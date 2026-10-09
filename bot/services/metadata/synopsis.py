import asyncio
import html
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from .cache import MetadataCache

logger = logging.getLogger(__name__)


def translate_to_indonesian(text: str) -> str:
    """Translates text to Indonesian using Google Translate public endpoint with fallback."""
    if not text or not text.strip():
        return ""
    clean_text = text.strip()
    try:
        url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
            "client": "gtx",
            "sl": "auto",
            "tl": "id",
            "dt": "t",
            "q": clean_text
        })
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                translated_parts = [segment[0] for segment in data[0] if segment and len(segment) > 0 and segment[0]]
                translated = "".join(translated_parts).strip()
                if translated:
                    return translated
    except Exception as e:
        logger.debug(f"Translation error: {e}")
    return clean_text


def generate_smart_fallback(title: str, year: Optional[int] = None, genre: Optional[str] = None) -> str:
    """Generates engaging, context-aware Indonesian teaser synopsis based on genre and year."""
    y_str = f" rilisan tahun {year}" if year else ""
    g_lower = (genre or "").lower()
    if "horor" in g_lower or "horror" in g_lower:
        return f"Film horor misterius{y_str}. Mengisahkan teror mencekam dan ancaman tak terduga yang menguji keberanian serta batas ketakutan terdalam para karakternya."
    elif "aksi" in g_lower or "action" in g_lower:
        return f"Film aksi mendebarkan{y_str}. Menyajikan rangkaian pertempuran sengit dan misi berbahaya penuh adrenalin yang memacu ketegangan dari awal hingga akhir."
    elif "animasi" in g_lower or "animation" in g_lower:
        return f"Petualangan animasi memukau{y_str}. Membawa penonton menyelami dunia imajinatif penuh warna, kehangatan persahabatan, dan pesan inspiratif mendalam."
    elif "komedi" in g_lower or "comedy" in g_lower:
        return f"Film komedi menghibur{y_str}. Menghadirkan rentetan peristiwa kocak, kesalahpahaman tak terduga, dan gelak tawa yang menyegarkan suasana."
    elif "romantis" in g_lower or "romance" in g_lower:
        return f"Kisah drama romantis menyentuh hati{y_str}. Mengikuti dinamika hubungan dan perjalanan cinta penuh liku yang menggetarkan perasaan."
    elif "sci-fi" in g_lower or "fantasi" in g_lower or "fantasy" in g_lower:
        return f"Kisah fiksi ilmiah dan fantasi spektakuler{y_str}. Menjelajahi misteri di luar nalar dan tantangan luar biasa yang melampaui batas realitas."
    elif "thriller" in g_lower or "misteri" in g_lower or "mystery" in g_lower:
        return f"Film thriller penuh teka-teki{y_str}. Menyuguhkan plot misterius dan ketegangan psikologis yang memikat penonton untuk mengungkap rahasia kelam di baliknya."
    elif "drama" in g_lower:
        return f"Karya drama emosional mendalam{y_str}. Mengangkat kisah kehidupan penuh pergulatan batin, konflik moral, dan pencarian jati diri yang sarat makna."
    elif genre:
        return f"Film bergenre {genre}{y_str}. Menyajikan alur cerita menarik dan dinamika konflik memikat yang layak untuk disaksikan bersama."
    else:
        return f"Sebuah tayangan film menarik{y_str} dengan alur cerita memikat dan dinamika sinematik yang patut dinikmati."


