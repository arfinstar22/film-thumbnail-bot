import logging
from typing import Any, Dict, Optional

from .parser import FilenameParser
from .caption import CaptionGenerator
from .cache import MetadataCache

logger = logging.getLogger(__name__)


class MetadataEngine:
    """Smart Offline Filename Metadata Engine.
    100% fast, deterministic, no AI API needed."""

    def __init__(self, groq_api_key: Optional[str] = None):
        self.parser = FilenameParser()
        self.caption_gen = CaptionGenerator()
        self.cache = MetadataCache()

    async def process(
        self,
        filename: str,
        extra: Optional[Dict[str, Any]] = None,
        watermark: Optional[str] = None
    ) -> Dict[str, Any]:
        metadata = self.parser.parse(filename)
        if extra:
            metadata.update(extra)

        caption = self.caption_gen.generate(metadata, custom_watermark=watermark)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "local", "metadata": metadata}