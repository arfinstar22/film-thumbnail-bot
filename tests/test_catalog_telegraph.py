import json
import unittest
from unittest.mock import patch

from bot.services.metadata.catalog import (
    _build_index_page_nodes,
    _publish_page,
)


class FakeCache:
    def __init__(self):
        self.data = {}

    def get_setting(self, key, default=""):
        return self.data.get(key, default)

    def set_setting(self, key, value):
        self.data[key] = str(value)


class TestTelegraphCatalogRefresh(unittest.TestCase):
    def test_unchanged_page_is_not_edited_again(self):
        """A full catalog refresh must not re-edit every unchanged A-Z page."""
        cache = FakeCache()
        calls = []

        def fake_api(endpoint, payload, timeout=15, max_attempts=3):
            calls.append(endpoint)
            return {"path": "Katalog-Test-01-01", "url": "https://telegra.ph/Katalog-Test-01-01"}

        nodes = [{"tag": "p", "children": ["Film A"]}]
        with patch("bot.services.metadata.catalog._telegraph_api", side_effect=fake_api):
            url1, wrote1 = _publish_page("token", "Katalog", nodes, "chan", cache, "key")
            url2, wrote2 = _publish_page("token", "Katalog", nodes, "chan", cache, "key")

        self.assertEqual(url1, "https://telegra.ph/Katalog-Test-01-01")
        self.assertEqual(url1, url2)
        self.assertTrue(wrote1)
        self.assertFalse(wrote2)
        self.assertEqual(calls, ["createPage"])

    def test_changed_page_is_edited(self):
        cache = FakeCache()
        calls = []

        def fake_api(endpoint, payload, timeout=15, max_attempts=3):
            calls.append(endpoint)
            return {"path": "Katalog-Test-01-01", "url": "https://telegra.ph/Katalog-Test-01-01"}

        with patch("bot.services.metadata.catalog._telegraph_api", side_effect=fake_api):
            _publish_page("token", "Katalog", [{"tag": "p", "children": ["A"]}], "chan", cache, "key")
            _publish_page("token", "Katalog", [{"tag": "p", "children": ["B"]}], "chan", cache, "key")

        self.assertEqual(calls, ["createPage", "editPage"])

    def test_failed_edit_is_retried_on_next_refresh(self):
        """A failed edit must NOT be cached as success; next refresh retries it."""
        cache = FakeCache()
        calls = []

        def fake_api(endpoint, payload, timeout=15, max_attempts=3):
            calls.append(endpoint)
            if endpoint == "editPage":
                return None
            return {"path": "Katalog-Test-01-01", "url": "https://telegra.ph/Katalog-Test-01-01"}

        changed = [{"tag": "p", "children": ["Film Baru"]}]
        with patch("bot.services.metadata.catalog._telegraph_api", side_effect=fake_api):
            _publish_page("token", "Katalog", [{"tag": "p", "children": ["Lama"]}], "chan", cache, "key")
            url2, _ = _publish_page("token", "Katalog", changed, "chan", cache, "key")
            # Same content again: hash was not stored after the failed edit, so retry.
            _publish_page("token", "Katalog", changed, "chan", cache, "key")

        self.assertEqual(url2, "https://telegra.ph/Katalog-Test-01-01")
        self.assertEqual(calls, ["createPage", "editPage", "editPage"])

    def test_index_links_every_chunk_of_a_split_letter(self):
        """Films in part 2+ must be reachable from the master index."""
        nodes = _build_index_page_nodes(
            [{"title": "Perahu Kertas", "year": 2012, "message_id": 1}],
            [("P", 120, ["https://telegra.ph/P-1", "https://telegra.ph/P-2"])],
            "film_indonesia1",
            "@bot",
        )
        rendered = json.dumps(nodes)
        self.assertIn("https://telegra.ph/P-1", rendered)
        self.assertIn("https://telegra.ph/P-2", rendered)
        self.assertIn("Bagian 1/2", rendered)
        self.assertIn("Bagian 2/2", rendered)


if __name__ == "__main__":
    unittest.main()
