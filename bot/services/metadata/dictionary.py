import json
import os
from typing import Dict, List, Optional, Tuple

class MetadataDictionary:
    def __init__(self, dict_dir: Optional[str] = None):
        if not dict_dir:
            dict_dir = os.path.join(os.path.dirname(__file__), "dictionaries")
        self.dict_dir = dict_dir
        self.resolutions = self._load("resolutions.json")
        self.sources = self._load("sources.json")
        self.video_codecs = self._load("video_codecs.json")
        self.audio_codecs = self._load("audio_codecs.json")
        self.platforms = self._load("platforms.json")


    def _load(self, filename: str) -> Dict[str, List[str]]:
        path = os.path.join(self.dict_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def match(self, token: str, category_dict: Dict[str, List[str]]) -> Optional[str]:
        token_lower = token.lower()
        for canonical, aliases in category_dict.items():
            for alias in aliases:
                if token_lower == alias.lower():
                    return canonical
        return None
