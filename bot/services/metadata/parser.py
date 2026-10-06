import re
from typing import Dict, Any, Optional, List
from .dictionary import MetadataDictionary
from .normalizer import Normalizer

class FilenameParser:
    def __init__(self, dictionary: Optional[MetadataDictionary] = None):
        self.dict = dictionary or MetadataDictionary()

    def parse(self, filename: str) -> Dict[str, Any]:
        orig, norm, tokens = Normalizer.clean_filename(filename)

        metadata: Dict[str, Any] = {
            "originalFilename": orig,
            "title": None,
            "year": None,
            "resolution": None,
            "source": None,
            "platform": None,
            "videoCodec": None,
            "audioCodec": None,
            "audioChannels": None,
            "season": None,
            "episode": None,
            "releaseGroup": None,
            "confidence": {},
            "uncertainFields": []
        }

        meta_token_indices = set()

        # 1. Season & Episode (e.g., S01E02)
        tv_match = re.search(r"\bS(\d{1,2})E(\d{1,2})\b", norm, re.IGNORECASE)
        if tv_match:
            metadata["season"] = int(tv_match.group(1))
            metadata["episode"] = int(tv_match.group(2))
            metadata["confidence"]["season"] = 1.0
            metadata["confidence"]["episode"] = 1.0
            for idx, t in enumerate(tokens):
                if re.match(r"^S\d{1,2}E\d{1,2}$", t, re.IGNORECASE):
                    meta_token_indices.add(idx)

        # 2. Tech specs mapping: platform, resolution, source, videoCodec, audioCodec
        tech_specs = [
            ("platform", getattr(self.dict, "platforms", {})),
            ("resolution", self.dict.resolutions),
            ("source", self.dict.sources),
            ("videoCodec", self.dict.video_codecs),
            ("audioCodec", self.dict.audio_codecs),
        ]

        for key, category_dict in tech_specs:
            for idx, t in enumerate(tokens):
                canonical = self.dict.match(t, category_dict)
                if canonical and (key not in metadata or not metadata.get(key)):
                    metadata[key] = canonical
                    metadata["confidence"][key] = 1.0
                    meta_token_indices.add(idx)
                    break

        # Check combined source tokens (e.g., WEB and DL -> WEB-DL)
        if not metadata["source"]:
            for idx in range(len(tokens) - 1):
                combined = f"{tokens[idx]}-{tokens[idx+1]}"
                src = self.dict.match(combined, self.dict.sources)
                if src:
                    metadata["source"] = src
                    metadata["confidence"]["source"] = 1.0
                    meta_token_indices.add(idx)
                    meta_token_indices.add(idx + 1)
                    break

        # 3. Audio Channels (1.0, 2.0, 5.1, 7.1)
        for idx, t in enumerate(tokens):
            if re.match(r"^[1257]\.[01]$", t):
                metadata["audioChannels"] = t
                metadata["confidence"]["audioChannels"] = 0.95
                meta_token_indices.add(idx)
                break

        # 4. Release Year Detection (1900 - 2099)
        year_candidates = []
        for idx, t in enumerate(tokens):
            if re.match(r"^(19\d\d|20\d\d)$", t):
                # Calculate distance to nearest technical metadata
                dist = min([abs(idx - i) for i in meta_token_indices]) if meta_token_indices else 1000
                year_candidates.append((idx, int(t), dist))

        best_year_idx = None
        if year_candidates:
            # Sort by distance to tech specs, then latest token index
            year_candidates.sort(key=lambda x: (x[2], -x[0]))
            best_year_idx = year_candidates[0][0]
            metadata["year"] = year_candidates[0][1]
            metadata["confidence"]["year"] = 0.95
            meta_token_indices.add(best_year_idx)

        # 5. Title Boundary
        boundary = len(tokens)
        if meta_token_indices:
            if best_year_idx is not None:
                boundary = best_year_idx
            else:
                boundary = min(meta_token_indices)

        # Extract title tokens
        title_tokens = tokens[:boundary]
        if title_tokens:
            cleaned_words = []
            for w in title_tokens:
                # Capitalize words if all-caps or all-lower, otherwise keep styling (e.g. McDonald)
                if w.islower() or w.isupper():
                    cleaned_words.append(w.capitalize())
                else:
                    cleaned_words.append(w)
            metadata["title"] = " ".join(cleaned_words)
            metadata["confidence"]["title"] = 0.95
        else:
            metadata["title"] = orig
            metadata["confidence"]["title"] = 0.3
            metadata["uncertainFields"].append("title")

        # 6. Release Group (tokens after boundary not in meta_token_indices)
        trailing_indices = [
            i for i in range(boundary, len(tokens))
            if i not in meta_token_indices
        ]
        if trailing_indices:
            trailing_tokens = [
                tokens[i] for i in trailing_indices
                if not re.match(r"^(mp4|mkv|avi|sub|indo|eng|indonesia)$", tokens[i], re.IGNORECASE)
            ]
            if trailing_tokens:
                # If short chunks like ['0n', '3'], join without space
                if all(len(x) <= 2 for x in trailing_tokens):
                    metadata["releaseGroup"] = "".join(trailing_tokens)
                else:
                    metadata["releaseGroup"] = " ".join(trailing_tokens)
                metadata["confidence"]["releaseGroup"] = 0.85

        # 7. Confidence Scoring
        scores = list(metadata["confidence"].values())
        metadata["confidence"]["overall"] = sum(scores) / len(scores) if scores else 0.0

        return metadata
