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
            "videoCodec": None,
            "audioCodec": None,
            "audioChannels": None,
            "season": None,
            "episode": None,
            "releaseGroup": None,
            "confidence": {},
            "uncertainFields": []
        }

        # 1. Detect technical metadata first to establish boundaries
        meta_token_indices = set()
        
        # Season/Episode
        tv_match = re.search(r"\bS(\d{1,2})E(\d{1,2})\b", norm, re.IGNORECASE)
        if tv_match:
            metadata["season"] = int(tv_match.group(1))
            metadata["episode"] = int(tv_match.group(2))
            metadata["confidence"]["season"] = 1.0
            metadata["confidence"]["episode"] = 1.0
            # Mark tokens corresponding to SxxExx
            for idx, t in enumerate(tokens):
                if re.match(r"^S\d{1,2}E\d{1,2}$", t, re.IGNORECASE):
                    meta_token_indices.add(idx)

        # Tech specs mapping
        tech_specs = [
            ("resolution", self.dict.resolutions),
            ("source", self.dict.sources),
            ("videoCodec", self.dict.video_codecs),
            ("audioCodec", self.dict.audio_codecs),
        ]

        for key, category_dict in tech_specs:
            for idx, t in enumerate(tokens):
                canonical = self.dict.match(t, category_dict)
                if canonical:
                    metadata[key] = canonical
                    metadata["confidence"][key] = 1.0
                    meta_token_indices.add(idx)
                    break # Usually only one per category
                    
        # Special case for combined tokens (e.g., WEB-DL often splits to WEB and DL)
        if not metadata["source"]:
            for idx in range(len(tokens) - 1):
                combined = f"{tokens[idx]}-{tokens[idx+1]}"
                src = self.dict.match(combined, self.dict.sources)
                if src:
                    metadata["source"] = src
                    metadata["confidence"]["source"] = 1.0
                    meta_token_indices.add(idx)
                    meta_token_indices.add(idx+1)
                    break

        # Audio channels
        for idx, t in enumerate(tokens):
            if re.match(r"^[1257]\.[01]$", t):
                metadata["audioChannels"] = t
                metadata["confidence"]["audioChannels"] = 0.95
                meta_token_indices.add(idx)
                break

        # 2. Smarter Year Detection
        year_candidates = []
        for idx, t in enumerate(tokens):
            if re.match(r"^(19\d\d|20\d\d)$", t):
                # Is it the last one before other tech metadata?
                dist_to_other_meta = min([abs(idx - i) for i in meta_token_indices]) if meta_token_indices else 1000
                year_candidates.append((idx, int(t), dist_to_other_meta))

        if year_candidates:
            # Prefer year that is closest to or followed by other metadata
            # Or just the last one that makes sense
            year_candidates.sort(key=lambda x: (x[2], -x[0]))
            best_year_idx, best_year_val, _ = year_candidates[0]
            metadata["year"] = best_year_val
            metadata["confidence"]["year"] = 0.95
            meta_token_indices.add(best_year_idx)
        else:
            best_year_idx = None

        # 3. Title Boundary
        # Boundary is usually the index of the first technical metadata token
        boundary = len(tokens)
        if meta_token_indices:
            # Filter out tokens that are likely part of the title despite looking like metadata
            # e.g., 2049 in Blade Runner 2049 should not be the boundary if there is a 2017 later.
            
            # Real metadata boundary is often the index of the year (if it exists and is followed by specs)
            # OR the first resolution/source/codec
            indices_to_consider = []
            for idx in meta_token_indices:
                # If this is the year, check if it's the release year or part of title
                if idx == best_year_idx:
                    # If this is the only year and it's near the end, it's likely the year
                    indices_to_consider.append(idx)
                else:
                    indices_to_consider.append(idx)
            
            if indices_to_consider:
                boundary = min(indices_to_consider)

        # Detect Release Group (the very last token usually)
        if tokens:
            last_idx = len(tokens) - 1
            if last_idx not in meta_token_indices and last_idx >= boundary:
                if not re.match(r"^(mp4|mkv|avi|sub|indo|eng)$", tokens[last_idx], re.IGNORECASE):
                    metadata["releaseGroup"] = tokens[last_idx]
                    metadata["confidence"]["releaseGroup"] = 0.7
                    meta_token_indices.add(last_idx)

        # Final title extraction
        title_tokens = tokens[:boundary]
        if title_tokens:
            metadata["title"] = " ".join(title_tokens)
            metadata["confidence"]["title"] = 0.95
        else:
            # If everything failed, try a very simple fallback: use original filename
            metadata["confidence"]["title"] = 0.3
            metadata["uncertainFields"].append("title")

        # Confidence Scoring
        scores = list(metadata["confidence"].values())
        metadata["confidence"]["overall"] = sum(scores) / len(scores) if scores else 0.0

        return metadata
