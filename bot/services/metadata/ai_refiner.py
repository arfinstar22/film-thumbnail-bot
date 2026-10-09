import json
import logging
import os
import re
from typing import Dict, Any, Optional
from groq import AsyncGroq

logger = logging.getLogger(__name__)

class AIRefiner:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = "llama-3.1-8b-instant"
        self._client = None

    def _get_client(self):
        if not self._client and self.api_key:
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def refine(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Only refine fields marked in 'uncertainFields' or if confidence is low.
        Returns the refined metadata.
        """
        uncertain = metadata.get("uncertainFields", [])
        overall_conf = metadata.get("confidence", {}).get("overall", 1.0)

        # Skip AI if high confidence and no uncertain fields
        if overall_conf >= 0.70 and not uncertain:
            logger.info("AI skipped: confidence is high (%.2f)", overall_conf)
            return metadata

        client = self._get_client()
        if not client:
            logger.warning("Groq API key not found, returning raw parsed metadata.")
            return metadata

        payload = {
            "filename": metadata.get("originalFilename"),
            "parsed": {
                "title": metadata.get("title"),
                "year": metadata.get("year"),
            },
            "uncertain": uncertain
        }

        prompt = f"Perbaiki bagian 'uncertain' dari data film ini. Kembalikan HANYA format JSON tanpa teks lain:\n{json.dumps(payload)}"

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Kembalikan hanya JSON murni sesuai schema: {'title': str, 'year': int}. Jangan halusinasi."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=150,
            )
            content = response.choices[0].message.content.strip()
            json_match = re.search(r"\{[^{}]*\}", content)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                if content.startswith("```"):
                    content = content.strip("`")
                    if content.startswith("json"):
                        content = content[4:].strip()
                result = json.loads(content)
            if "title" in result and result["title"]:
                metadata["title"] = result["title"]
            if "year" in result and result["year"]:
                metadata["year"] = result["year"]

            logger.info("AI refinement successful for %s", metadata.get("title"))
        except Exception as e:
            logger.error("AI refinement failed, using local parse: %s", e)

        return metadata
