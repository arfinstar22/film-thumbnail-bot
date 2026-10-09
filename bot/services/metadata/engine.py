import asyncio
import logging
from typing import Any, Dict, Optional

from .parser import FilenameParser
from .caption import CaptionGenerator
from .cache import MetadataCache
from .synopsis import WikipediaSynopsisService
from .rating import MovieRatingService

logger = logging.getLogger(__name__)


class MetadataEngine:
    """Smart Offline Filename Metadata Engine.
    100% fast, deterministic, no AI API needed."""

    def __init__(self, groq_api_key: Optional[str] = None):
        self.parser = FilenameParser()
        self.caption_gen = CaptionGenerator()
        self.cache = MetadataCache()
        self.synopsis_service = WikipediaSynopsisService(cache=self.cache)
        self.rating_service = MovieRatingService(cache=self.cache)

    async def process(
        self,
        filename: str,
        extra: Optional[Dict[str, Any]] = None,
        watermark: Optional[str] = None,
        enable_synopsis: bool = True
    ) -> Dict[str, Any]:
        metadata = self.parser.parse(filename)
        if extra:
            metadata.update(extra)

        title = metadata.get("title")
        year = metadata.get("year")
        season = metadata.get("season")
        episode = metadata.get("episode")
        is_series = bool(season is not None or episode is not None)

        if title:
            tasks = []
            if enable_synopsis and not metadata.get("synopsis"):
                tasks.append(self.synopsis_service.get_synopsis(title, year, is_series=is_series, genre=metadata.get("genre")))
            else:
                tasks.append(asyncio.sleep(0, result=""))

            if not metadata.get("rating") or not metadata.get("genre"):
                tasks.append(self.rating_service.get_rating_and_genre(title, year))
            else:
                tasks.append(asyncio.sleep(0, result={}))

            syn_res, rate_res = await asyncio.gather(*tasks)

            if rate_res:
                if rate_res.get("rating") and not metadata.get("rating"):
                    metadata["rating"] = rate_res["rating"]
                if rate_res.get("genre") and not metadata.get("genre"):
                    metadata["genre"] = rate_res["genre"]
                if rate_res.get("director") and not metadata.get("director"):
                    metadata["director"] = rate_res["director"]
                if rate_res.get("actors") and not metadata.get("actors"):
                    metadata["actors"] = rate_res["actors"]
                if rate_res.get("country") and not metadata.get("country"):
                    metadata["country"] = rate_res["country"]

            if syn_res and not metadata.get("synopsis"):
                metadata["synopsis"] = syn_res
            elif enable_synopsis and not metadata.get("synopsis"):
                if rate_res and rate_res.get("plot"):
                    translated_plot = self.synopsis_service.translate_if_needed(rate_res["plot"])
                    if translated_plot:
                        metadata["synopsis"] = translated_plot
                if not metadata.get("synopsis"):
                    metadata["synopsis"] = self.synopsis_service.get_fallback_synopsis(
                        title, year, metadata.get("genre") or (rate_res.get("genre") if rate_res else None)
                    )

        caption = self.caption_gen.generate(metadata, custom_watermark=watermark)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "local", "metadata": metadata}

    def extract_metadata(self, caption: str = "", filename: str = "") -> Dict[str, Any]:
        """Extracts title, year, rating, genre, etc. from caption text or filename."""
        import re
        meta: Dict[str, Any] = {}
        if filename:
            try:
                meta = self.parser.parse(filename)
            except Exception:
                meta = {}

        if caption:
            clean = re.sub(r"<[^>]+>", "", caption).strip()
            lines = [line.strip() for line in clean.splitlines() if line.strip()]
            if lines and not meta.get("title"):
                first_line = lines[0]
                m = re.search(r"^(.*?)\s*\((\d{4})\)", first_line)
                if m:
                    meta["title"] = m.group(1).strip()
                    try:
                        meta["year"] = int(m.group(2))
                    except Exception:
                        pass
                else:
                    meta["title"] = first_line

            # Rating
            rate_match = re.search(r"(?:Rating|IMDb|Skor|⭐)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*10)?", clean, re.IGNORECASE)
            if rate_match and not meta.get("rating"):
                meta["rating"] = rate_match.group(1).strip()

            # Genre
            genre_match = re.search(r"(?:Genre|🎭)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if genre_match and not meta.get("genre"):
                meta["genre"] = genre_match.group(1).strip()

            # Country
            country_match = re.search(r"(?:Negara|Country|🌍)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if country_match and not meta.get("country"):
                meta["country"] = country_match.group(1).strip()

            # Director
            dir_match = re.search(r"(?:Sutradara|Director)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if dir_match and not meta.get("director"):
                meta["director"] = dir_match.group(1).strip()

            # Actors
            act_match = re.search(r"(?:Pemeran|Aktor|Bintang|Cast|Actors|👥)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if act_match and not meta.get("actors"):
                meta["actors"] = act_match.group(1).strip()

            # Synopsis
            syn_match = re.search(r"(?:Sinopsis|Storyline|Deskripsi)\s*[:：]?\s*\n*(.*?)(?=\n\n|\Z)", clean, re.IGNORECASE | re.DOTALL)
            if syn_match and not meta.get("synopsis"):
                meta["synopsis"] = syn_match.group(1).strip()

        return meta

    async def enrich_metadata(self, raw_meta: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        """Enriches raw metadata with synopsis, rating, and genre."""
        meta = dict(raw_meta or {})
        title = meta.get("title") or query
        year = meta.get("year")
        season = meta.get("season")
        episode = meta.get("episode")
        is_series = bool(season is not None or episode is not None)

        tasks = []
        if not meta.get("synopsis") and title:
            tasks.append(self.synopsis_service.get_synopsis(title, year, is_series=is_series, genre=meta.get("genre")))
        else:
            tasks.append(asyncio.sleep(0, result=""))

        if (not meta.get("rating") or not meta.get("genre")) and title:
            tasks.append(self.rating_service.get_rating_and_genre(title, year))
        else:
            tasks.append(asyncio.sleep(0, result={}))

        syn_res, rate_res = await asyncio.gather(*tasks)

        if rate_res:
            if rate_res.get("rating") and not meta.get("rating"):
                meta["rating"] = rate_res["rating"]
            if rate_res.get("genre") and not meta.get("genre"):
                meta["genre"] = rate_res["genre"]
            if rate_res.get("director") and not meta.get("director"):
                meta["director"] = rate_res["director"]
            if rate_res.get("actors") and not meta.get("actors"):
                meta["actors"] = rate_res["actors"]
            if rate_res.get("country") and not meta.get("country"):
                meta["country"] = rate_res["country"]

        if syn_res and not meta.get("synopsis"):
            meta["synopsis"] = syn_res
        elif not meta.get("synopsis") and title:
            if rate_res and rate_res.get("plot"):
                translated_plot = self.synopsis_service.translate_if_needed(rate_res["plot"])
                if translated_plot:
                    meta["synopsis"] = translated_plot
            if not meta.get("synopsis"):
                meta["synopsis"] = self.synopsis_service.get_fallback_synopsis(
                    title, year, meta.get("genre") or (rate_res.get("genre") if rate_res else None)
                )

        return meta