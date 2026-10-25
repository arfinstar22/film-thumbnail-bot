import unittest
import tempfile
import os
import time
from bot.services.metadata.cache import MetadataCache


class TestUserManagementCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.cache = MetadataCache(db_path=self.tmp.name)

    def tearDown(self):
        try:
            os.remove(self.tmp.name)
        except Exception:
            pass

    def test_block_and_unblock_user(self):
        self.cache.register_bot_user(12345, "testuser", "Test")
        self.assertFalse(self.cache.is_user_banned(12345)[0])

        # Block user manually
        self.cache.block_user(12345, reason="Banned by admin")
        is_banned, reason, _ = self.cache.is_user_banned(12345)
        self.assertTrue(is_banned)
        self.assertEqual(reason, "Banned by admin")

        # Unblock user
        self.cache.unblock_user(12345)
        is_banned, reason, _ = self.cache.is_user_banned(12345)
        self.assertFalse(is_banned)

    def test_temporary_ban_and_auto_expiry(self):
        self.cache.register_bot_user(67890, "spammer", "Spam")
        # Ban for 1 second
        self.cache.ban_user(67890, duration_seconds=1, reason="Spam chat terus-menerus")
        is_banned, reason, _ = self.cache.is_user_banned(67890)
        self.assertTrue(is_banned)
        self.assertEqual(reason, "Spam chat terus-menerus")

        # After expiration (> 1.2s), is_user_banned should auto-lift ban
        time.sleep(1.2)
        is_banned, _, _ = self.cache.is_user_banned(67890)
        self.assertFalse(is_banned)

    def test_get_bot_users_pagination(self):
        for i in range(1, 15):
            self.cache.register_bot_user(i, f"user_{i}", f"Name {i}")

        users, total_pages = self.cache.get_bot_users(page=1, page_size=10)
        self.assertEqual(len(users), 10)
        self.assertEqual(total_pages, 2)
        self.assertIn("user_id", users[0])
        self.assertIn("is_blocked", users[0])

        page2_users, _ = self.cache.get_bot_users(page=2, page_size=10)
        self.assertEqual(len(page2_users), 4)
