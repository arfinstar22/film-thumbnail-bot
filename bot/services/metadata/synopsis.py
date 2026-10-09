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

    def _sync_fetch(self, title: str, year: Optional[int] = None, is_series: bool = False) -> str:
        if not title:
            return ""

        cache_key = f"synopsis_v3_{title.lower()}_{year}_{is_series}" if year else f"synopsis_v3_{title.lower()}_{is_series}"
        cached = self.cache.get_setting(cache_key, "")
        if cached:
            return "" if cached == "none" else cached

        # Build prioritized queries: exact title first!
        queries = [title]
        if is_series:
            queries.append(f"{title} seri televisi")
            queries.append(f"{title} drama")
        else:
            if year:
                queries.append(f"{title} {year} film")
            queries.append(f"{title} film")

        for query in queries:
            try:
                search_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
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

                    # Filter and score candidates
                    candidates = []
                    for r in results:
                        sc = self._score_page(r.get("title", ""), r.get("snippet", ""), title, year, is_series)
                        if sc > 0:
                            candidates.append((sc, r["title"]))

                    if not candidates:
                        continue

                    candidates.sort(key=lambda x: x[0], reverse=True)
                    best_page = candidates[0][1]

                # Strategy 1: Dedicated Section (Sinopsis, Alur cerita, Plot, Premis)
                sec_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
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
                    if any(k in line for k in ["sinopsis", "alur cerita", "alur", "plot", "premis", "ringkasan cerita"]):
                        target_section_idx = s.get("index")
                        break

                if target_section_idx:
                    p_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
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
                            result = self._truncate_smart(clean)
                            self.cache.set_setting(cache_key, result)
                            return result

                # Strategy 2: Smart Lead Extractor (for pages without section headers)
                ext_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
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
                        result = self._truncate_smart(story)
                        self.cache.set_setting(cache_key, result)
                        return result

            except Exception as e:
                logger.debug(f"Wikipedia synopsis fetch error for '{query}': {e}")
                continue

        # Mark as not found to avoid redundant queries
        self.cache.set_setting(cache_key, "none")
        return ""

    async def get_synopsis(self, title: str, year: Optional[int] = None, is_series: bool = False) -> str:
        return await asyncio.to_thread(self._sync_fetch, title, year, is_series)
