import asyncio
import os
import sys
import unittest
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/home/darfinstar/projectTumbnail/.env")

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata.parser import FilenameParser
from bot.services.video import inspect_media_streams


class TestAdvancedFeatures(unittest.TestCase):
    def setUp(self):
        self.test_db = "/tmp/test_advanced_feat.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.cache = MetadataCache(self.test_db)
        self.parser = FilenameParser()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    # ================= 1. AUTO-FULFILL & SMART MATCHING =================
    def test_auto_fulfill_strict_matching_rasuk_vs_paraperasuk(self):
        """User requested 'Rasuk (2018)'. Admin posts 'Para Perasuk (2026)'. Must NOT fulfill."""
        self.cache.add_movie_request(101, "andi", "Rasuk (2018)", "film_indonesia1")
        self.cache.add_movie_request(102, "budi", "Para Perasuk (2026)", "film_indonesia1")

        # Check matching for Para Perasuk (2026)
        matched = self.cache.find_matching_requests("Para Perasuk", year=2026)
        matched_user_ids = [m["user_id"] for m in matched]
        self.assertIn(102, matched_user_ids)
        self.assertNotIn(101, matched_user_ids)

        # Fulfill Para Perasuk
        fulfilled = self.cache.fulfill_movie_requests("Para Perasuk", "film_indonesia1", year=2026)
        fulfilled_user_ids = [m["user_id"] for m in fulfilled]
        self.assertIn(102, fulfilled_user_ids)
        self.assertNotIn(101, fulfilled_user_ids)

        # Andi's request for Rasuk (2018) must still be pending
        pending = self.cache.get_pending_requests("film_indonesia1")
        self.assertEqual(len(pending), 1)
        self.assertIn(101, pending[0]["user_ids"])

        # Now fulfill Rasuk (2018)
        fulfilled_rasuk = self.cache.fulfill_movie_requests("Rasuk", "film_indonesia1", year=2018)
        self.assertEqual(len(fulfilled_rasuk), 1)
        self.assertEqual(fulfilled_rasuk[0]["user_id"], 101)

        # Now all fulfilled
        pending_after = self.cache.get_pending_requests("film_indonesia1")
        self.assertEqual(len(pending_after), 0)

    def test_auto_fulfill_sequel_differentiation(self):
        """User requested 'Pengabdi Setan'. Admin posts 'Pengabdi Setan 2 (2022)'. Must NOT fulfill part 1."""
        self.cache.add_movie_request(201, "citra", "Pengabdi Setan", "film_indonesia1")
        self.cache.add_movie_request(202, "dono", "Pengabdi Setan 2", "film_indonesia1")

        # Post Pengabdi Setan 2
        fulfilled = self.cache.fulfill_movie_requests("Pengabdi Setan 2", "film_indonesia1", year=2022)
        fulfilled_user_ids = [m["user_id"] for m in fulfilled]
        self.assertIn(202, fulfilled_user_ids)
        self.assertNotIn(201, fulfilled_user_ids)

    # ================= 2. AUTO AUDIO & SUBTITLE INSPECTOR =================
    def test_auto_audio_and_subtitle_filename_parsing(self):
        """FilenameParser should automatically detect audio presets and subtitles."""
        meta1 = self.parser.parse("Agak.Laen.2024.1080p.NF.WEB-DL.Softsub.Indo.mkv")
        self.assertEqual(meta1.get("subtitle"), "Softsub Indo")
        self.assertEqual(meta1.get("resolution"), "1080p")
        self.assertEqual(meta1.get("title"), "Agak Laen")

        meta2 = self.parser.parse("Spirited.Away.2001.Dub.Indo.x264.mkv")
        self.assertEqual(meta2.get("audio"), "Dub Indo")
        self.assertEqual(meta2.get("title"), "Spirited Away")

        meta3 = self.parser.parse("One.Piece.Film.Red.2022.Hardsub.Indo.1080p.mkv")
        self.assertEqual(meta3.get("subtitle"), "Hardsub Indo")

        meta4 = self.parser.parse("Avatar.2009.Dual.Audio.1080p.mkv")
        self.assertEqual(meta4.get("audio"), "Dual Audio (ID+EN)")


    # ================= 4. PRIME-TIME SEQUENTIAL SCHEDULING =================
    def test_prime_time_scheduling_queue(self):
        """Should schedule multiple movies into consecutive prime-time slots."""
        chat_id = 112233
        titles = ["Gundala", "Sri Asih", "Virgo and the Sparklings"]
        for t in titles:
            self.cache.add_scheduled_post(
                chat_id=chat_id,
                video_file_id=f"fid_{t}",
                caption_text=f"Caption for {t}",
                metadata={"title": t, "year": 2022},
                watermark="@film_indonesia1",
                title=t
            )

        pending = self.cache.get_pending_scheduled_posts()
        self.assertEqual(len(pending), 3)

        # Check timestamps are ordered ascending
        timestamps = [p["scheduled_timestamp"] for p in pending]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertTrue(len(set(timestamps)) == 3)  # distinct prime-time slots

    # ================= 5. MOOD RECOMMENDER =================
    def test_mood_recommender_filters_and_ranking(self):
        """Should filter catalog by mood and sort by rating descending."""
        channel = "film_indonesia1"
        self.cache.save_movie_post("Pengabdi Setan 2", year=2022, rating="7.4", genre="Horror, Mystery", quality="1080p", channel_username=channel, message_id=101)
        self.cache.save_movie_post("KKN di Desa Penari", year=2022, rating="6.8", genre="Horor", quality="1080p", channel_username=channel, message_id=102)
        self.cache.save_movie_post("Agak Laen", year=2024, rating="7.8", genre="Comedy", quality="1080p", channel_username=channel, message_id=103)
        self.cache.save_movie_post("Warkop DKI Reborn", year=2016, rating="6.5", genre="Komedi", quality="1080p", channel_username=channel, message_id=104)
        self.cache.save_movie_post("The Raid", year=2011, rating="8.1", genre="Action, Crime", quality="1080p", channel_username=channel, message_id=105)
        self.cache.save_movie_post("Habibie & Ainun", year=2012, rating="7.6", genre="Drama, Romance", quality="1080p", channel_username=channel, message_id=106)

        # Mood Horror: must return Pengabdi Setan 2 first (7.4), then KKN (6.8)
        horror_movies = self.cache.get_movies_by_mood("horror", channel_username=channel)
        self.assertEqual(len(horror_movies), 2)
        self.assertEqual(horror_movies[0]["title"], "Pengabdi Setan 2")
        self.assertEqual(horror_movies[1]["title"], "KKN di Desa Penari")

        # Mood Comedy: must return Agak Laen (7.8), then Warkop (6.5)
        comedy_movies = self.cache.get_movies_by_mood("comedy", channel_username=channel)
        self.assertEqual(len(comedy_movies), 2)
        self.assertEqual(comedy_movies[0]["title"], "Agak Laen")
        self.assertEqual(comedy_movies[1]["title"], "Warkop DKI Reborn")

        # Mood Action: must return The Raid (8.1)
        action_movies = self.cache.get_movies_by_mood("action", channel_username=channel)
        self.assertEqual(len(action_movies), 1)
        self.assertEqual(action_movies[0]["title"], "The Raid")

        # Mood Romance: must return Habibie & Ainun (7.6)
        romance_movies = self.cache.get_movies_by_mood("romance", channel_username=channel)
        self.assertEqual(len(romance_movies), 1)
        self.assertEqual(romance_movies[0]["title"], "Habibie & Ainun")

        # Mood Random / Acak: returns sample from all movies
        random_sample = self.cache.get_movies_by_mood("random", channel_username=channel, limit=3)
        self.assertEqual(len(random_sample), 3)


if __name__ == "__main__":
    unittest.main()