class WikipediaSynopsisService:
    """Smart Zero-AI Synopsis Extractor for Movies and TV Series.
    Extracts authentic story plots and avoids encyclopedic fluff or actor biographies."""

    def __init__(self, cache: Optional[MetadataCache] = None):
        self.cache = cache or MetadataCache()
        self.headers = {
            "User-Agent": "FilmIndonesiaBot/2.0 (https://t.me/film_indonesia1; bot_dev@gmail.com)"
        }

    def _remove_wiki_files(self, text: str) -> str:
        """Remove nested [[Berkas:...]] and [[File:...]] blocks safely."""
        while True:
            match = re.search(r"\[\[(?:Berkas|File|Gambar):", text, re.IGNORECASE)
            if not match:
                break
            start = match.start()
            depth = 0
            end = -1
            i = start
            while i < len(text) - 1:
                if text[i:i+2] == "[[":
                    depth += 1
                    i += 2
                elif text[i:i+2] == "]]":
                    depth -= 1
                    i += 2
                    if depth == 0:
                        end = i
                        break
                else:
                    i += 1
            if end != -1:
                text = text[:start] + text[end:]
            else:
                break
        return text

    def _clean_wikitext(self, text: str) -> str:
        if not text:
            return ""
        # 1. Remove nested media blocks
        text = self._remove_wiki_files(text)
        # 2. Remove leftover thumbnail flags
        text = re.sub(r"(?:jmpl|thumb|miniatur)\|[^\]]*\]\]", "", text, flags=re.IGNORECASE)
        # 3. Remove section headers == Header ==
        text = re.sub(r"==+[^=]+==+", "", text)
        # 4. Remove reference tags
        text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
        text = re.sub(r"<ref[^>]*/>", "", text)
        # 5. Remove templates {{...}} (including nested)
        while "{{" in text and "}}" in text:
            new_text = re.sub(r"\{\{[^{}]*\}\}", "", text)
            if new_text == text:
                break
            text = new_text
        # 6. Resolve internal links [[Target|Anchor]] -> Anchor, [[Target]] -> Target
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # 7. Remove footnote markers [1], [catatan 1]
        text = re.sub(r"\[\s*(?:\d+|catatan\s*\d+)\s*\]", "", text)
        # 8. Remove formatting
        text = re.sub(r"\'\'\'?", "", text)
        # 9. Strip any stray HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # 10. Unescape HTML entities
        text = html.unescape(text)
        # 11. Normalize spaces
        return re.sub(r"\s+", " ", text).strip()

    def _is_biography(self, text: str) -> bool:
        """Reject pages that are human biographies rather than media plots."""
        bio_patterns = [
            r"\badalah\s+(?:seorang\s+)?(?:aktris|aktor|pemeran|sutradara|produser|penyanyi|musisi|model|politikus|atlet)\b",
            r"\blahir\s+\d+\s+(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember|\w+)\s+\d{4}\b",
            r"\(Hangul:\s*[^,)]+,\s*lahir\b",
            r"\bmemulai\s+kariernya\s+sebagai\b",
            r"\bkelahiran\s+\d+\s+\w+\s+\d{4}\b",
        ]
        for p in bio_patterns:
            if re.search(p, text, re.IGNORECASE):
                return True
        return False

    def _extract_storyline_from_lead(self, lead_text: str) -> str:
        """Extract genuine plot sentences from lead paragraphs, dropping encyclopedic fluff."""
        if not lead_text:
            return ""
        if self._is_biography(lead_text):
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", lead_text)
        story_sentences = []

        metadata_patterns = [
            r"\badalah\s+(?:sebuah\s+)?(?:film|seri\s+televisi|serial\s+televisi|drama|anime)\b",
            r"\bdisutradarai\s+oleh\b",
            r"\bditulis\s+oleh\b",
            r"\bmerilisnya\s+pada\b",
            r"\btayang\s+perdana\b",
            r"\bdirilis\s+pada\b",
            r"\bmeraih\s+(?:jumlah\s+)?nominasi\b",
            r"\bberdasarkan\s+siniar\b",
            r"\bsekuel\s+dari\b",
            r"\bfestival\s+film\b",
            r"\btayang\s+secara\s+global\b",
            r"\bpenayangan\b",
            r"\bjuga\s+tersedia\s+untuk\s+penonton\b",
        ]

        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue

            is_pure_metadata = False
            for p in metadata_patterns:
                if re.search(p, s_clean, re.IGNORECASE):
                    # Exception: if it introduces the protagonist / conflict
                    if re.search(r"sebagai\s+[^,]+,\s*(?:seorang|yang|pembunuh|detektif|anak|gadis|pria|wanita|sosok|pengacara)", s_clean, re.IGNORECASE):
                        continue
                    is_pure_metadata = True
                    break

            if not is_pure_metadata:
                story_sentences.append(s_clean)

        res = " ".join(story_sentences)
        # Polish opening syntax if actor intro was retained
        res = re.sub(r"^Film ini (?:sendiri )?dibintangi [^,]+ sebagai ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Seri ini (?:sendiri )?dibintangi [^,]+ sebagai ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Film ini menceritakan ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Seri ini menceritakan ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Film ini mengisahkan ", "Mengisahkan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Seri ini mengisahkan ", "Mengisahkan ", res, flags=re.IGNORECASE)
        return res

    def _score_page(self, page_title: str, snippet: str, target_title: str, target_year: Optional[int], is_series: bool) -> int:
        """Score candidate Wikipedia pages to avoid picking sequels, actors, or wrong items."""
        t_lower = target_title.lower().strip()
        p_lower = page_title.lower().strip()
        clean_p = re.sub(r"\s*\([^)]*\)", "", p_lower).strip()

        stop_words = {"the", "a", "an", "di", "ke", "dan", "of", "in", "on", "for"}
        t_words = [w for w in re.findall(r"\w+", t_lower) if w not in stop_words]
        p_words = set(re.findall(r"\w+", clean_p))

        if not t_words:
            return 0

        overlap = sum(1 for w in t_words if w in p_words)
        overlap_ratio = overlap / len(t_words)

        # REJECT if word overlap is too weak (e.g. Park Eun-bin for Extraordinary Attorney Woo)
        if overlap_ratio < 0.5 and clean_p != t_lower:
            return -9999

        score = int(overlap_ratio * 60)

        # Exact title match gets massive boost
        if clean_p == t_lower:
            score += 50
        elif t_lower in p_lower:
            score += 30

        snip_lower = snippet.lower()
        if is_series:
            if any(k in p_lower for k in ["seri televisi", "drama", "serial", "series", "anime"]):
                score += 25
            if any(k in snip_lower for k in ["seri televisi", "drama", "serial", "series"]):
                score += 15
        else:
            if any(k in p_lower for k in ["film", "(film"]):
                score += 25
            if "film" in snip_lower:
                score += 10

        # Penalize biographical articles
        if any(k in snip_lower for k in ["aktris", "aktor", "pemeran", "kelahiran", "model anak"]):
            score -= 50

        if target_year:
            str_year = str(target_year)
            if str_year in p_lower:
                score += 20
            elif str_year in snip_lower:
                score += 10
            other_years = re.findall(r"\b(19\d{2}|20\d{2})\b", p_lower)
            if other_years and str_year not in other_years:
                score -= 30

        return score

    def _truncate_smart(self, text: str, max_chars: int = 300) -> str:
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_chars:
            return text

        # 1. Check if a period exists slightly ahead (up to +45 chars) to finish current sentence cleanly
        extended = text[:max_chars + 45]
        ext_dot = extended.rfind(".")
        if ext_dot >= max_chars - 30:
            return extended[:ext_dot + 1].strip()

        # 2. Check if a period exists within max_chars
        cutoff = text[:max_chars].rfind(".")
        if cutoff > 80:
            return text[:cutoff + 1].strip()

        # 3. Clean word boundary fallback with ellipsis
        last_space = text[:max_chars].rfind(" ")
        if last_space > 50:
            return text[:last_space].rstrip(",;:- ") + "..."

        return text[:max_chars].rstrip() + "..."

    def _fetch_from_wikipedia(self, lang: str, title: str, year: Optional[int] = None, is_series: bool = False) -> str:
        base_url = f"https://{lang}.wikipedia.org/w/api.php?"
        queries = []
        if lang == "id":
            queries.append(title)
            if is_series:
                queries.append(f"{title} seri televisi")
                queries.append(f"{title} drama")
            else:
                if year:
                    queries.append(f"{title} {year} film")
                queries.append(f"{title} film")
            sec_keywords = ["sinopsis", "alur cerita", "alur", "plot", "premis", "ringkasan cerita"]
        else:
            if year:
                queries.append(f"{title} ({year} film)")
                queries.append(f"{title} {year} film")
            queries.append(f"{title} (film)")
            queries.append(f"{title} film")
            queries.append(title)
            sec_keywords = ["plot", "synopsis", "premise", "storyline", "overview", "summary"]

        for query in queries:
            try:
                search_url = base_url + urllib.parse.urlencode({
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 4
                })
                req = urllib.request.Request(search_url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("query", {}).get("search", [])
                    if not results:
                        continue

                    candidates = []
                    for r in results:
                        sc = self._score_page(r.get("title", ""), r.get("snippet", ""), title, year, is_series)
                        if sc > 0:
                            candidates.append((sc, r["title"]))

                    if not candidates:
                        continue

                    candidates.sort(key=lambda x: x[0], reverse=True)
                    best_page = candidates[0][1]

                # Strategy 1: Dedicated Section
                sec_url = base_url + urllib.parse.urlencode({
                    "action": "parse",
                    "page": best_page,
                    "prop": "sections",
                    "format": "json"
                })
                req_sec = urllib.request.Request(sec_url, headers=self.headers)
                with urllib.request.urlopen(req_sec, timeout=2.5) as resp_sec:
                    sec_data = json.loads(resp_sec.read().decode("utf-8"))
                    secs = sec_data.get("parse", {}).get("sections", [])

                target_section_idx = None
                for s in secs:
                    line = s.get("line", "").lower()
                    if any(k in line for k in sec_keywords):
                        target_section_idx = s.get("index")
                        break

                if target_section_idx:
                    p_url = base_url + urllib.parse.urlencode({
                        "action": "parse",
                        "page": best_page,
                        "prop": "wikitext",
                        "section": target_section_idx,
                        "format": "json"
                    })
                    req_p = urllib.request.Request(p_url, headers=self.headers)
                    with urllib.request.urlopen(req_p, timeout=2.5) as resp_p:
                        p_data = json.loads(resp_p.read().decode("utf-8"))
                        wt = p_data.get("parse", {}).get("wikitext", {}).get("*", "")
                        clean = self._clean_wikitext(wt)
                        if clean and len(clean) > 35 and not self._is_biography(clean):
                            if lang == "en":
                                clean = translate_to_indonesian(clean)
                            return self._truncate_smart(clean)

                # Strategy 2: Lead Extractor
                ext_url = base_url + urllib.parse.urlencode({
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": "1",
                    "titles": best_page,
                    "format": "json"
                })
                req_ext = urllib.request.Request(ext_url, headers=self.headers)
                with urllib.request.urlopen(req_ext, timeout=2.5) as resp_ext:
                    ext_data = json.loads(resp_ext.read().decode("utf-8"))
                    pages = ext_data.get("query", {}).get("pages", {})
                    raw_ext = ""
                    for p in pages.values():
                        raw_ext = p.get("extract", "")
                        break
                    lead = raw_ext.split("==")[0].strip()
                    story = self._extract_storyline_from_lead(lead)
                    if story and len(story) > 35 and not self._is_biography(story):
                        if lang == "en":
                            story = translate_to_indonesian(story)
                        return self._truncate_smart(story)

            except Exception as e:
                logger.debug(f"Wikipedia ({lang}) synopsis fetch error for '{query}': {e}")
                continue

        return ""

    def _sync_fetch(self, title: str, year: Optional[int] = None, is_series: bool = False, genre: Optional[str] = None) -> str:
        if not title:
            return ""

        cache_key = f"synopsis_v4_{title.lower()}_{year}_{is_series}" if year else f"synopsis_v4_{title.lower()}_{is_series}"
        cached = self.cache.get_setting(cache_key, "")
        if cached:
            return "" if cached == "none" else cached

        # Tier 1: Indonesian Wikipedia
        syn = self._fetch_from_wikipedia("id", title, year, is_series)
        if syn:
            self.cache.set_setting(cache_key, syn)
            return syn

        # Tier 2: English Wikipedia (Auto-translated to Indonesian)
        syn = self._fetch_from_wikipedia("en", title, year, is_series)
        if syn:
            self.cache.set_setting(cache_key, syn)
            return syn

        # Tier 3: OMDb API Plot (Auto-translated to Indonesian)
        try:
            omdb_url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey=trilogy"
            if year:
                omdb_url += f"&y={year}"
            req_omdb = urllib.request.Request(omdb_url, headers=self.headers)
            with urllib.request.urlopen(req_omdb, timeout=2.5) as resp_omdb:
                o_data = json.loads(resp_omdb.read().decode("utf-8"))
                if o_data.get("Response") == "True" and o_data.get("Plot") and o_data["Plot"] != "N/A":
                    raw_plot = o_data["Plot"]
                    translated_plot = translate_to_indonesian(raw_plot)
                    if translated_plot:
                        syn = self._truncate_smart(translated_plot)
                        self.cache.set_setting(cache_key, syn)
                        return syn
        except Exception as e:
            logger.debug(f"OMDb plot fetch error for '{title}': {e}")

        # Tier 4: Smart Contextual Fallback (Never leave caption empty)
        fallback = generate_smart_fallback(title, year, genre)
        self.cache.set_setting(cache_key, fallback)
        return fallback

    def translate_if_needed(self, text: str) -> str:
        """Translates text to Indonesian if it is in English."""
        return translate_to_indonesian(text)

    def get_fallback_synopsis(self, title: str, year: Optional[int] = None, genre: Optional[str] = None) -> str:
        """Generates smart contextual fallback synopsis."""
        return generate_smart_fallback(title, year, genre)

    async def get_synopsis(self, title: str, year: Optional[int] = None, is_series: bool = False, genre: Optional[str] = None) -> str:
        return await asyncio.to_thread(self._sync_fetch, title, year, is_series, genre)
