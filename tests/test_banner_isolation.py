import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.handlers import (
    _is_matching_banner_session,
    _banner_sessions,
    _jobs,
)


class TestBannerIsolation(unittest.TestCase):
    def setUp(self):
        _banner_sessions.clear()
        _jobs.clear()

    def tearDown(self):
        _banner_sessions.clear()
        _jobs.clear()

    def test_matching_banner_session_true(self):
        session = {
            "metadata": {"title": "Lavender Marriage", "year": 2025},
            "query": "Lavender Marriage"
        }
        job = {
            "metadata": {"title": "Lavender Marriage", "year": 2025},
            "filename": "Lavender.Marriage.2025.mkv"
        }
        self.assertTrue(_is_matching_banner_session(session, job))

    def test_matching_banner_session_different_titles(self):
        session = {
            "metadata": {"title": "Lavender Marriage", "year": 2025},
            "query": "Lavender Marriage"
        }
        job = {
            "metadata": {"title": "Mata Batin", "year": 2017},
            "filename": "Mata.Batin.2017.mkv"
        }
        self.assertFalse(_is_matching_banner_session(session, job))

    def test_matching_banner_session_different_years(self):
        session = {
            "metadata": {"title": "Pengabdi Setan", "year": 1980},
            "query": "Pengabdi Setan"
        }
        job = {
            "metadata": {"title": "Pengabdi Setan", "year": 2017},
            "filename": "Pengabdi.Setan.2017.mkv"
        }
        self.assertFalse(_is_matching_banner_session(session, job))

    def test_matching_banner_session_none_or_empty(self):
        self.assertFalse(_is_matching_banner_session(None, {"metadata": {"title": "Test"}}))
        self.assertFalse(_is_matching_banner_session({}, {"metadata": {"title": "Test"}}))
        self.assertFalse(_is_matching_banner_session({"metadata": {"title": "Test"}}, None))
        self.assertFalse(_is_matching_banner_session({"metadata": {"title": ""}}, {"metadata": {"title": ""}}))

    def test_stale_banner_session_isolation_on_new_film(self):
        chat_id = 12345
        # Simulate film 1 having custom photo/banner in _banner_sessions
        _banner_sessions[chat_id] = {
            "metadata": {"title": "Film Pertama", "year": 2020},
            "poster_url": "/tmp/custom_film1.jpg",
            "banner_path": "/tmp/banner_film1.jpg",
            "query": "Film Pertama"
        }

        # Film 2 is uploaded
        job2 = {
            "chat_id": chat_id,
            "filename": "Film.Kedua.2024.mkv",
            "metadata": {"title": "Film Kedua", "year": 2024, "poster_url": "https://tmdb/poster2.jpg"},
            "poster_url": "https://tmdb/poster2.jpg",
            "thumb_path": "/tmp/thumb2.jpg",
            "caption_text": "Film Kedua caption"
        }
        _jobs[chat_id] = job2

        # Check session match
        session = _banner_sessions.get(chat_id)
        self.assertFalse(_is_matching_banner_session(session, job2))

        # When evaluated for posting:
        if session and not _is_matching_banner_session(session, job2):
            session = None
            _banner_sessions.pop(chat_id, None)

        self.assertIsNone(session)
        self.assertNotIn(chat_id, _banner_sessions)

        meta2 = job2.get("metadata", {})
        latest_poster = (
            job2.get("poster_url")
            or meta2.get("poster_url")
            or meta2.get("poster_path")
            or (session.get("poster_url") if session else None)
            or job2.get("thumb_path")
        )
        banner_file = job2.get("banner_path") or (session.get("banner_path") if session else None)

        # Must be Film 2's poster, NOT Film 1's custom photo
        self.assertEqual(latest_poster, "https://tmdb/poster2.jpg")
        # Must be None, so publish_video_to_channel generates a fresh banner for Film 2
        self.assertIsNone(banner_file)


if __name__ == "__main__":
    unittest.main()
