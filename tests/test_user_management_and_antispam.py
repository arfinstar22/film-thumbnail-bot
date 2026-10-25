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


class TestAntiSpamAndMiddleware(unittest.TestCase):
    def test_absolute_admin_immunity(self):
        """Absolute admin must be completely immune to anti-spam and bans."""
        from bot.handlers import is_owner, _check_antispam_and_banned
        from bot.config import ABSOLUTE_ADMIN_USER_IDS
        admin_id = list(ABSOLUTE_ADMIN_USER_IDS)[0]

        self.assertTrue(is_owner(admin_id))

        # Sending 20 messages rapidly should NEVER trigger ban for absolute admin
        for _ in range(20):
            blocked, _ = _check_antispam_and_banned(admin_id, "dxstar22", "Darfin")
            self.assertFalse(blocked)

    def test_regular_user_spam_triggers_ban(self):
        """Regular user typing continuously should trigger 1-day ban."""
        from bot.handlers import _check_antispam_and_banned, _user_message_timestamps, _engine
        user_id = 999111
        _user_message_timestamps.pop(user_id, None)
        _engine.cache.unblock_user(user_id)

        # First message is OK
        blocked, _ = _check_antispam_and_banned(user_id, "testuser", "Normal")
        self.assertFalse(blocked)

        # Rapidly spam messages (> 5 messages within 3 seconds)
        banned = False
        alert_msg = ""
        for _ in range(6):
            blocked, alert = _check_antispam_and_banned(user_id, "testuser", "Normal")
            if blocked:
                banned = True
                alert_msg = alert
                break

        self.assertTrue(banned)
        self.assertIn("1 hari", alert_msg.lower())

        # Now is_user_banned in cache should be True
        is_b, reason, _ = _engine.cache.is_user_banned(user_id)
        self.assertTrue(is_b)
        self.assertIn("spam", reason.lower())

        # Subsequent messages should immediately be blocked
        blocked, alert_sub = _check_antispam_and_banned(user_id, "testuser", "Normal")
        self.assertTrue(blocked)

