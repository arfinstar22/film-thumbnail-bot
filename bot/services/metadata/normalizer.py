import re
import unicodedata
from typing import List, Tuple

class Normalizer:
    @staticmethod
    def is_homoglyph_or_decorative(word: str) -> bool:
        """Deteksi apakah kata mengandung karakter dekoratif/homoglif campuran (misal: fαιвεяsgαтє)."""
        if len(word) < 3:
            return False
        scripts = set()
        for ch in word:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                if "GREEK" in name:
                    scripts.add("GREEK")
                elif "CYRILLIC" in name:
                    scripts.add("CYRILLIC")
                elif "LATIN" in name:
                    scripts.add("LATIN")
                elif "MATHEMATICAL" in name:
                    scripts.add("MATH")
                else:
                    scripts.add("OTHER")
        # Campuran Greek/Cyrillic dengan Latin adalah watermark uploader gaya font khusus
        if ("GREEK" in scripts or "CYRILLIC" in scripts or "MATH" in scripts) and ("LATIN" in scripts or len(word) >= 4):
            return True
        return False

    @staticmethod
    def clean_filename(raw_name: str) -> Tuple[str, str, List[str]]:
        """
        Membersihkan nama file dari ekstensi, emoji, watermark uploader/channel,
        dan memformat audio channels/codecs dengan benar.
        Returns: (original, normalized_string, tokens)
        """
        # 1. Hapus ekstensi file media
        clean = re.sub(r"\.(mp4|mkv|avi|mov|flv|wmv|webm|ts|m4v|3gp|vob|mpg|mpeg)$", "", raw_name, flags=re.IGNORECASE)


        # 2. Hapus emoji & simbol khusus
        clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff]", "", clean)

        # 3. Hapus uploader prefix: URL, channel handles, domain watermarks, brackets
        clean = re.sub(r"^(?:https?://\S+|www\.\S+|(?:t\.me|telegram\.me)/\S+)[\.\s\-_]*", "", clean)
        clean = re.sub(r"^(?:[a-zA-Z0-9_\-]+\.)+(?:com|net|org|io|me|tv|co|id|ru|xyz|to|is|site|top|cc|ws|vip)\b[\.\s\-_]*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^@[a-zA-Z0-9_]+[\.\s\-]+", "", clean)
        clean = re.sub(r"^\[[^\]]+\][\.\s\-_]*", "", clean)
        clean = re.sub(r"^\([^\)]*(?:telegram|channel|upload|link|t\.me)\b[^\)]*\)[\.\s\-_]*", "", clean, flags=re.IGNORECASE)

        # 4. Deteksi kata pertama jika itu watermark homoglif atau nama channel umum
        m = re.match(r"^([^\.\s\-_]+)[\.\s\-_]+(.*)$", clean)
        if m:
            first_token, rest = m.group(1), m.group(2)
            known_uploaders = {
                "sitikus", "fibersgate", "melongfilm", "pahe", "yts", "psa",
                "dramaindo", "layarkaca21", "lk21", "indoxxi", "dunia21", "kuy"
            }
            if Normalizer.is_homoglyph_or_decorative(first_token) or first_token.lower() in known_uploaders:
                clean = rest

        # 5. Pisahkan audio dan channel: AAC2.0 -> AAC 2.0, DDP5.1 -> DDP 5.1
        clean = re.sub(r"(?i)\b(AAC|AC3|EAC3|DDP|DD|DTS|FLAC|MP3)[\.\-_]?([1257]\.[01])\b", r"\1 \2", clean)

        # 6. Rapikan video codecs dengan titik: H.264 -> H264, x.264 -> x264
        clean = re.sub(r"(?i)\b([HhXx])\.(26[45])\b", r"\1\2", clean)

        # 7. Rapikan WEB.DL -> WEB-DL, WEB.Rip -> WEBRip
        clean = re.sub(r"(?i)\bWEB[\.\s_]DL\b", "WEB-DL", clean)
        clean = re.sub(r"(?i)\bWEB[\.\s_]Rip\b", "WEBRip", clean)

        # 8. Lindungi titik desimal audio: 2.0 -> 2AUDIOCHDOT0
        clean = re.sub(r"\b([1257])\.([01])\b", r"\1AUDIOCHDOT\2", clean)

        # 9. Ganti pemisah titik, underscore, kurung dengan spasi
        clean = re.sub(r"[\._\(\)\[\]\-]", " ", clean)

        # 10. Kembalikan titik desimal audio
        clean = clean.replace("AUDIOCHDOT", ".")

        tokens = [t.strip() for t in clean.split() if t.strip()]
        normalized = " ".join(tokens)

        return raw_name, normalized, tokens
