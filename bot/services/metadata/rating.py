import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any

from .cache import MetadataCache

logger = logging.getLogger(__name__)

GENRE_MAP = {
    "action": "Aksi",
    "adventure": "Petualangan",
    "animation": "Animasi",
    "biography": "Biografi",
    "comedy": "Komedi",
    "crime": "Kriminal",
    "documentary": "Dokumenter",
    "drama": "Drama",
    "family": "Keluarga",
    "fantasy": "Fantasi",
    "history": "Sejarah",
    "horror": "Horor",
    "music": "Musik",
    "musical": "Musikal",
    "mystery": "Misteri",
    "romance": "Romantis",
    "sci-fi": "Sci-Fi",
    "sport": "Olahraga",
    "thriller": "Thriller",
    "war": "Perang",
    "western": "Western"
}


class MovieRatingService:
    """Zero-cost movie rating, genre, plot, director, and cast fetcher using IMDb Suggest & OMDB."""

    def __init__(self, cache: Optional[MetadataCache] = None):
        self.cache = cache or MetadataCache()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def _translate_genres(self, genre_str: str) -> str:
        if not genre_str or genre_str == "N/A":
            return ""
        parts = [g.strip() for g in genre_str.split(",") if g.strip()]
        translated = [GENRE_MAP.get(p.lower(), p) for p in parts]
        return ", ".join(translated)

    def _sync_fetch(self, title: str, year: Optional[int] = None) -> Dict[str, str]:
        if not title:
            return {}

        clean_title = re.sub(r"[^\w\s]", "", title).strip()
        cache_key = f"rating_v2_{clean_title.lower()}_{year}" if year else f"rating_v2_{clean_title.lower()}"
        cached_raw = self.cache.get_setting(cache_key, "")
        if cached_raw:
            try:
                return json.loads(cached_raw)
            except Exception:
                pass

        imdb_id = None

        # Step 1: IMDb Suggest API
        try:
            first_char = "a"
            for ch in clean_title.lower():
                if ch.isascii() and ch.isalnum():
                    first_char = ch
                    break
            slug = urllib.parse.quote(clean_title.lower().replace(" ", "_"))
            url_suggest = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{slug}.json"
            req = urllib.request.Request(url_suggest, headers=self.headers)
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("d", [])
                for it in items:
                    it_id = it.get("id", "")
                    if it_id.startswith("tt"):
                        if year and it.get("y") and abs(it["y"] - year) <= 1:
                            imdb_id = it_id
                            break
                        elif not imdb_id:
                            imdb_id = it_id
        except Exception as e:
            logger.debug(f"IMDb suggest error: {e}")

        # Step 2: OMDB Endpoint
        omdb_urls = []
        if imdb_id:
            omdb_urls.append(f"http://www.omdbapi.com/?i={imdb_id}&apikey=trilogy")
        if year:
            omdb_urls.append(f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&y={year}&apikey=trilogy")
        omdb_urls.append(f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey=trilogy")

        for u in omdb_urls:
            try:
                req = urllib.request.Request(u, headers=self.headers)
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("Response") == "True":
                        rating = data.get("imdbRating")
                        raw_genre = data.get("Genre")
                        genre = self._translate_genres(raw_genre)
                        res = {}
                        if rating and rating != "N/A":
                            res["rating"] = f"{rating} / 10 • IMDb"
                        elif data.get("Rated") and data["Rated"] != "N/A":
                            res["rating"] = f"Rated {data['Rated']} • IMDb"
                        if genre:
                            res["genre"] = genre
                        if data.get("Director") and data["Director"] != "N/A":
                            res["director"] = data["Director"]
                        if data.get("Actors") and data["Actors"] != "N/A":
                            res["actors"] = data["Actors"]
                        if data.get("Plot") and data["Plot"] != "N/A":
                            res["plot"] = data["Plot"]
                        if res:
                            self.cache.set_setting(cache_key, json.dumps(res))
                            return res
            except Exception:
                continue

        # Save empty result to avoid re-fetching failed queries
        self.cache.set_setting(cache_key, json.dumps({}))
        return {}

    async def get_rating_and_genre(self, title: str, year: Optional[int] = None) -> Dict[str, str]:
        return await asyncio.to_thread(self._sync_fetch, title, year)
