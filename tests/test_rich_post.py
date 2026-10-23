import unittest
from bot.services.metadata.rich_post import build_rich_article_payload


class TestRichArticlePost(unittest.TestCase):
    def test_build_rich_article_payload_structure(self):
        meta = {
            "title": "Ipar Itu Benalu",
            "year": 2026,
            "rating": "7.0",
            "genre": "Drama, Keluarga",
            "resolution": "1080p",
            "duration": "1 jam 40 menit",
            "fileSize": "1.5 GB",
            "actors": "Rina, Dimas, Siti",
            "director": "Budi Santoso",
            "synopsis": "Kisah rumah tangga Rina dan Dimas yang mulai goyah akibat kehadiran ipar.",
            "audio": "Indonesian AAC 2.0"
        }

        payload = build_rich_article_payload(
            chat_id="@testchannel",
            metadata=meta,
            watermark="@testchannel",
            video_file_id="BAACAgQAAxUHats3y8OINTYx5bjgO4-qhP-K2QEAApsIAAJxITxT0AaS0ATlhPk9BA",
            banner_file_id_or_url="banner_file_123",
            poster_file_id_or_url="poster_file_456",
            reply_markup={"inline_keyboard": [[{"text": "Tonton", "url": "https://t.me"}]]}
        )

        self.assertEqual(payload["chat_id"], "@testchannel")
        self.assertIn("rich_message", payload)
        rich_msg = payload["rich_message"]
        self.assertIn("html", rich_msg)
        html_content = rich_msg["html"]

        # Check native tags
        self.assertIn("<h1>🎬 IPAR ITU BENALU (2026)</h1>", html_content)
        self.assertIn("<tg-slideshow>", html_content)
        self.assertIn('<video src="tg://video?id=film_video"></video>', html_content)
        self.assertIn("<details>", html_content)
        self.assertIn("<summary>📖 Sinopsis Lengkap</summary>", html_content)
        self.assertIn("<summary>ℹ️ Detail Spesifikasi &amp; Pemain</summary>", html_content)
        self.assertIn("<footer>🍿 Channel Resmi: @testchannel</footer>", html_content)

        # Check media mapping
        self.assertIn("media", rich_msg)
        media_ids = [m["id"] for m in rich_msg["media"]]
        self.assertIn("film_video", media_ids)
        self.assertIn("banner_img", media_ids)
        self.assertIn("poster_img", media_ids)


if __name__ == "__main__":
    unittest.main()
