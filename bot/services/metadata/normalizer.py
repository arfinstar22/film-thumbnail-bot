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

    KNOWN_PIRATE_SITES = {
        "idlix", "idlix21", "lk21", "layarkaca21", "layarkaca", "indoxxi", "dunia21",
        "ngefilm", "ngefilm21", "rebahin", "rebahin21", "kawanfilm", "kawanfilm21",
        "melongfilm", "melong", "ganool", "ganool21", "juraganfilm", "juraganfilm21",
        "pusatfilm", "pusatfilm21", "filmapik", "filmapik21", "sobatkeren", "sobatkeren21",
        "bioskopkeren", "bioskopkeren21", "dutafilm", "dutafilm21", "cinema21", "cinemaindo",
        "cinemakeren", "nontonmovie", "nontonmovie21", "nontongo", "nontondrama",
        "dramaindo", "drakorindo", "gudangfilm", "gudangfilm21", "indofilm", "indofilm21",
        "sukafilm", "sukafilm21", "muvihd", "muvihd21", "terbit21", "terbitfilm",
        "kuyhaa", "bagas31", "sharer", "fembed", "streamtape", "gdriveplayer",
        "sitikus", "sitikusrobot", "fibersgate", "blurayindo", "subscene",
        "pahe", "pahe.in", "pahe.li", "yts", "yify", "psa", "galaxyrg", "rarbg",
        "1337x", "eztv", "torrentgalaxy", "tgx", "extratorrent", "1tamilmv",
        "tamilrockers", "bolly4u", "katmoviehd", "worldfree4u", "mkvcage", "mkvking",
        "cinevood", "vega", "vegamovies", "luxmovies", "hubdrive", "hubcloud"
    }

    PROMO_NOISE_TOKENS = {
        "pw", "vip", "official", "org", "net", "com", "id", "site", "hd", "pro",
        "admin", "channel", "bot", "robot", "web", "ori", "asli", "baru", "cx",
        "top", "fun", "club", "live", "preview"
    }

    UNAMBIGUOUS_TLD = (
        r"(?:my\.id|co\.id|web\.id|net\.id|org\.id|co\.uk|com\.br|com\.mx|"
        r"com|net|org|xyz|site|top|vip|pw|cx|club|fun|live|online|life|icu|"
        r"link|lat|pro|asia|biz|world|app|space|fit|click|monster|cfd|rest|"
        r"lol|zone|art|tech|media|info|mobi|cc|ws|tv|official)"
    )

    ALL_TLD = (
        r"(?:my\.id|co\.id|web\.id|net\.id|org\.id|co\.uk|com\.br|com\.mx|"
        r"com|net|org|xyz|site|top|vip|pw|cx|club|fun|live|online|life|icu|"
        r"link|lat|pro|asia|biz|world|app|space|fit|click|monster|cfd|rest|"
        r"lol|zone|art|tech|media|info|mobi|cc|ws|tv|in|is|to|me|so|it|at|my|do|be|no|mx|li|lt|ag|re)"
    )

    @classmethod
    def is_pirate_brand(cls, word: str) -> bool:
        """Deteksi apakah sebuah kata adalah brand/nama situs bajakan atau uploader watermark."""
        if not word:
            return False
        w = word.lower()
        if w in cls.KNOWN_PIRATE_SITES:
            return True
        # Deteksi pola brand *21 (misal: idlix21, ngefilm21, lk21, dunia21, rebahin21)
        if re.match(r"^[a-zA-Z]{2,}21$", w) and len(w) >= 4:
            return True
        # Deteksi kata majemuk dengan kata kunci streaming bajakan
        if len(w) > 6 and any(k in w for k in ("film", "movie", "cinema", "nonton", "bioskop", "drakor", "layarkaca")):
            return True
        return False

    @classmethod
    def strip_uploader_prefixes(cls, clean: str) -> str:
        """
        Membersihkan semua variasi watermark website, uploader, domain, dan bracket
        secara berulang (iteratif) hingga judul asli film ditemukan.
        """
        for _ in range(6):
            prev = clean

            # 1. URLs, t.me, telegram links
            clean = re.sub(r"^(?:https?://\S+|www\.\S+|(?:t\.me|telegram\.me)/\S+)[\.\s\-_]*", "", clean, flags=re.IGNORECASE)

            # 2. Bracket, kurung, atau delimiter uploader di awal (kecuali tahun 4-digit murni)
            clean = re.sub(r"^[\[\(\{【『「《](?!\s*\d{4}\s*[\]\)\}】』」》])[^\]\)\}】』」》]+[\]\)\}】』」》][\.\s\-_]*", "", clean)

            # 3. Handle @channel di awal
            clean = re.sub(r"^@[a-zA-Z0-9_]+[\.\s\-_]+", "", clean)

            # 4. Domain internet dengan TLD jelas (misal: NGEFILM21.PW., MELONGFILM.SITE_, IDLIX.VIP.)
            clean = re.sub(rf"^(?:www\.)?[a-zA-Z0-9\-]{{2,30}}\.(?:{cls.UNAMBIGUOUS_TLD})(?:[\.\s\-_]+|$)", "", clean, flags=re.IGNORECASE)

            # 5. Domain dengan brand bajakan + sembarang TLD (misal: Pahe.in-, YTS.MX-, Ganool.is-, KawanFilm21.me.)
            dm = re.match(rf"^([a-zA-Z0-9_\-]+)\.(?:{cls.ALL_TLD})(?:[\.\s\-_]+|$)", clean, flags=re.IGNORECASE)
            if dm and cls.is_pirate_brand(dm.group(1)):
                clean = clean[dm.end():]

            # 6. Deteksi kata pertama jika nama website bajakan, noise promo, atau dekoratif
            m = re.match(r"^([^\.\s\-_]+)[\.\s\-_]+(.*)$", clean)
            if m:
                first, rest = m.group(1), m.group(2)
                f_low = first.lower()
                if (
                    cls.is_pirate_brand(first)
                    or f_low in cls.PROMO_NOISE_TOKENS
                    or cls.is_homoglyph_or_decorative(first)
                ):
                    clean = rest

            # 7. Bersihkan pemisah sisa di awal teks
            clean = re.sub(r"^[\.\s\-_]+", "", clean)

            if clean == prev:
                break

        return clean

    @staticmethod
    def clean_filename(raw_name: str) -> Tuple[str, str, List[str]]:
        """
        Membersihkan nama file dari ekstensi, emoji, watermark uploader/channel/website,
        dan memformat audio channels/codecs dengan benar.
        Returns: (original, normalized_string, tokens)
        """
        # 1. Hapus ekstensi file media
        clean = re.sub(r"\.(mp4|mkv|avi|mov|flv|wmv|webm|ts|m4v|3gp|vob|mpg|mpeg)$", "", raw_name, flags=re.IGNORECASE)

        # 2. Hapus emoji & simbol khusus
        clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff]", "", clean)

        # 3. Bersihkan semua watermark website & uploader secara pintar
        clean = Normalizer.strip_uploader_prefixes(clean)

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
