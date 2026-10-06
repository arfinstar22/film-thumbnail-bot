import re
from typing import List, Tuple

class Normalizer:
    @staticmethod
    def clean_filename(raw_name: str) -> Tuple[str, str, List[str]]:
        """
        Returns (original_filename, normalized_string, tokens)
        """
        # Remove extension
        clean = re.sub(r"\.[a-zA-Z0-9]{2,4}$", "", raw_name)
        
        # Only protect actual audio channel decimals: 1.0, 2.0, 5.1, 7.1
        clean = re.sub(r"\b([1257])\.([01])\b", r"\1AUDIOCHDOT\2", clean)
        
        # Replace remaining dots, underscores, brackets, dashes with space
        clean = re.sub(r"[\._\(\)\[\]\-]", " ", clean)
        
        # Restore audio dots
        clean = clean.replace("AUDIOCHDOT", ".")
        
        # Split tokens and strip extra whitespace
        tokens = [t.strip() for t in clean.split() if t.strip()]
        normalized = " ".join(tokens)
        
        return raw_name, normalized, tokens
