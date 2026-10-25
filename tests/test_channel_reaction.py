import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from bot.handlers import CHANNEL_REACTION_EMOJIS, _send_random_channel_reaction


class TestChannelReaction(unittest.IsolatedAsyncioTestCase):
    def test_reaction_emojis_list(self):
        """Should have an expressive set of reaction emojis."""
        self.assertIsInstance(CHANNEL_REACTION_EMOJIS, list)
        self.assertGreaterEqual(len(CHANNEL_REACTION_EMOJIS), 5)
        self.assertIn("🔥", CHANNEL_REACTION_EMOJIS)
        self.assertIn("🍿", CHANNEL_REACTION_EMOJIS)

    async def test_send_random_channel_reaction_success(self):
        """Should call Bot API setMessageReaction and succeed."""
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"ok": true, "result": true}'
            mock_url.return_value.__enter__.return_value = mock_resp

            res = await _send_random_channel_reaction(None, "@test_channel", 123)
            self.assertTrue(res)
            self.assertTrue(mock_url.called)

    async def test_send_random_channel_reaction_safe_on_error(self):
        """Should never throw and return False if reaction fails."""
        with patch("urllib.request.urlopen", side_effect=Exception("Chat not found")):
            mock_client = MagicMock()
            mock_client.send_reaction = AsyncMock(side_effect=Exception("Pyrogram reaction error"))
            res = await _send_random_channel_reaction(mock_client, "@test_channel", 123)
            self.assertFalse(res)
