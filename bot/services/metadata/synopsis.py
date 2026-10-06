import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from .cache import MetadataCache

logger = logging.getLogger(__name__)


class WikipediaSynopsisService:
    """Smart Zero-AI Indonesian Film Synopsis Extractor.
    Extracts authentic story plots without encyclopedic boilerplate or paid AI API keys."""

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
        # 5. Remove templates {{...}}
        text = re.sub(r"\{\{[^}]*\}\}", "", text)
        # 6. Resolve internal links [[Target|Anchor]] -> Anchor, [[Target]] -> Target
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # 7. Remove footnote markers [1], [catatan 1]
        text = re.sub(r"\[\s*(?:\d+|catatan\s*\d+)\s*\]", "", text)
        # 8. Remove formatting
        text = re.sub(r"\'\'\'?", "", text)
        # 9. Strip any stray HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # 10. Normalize spaces
        return re.sub(r"\s+", " ", text).strip()

    def _extract_storyline_from_lead(self, lead_text: str) -> str:
        """Extract genuine plot sentences from lead paragraphs, dropping encyclopedic fluff."""
        if not lead_text:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", lead_text)
        story_sentences = []

        metadata_patterns = [
            r"\badalah\s+(?:sebuah\s+)?film\b",
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
        ]

        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue

            is_pure_metadata = False
            for p in metadata_patterns:
                if re.search(p, s_clean, re.IGNORECASE):
                    # Exception: if it introduces the protagonist / conflict
                    if re.search(r"sebagai\s+[^,]+,\s*(?:seorang|yang|pembunuh|detektif|anak|gadis|pria|wanita|sosok)", s_clean, re.IGNORECASE):
                        continue
                    is_pure_metadata = True
                    break

            if not is_pure_metadata:
                story_sentences.append(s_clean)

        res = " ".join(story_sentences)
        # Polish opening syntax if actor intro was retained
        res = re.sub(r"^Film ini (?:sendiri )?dibintangi [^,]+ sebagai ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Film ini menceritakan ", "Menceritakan ", res, flags=re.IGNORECASE)
        res = re.sub(r"^Film ini mengisahkan ", "Mengisahkan ", res, flags=re.IGNORECASE)
        return res

    def _score_page(self, page_title: str, snippet: str, target_title: str, target_year: Optional[int]) -> int:
        """Score candidate Wikipedia pages to avoid picking sequels or wrong films."""
        score = 0
        t_lower = target_title.lower()
        p_lower = page_title.lower()
        snip_lower = snippet.lower()

        clean_p = re.sub(r"\s*\([^)]*\)", "", p_lower).strip()
        if clean_p == t_lower:
            score += 50
        elif t_lower in p_lower:
            score += 30

        t_words = set(re.findall(r"\w+", t_lower))
        p_words = set(re.findall(r"\w+", p_lower))
        overlap = len(t_words & p_words)
        score += overlap * 10

        if "(film" in p_lower or "film" in p_lower:
            score += 15
        if "film" in snip_lower:
            score += 5

        if target_year:
            str_year = str(target_year)
            if str_year in p_lower:
                score += 20
            elif str_year in snip_lower:
                score += 10
            other_years = re.findall(r"\b(19\d{2}|20\d{2})\b", p_lower)
            if other_years and str_year not in other_years:
                score -= 25

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

    def _sync_fetch(self, title: str, year: Optional[int] = None) -> str:
        if not title:
            return ""

        cache_key = f"synopsis_v2_{title.lower()}_{year}" if year else f"synopsis_v2_{title.lower()}"
        cached = self.cache.get_setting(cache_key, "")
        if cached:
            return "" if cached == "none" else cached

        queries = []
        if year:
            queries.append(f"{title} {year} film")
        queries.append(f"{title} film")
        queries.append(title)

        for query in queries:
            try:
                search_url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 3
                })
                req = urllib.request.Request(search_url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("query", {}).get("search", [])
                    if not results:
                        continue

                    # Select best candidate by score
                    best_page = max(
                        results,
                        key=lambda r: self._score_page(r.get("title", ""), r.get("snippet", ""), title, year)
                    )["title"]

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
                        if clean and len(clean) > 35:
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
                    if story and len(story) > 35:
                        result = self._truncate_smart(story)
                        self.cache.set_setting(cache_key, result)
                        return result

            except Exception as e:
                logger.debug(f"Wikipedia synopsis fetch error for '{query}': {e}")
                continue

        # Mark as not found to avoid redundant queries
        self.cache.set_setting(cache_key, "none")
        return ""

    async def get_synopsis(self, title: str, year: Optional[int] = None) -> str:
        return await asyncio.to_thread(self._sync_fetch, title, year)
