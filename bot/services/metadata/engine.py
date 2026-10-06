import logging
from typing import Any, Dict

from .parser import FilenameParser
from .caption import CaptionGenerator
from .cache import MetadataCache
from .ai_refiner import AIRefiner

logger = logging.getLogger(__name__)


class MetadataEngine:
    """Filename -> Smart Parser -> Dictionary -> Confidence -> Caption.
    AI is only used as fallback when confidence is low."""

    def __init__(self, groq_api_key: str = None):
        self.parser = FilenameParser()
        self.caption_gen = CaptionGenerator()
        self.cache = MetadataCache()
        self.ai = AIRefiner(groq_api_key)

    async def process(self, filename: str) -> Dict[str, Any]:
        # 1. Check cache (filename hash as key)
        cached = self.cache.get_caption(filename)
        if cached:
            logger.info("Cache hit for %s", filename)
            return {"caption": cached, "source": "cache"}

        # 2. Parse locally
        metadata = self.parser.parse(filename)
        overall_conf = metadata.get("confidence", {}).get("overall", 0.0)
        uncertain = metadata.get("uncertainFields", [])
        logger.info(
            "Parsed '%s' -> overall confidence %.2f, uncertain=%s",
            filename, overall_conf, uncertain,
        )

        # 3. Only use AI if confidence low OR uncertain fields exist
        if overall_conf >= 0.70 and not uncertain:
            caption = self.caption_gen.generate(metadata)
            self.cache.save_caption(filename, caption)
            return {"caption": caption, "source": "local"}

        # 4. AI fallback
        refined = await self.ai.refine(metadata)
        caption = self.caption_gen.generate(refined)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "ai", "metadata": refined}