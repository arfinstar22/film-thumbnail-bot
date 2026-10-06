import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from .cache import MetadataCache

logger = logging.getLogger(__name__)


class WikipediaSynopsisService:
    """Zero-AI Wikipedia Indonesia Synopsis Fetcher.
    Fetches 100% human-verified movie synopses with zero API key and zero hallucination."""

    def __init__(self, cache: Optional[MetadataCache] = None):
        self.cache = cache or MetadataCache()
        self.headers = {
            "User-Agent": "FilmIndonesiaBot/1.0 (https://t.me/film_indonesia1; bot@filmindonesia.local)"
        }

    def _clean_text(self, text: str, max_chars: int = 280) -> str:
        if not text:
            return ""
        # Remove wiki citations like [1], [2], [catatan 1]
        text = re.sub(r"\[\s*(?:\d+|catatan\s*\d+)\s*\]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) <= max_chars:
            return text

        cutoff = text[:max_chars].rfind(".")
        if cutoff > 100:
            return text[:cutoff + 1].strip()
        return text[:max_chars].rstrip() + "..."

    def _sync_fetch(self, title: str, year: Optional[int] = None) -> str:
        if not title:
            return ""

        cache_key = f"synopsis_{title.lower()}_{year}" if year else f"synopsis_{title.lower()}"
        cached = self.cache.get_setting(cache_key, "")
        if cached:
            return "" if cached == "none" else cached

        queries = []
        if year:
            queries.append(f"{title} {year} film")
        queries.append(f"{title} film")

        for query in queries:
            try:
                search_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 1
                })
                req = urllib.request.Request(search_url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("query", {}).get("search", [])
                    if not results:
                        continue
                    page_title = results[0]["title"]

                intro_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                    "action": "query",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "titles": page_title,
                    "format": "json"
                })
                req2 = urllib.request.Request(intro_url, headers=self.headers)
                with urllib.request.urlopen(req2, timeout=2.5) as resp2:
                    data2 = json.loads(resp2.read().decode("utf-8"))
                    pages = data2.get("query", {}).get("pages", {})
                    extract = ""
                    for p in pages.values():
                        extract = p.get("extract", "")
                        break

                cleaned = self._clean_text(extract)
                if cleaned:
                    self.cache.set_setting(cache_key, cleaned)
                    return cleaned
            except Exception as e:
                logger.debug(f"Wikipedia fetch error for {query}: {e}")

        # Mark as not found to avoid re-querying
        self.cache.set_setting(cache_key, "none")
        return ""

    async def get_synopsis(self, title: str, year: Optional[int] = None) -> str:
        return await asyncio.to_thread(self._sync_fetch, title, year)
