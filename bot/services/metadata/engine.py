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
                tasks.append(self.synopsis_service.get_synopsis(title, year, is_series=is_series))
            else:
                tasks.append(asyncio.sleep(0, result=""))

            if not metadata.get("rating") or not metadata.get("genre"):
                tasks.append(self.rating_service.get_rating_and_genre(title, year))
            else:
                tasks.append(asyncio.sleep(0, result={}))

            syn_res, rate_res = await asyncio.gather(*tasks)

            if syn_res and not metadata.get("synopsis"):
                metadata["synopsis"] = syn_res

            if rate_res:
                if rate_res.get("rating") and not metadata.get("rating"):
                    metadata["rating"] = rate_res["rating"]
                if rate_res.get("genre") and not metadata.get("genre"):
                    metadata["genre"] = rate_res["genre"]

        caption = self.caption_gen.generate(metadata, custom_watermark=watermark)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "local", "metadata": metadata}