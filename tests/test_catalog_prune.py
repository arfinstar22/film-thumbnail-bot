import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock, AsyncMock
from bot.services.metadata.cache import MetadataCache
from bot.handlers import prune_dead_channel_catalog, clean_catalog_cmd


class TestCatalogPrune(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.cache = MetadataCache(db_path=self.tmp.name)

    def tearDown(self):
        try:
            os.remove(self.tmp.name)
        except Exception:
            pass

    async def test_prune_dead_channel_catalog_preserves_rich_posts(self):
        """Should prune deleted messages but preserve active rich posts and video posts."""
        # Insert 3 movies:
        # msg 101: Legacy post
        # msg 102: Rich article post (sendRichMessage)
        # msg 103: Deleted post
        self.cache.save_movie_post(
            title="Film Klasik",
            year=2000,
            rating="7.5",
            genre="Drama",
            quality="1080p",
            channel_username="testchannel",
            message_id=101
        )
        self.cache.save_movie_post(
            title="The Big 4 (Rich Post)",
            year=2022,
            rating="8.0",
            genre="Action",
            quality="1080p",
            channel_username="testchannel",
            message_id=102
        )
        self.cache.save_movie_post(
            title="Film Dihapus",
            year=2015,
            rating="6.0",
            genre="Horror",
            quality="720p",
            channel_username="testchannel",
            message_id=103
        )

        mock_client = MagicMock()

        # Mock message objects
        # 101: legacy video post
        m_legacy = MagicMock()
        m_legacy.id = 101
        m_legacy.empty = False
        m_legacy.service = False
        m_legacy.pinned_message = False

        # 102: rich post (Telegram returns empty caption/media but message exists)
        m_rich = MagicMock()
        m_rich.id = 102
        m_rich.empty = None
        m_rich.service = False
        m_rich.pinned_message = False
        m_rich.caption = None
        m_rich.text = None
        m_rich.video = None

        # 103: deleted post (Telegram returns empty=True or None)
        m_dead = MagicMock()
        m_dead.id = 103
        m_dead.empty = True

        mock_client.get_messages = AsyncMock(return_value=[m_legacy, m_rich, m_dead])

        with patch("bot.handlers._engine.cache", self.cache):
            total_checked, alive_count, pruned_count = await prune_dead_channel_catalog(
                mock_client,
                "@testchannel",
                "testchannel",
                batch_size=10
            )

        self.assertEqual(total_checked, 3)
        self.assertEqual(alive_count, 2)
        self.assertEqual(pruned_count, 1)

        # Check database: 101 and 102 must still exist; 103 must be removed
        conn = self.cache._conn()
        cur = conn.cursor()
        cur.execute("SELECT message_id, title FROM movie_catalog WHERE channel_username = 'testchannel' ORDER BY message_id ASC")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], 101)
        self.assertEqual(rows[1][0], 102)
        self.assertEqual(rows[1][1], "The Big 4 (Rich Post)")

    async def test_clean_catalog_cmd_flow(self):
        """Should execute clean_catalog_cmd successfully for channel admin."""
        mock_msg = MagicMock()
        mock_msg.chat.id = 12345
        mock_msg.text = "/bersihkatalog"
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        mock_msg.reply_text = AsyncMock(return_value=status_msg)

        mock_client = MagicMock()

        with patch("bot.handlers.check_admin", return_value=True), \
             patch("bot.handlers._get_user_watermark", return_value="@testchannel"), \
             patch("bot.handlers.prune_dead_channel_catalog", new_callable=AsyncMock) as mock_prune, \
             patch("bot.handlers.update_pinned_catalog", new_callable=AsyncMock) as mock_update_pin, \
             patch("bot.handlers.send_or_update_backup_document", new_callable=AsyncMock):
            mock_prune.return_value = (10, 8, 2)
            mock_update_pin.return_value = 8

            await clean_catalog_cmd(mock_client, mock_msg)

            mock_prune.assert_called_once_with(mock_client, "@testchannel", "testchannel")
            mock_update_pin.assert_called_once()
            status_msg.edit_text.assert_called()
            call_text = status_msg.edit_text.call_args[0][0]
            self.assertIn("Pembersihan Katalog Selesai", call_text)
            self.assertIn("Film Aktif Dipertahankan:", call_text)
            self.assertIn("Post Terhapus / Link Mati:", call_text)
