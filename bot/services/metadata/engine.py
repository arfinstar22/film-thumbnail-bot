import logging
from typing import Any, Dict, Optional

from .parser import FilenameParser
from .caption import CaptionGenerator
from .cache import MetadataCache
from .synopsis import WikipediaSynopsisService

logger = logging.getLogger(__name__)


class MetadataEngine:
    """Smart Offline Filename Metadata Engine.
    100% fast, deterministic, no AI API needed."""

    def __init__(self, groq_api_key: Optional[str] = None):
        self.parser = FilenameParser()
        self.caption_gen = CaptionGenerator()
        self.cache = MetadataCache()
        self.synopsis_service = WikipediaSynopsisService(cache=self.cache)

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

        if enable_synopsis and not metadata.get("synopsis"):
            title = metadata.get("title")
            year = metadata.get("year")
            season = metadata.get("season")
            episode = metadata.get("episode")
            is_series = bool(season is not None or episode is not None)
            if title:
                syn = await self.synopsis_service.get_synopsis(title, year, is_series=is_series)
                if syn:
                    metadata["synopsis"] = syn

        caption = self.caption_gen.generate(metadata, custom_watermark=watermark)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "local", "metadata": metadata}