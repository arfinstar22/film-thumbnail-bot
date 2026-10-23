import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .cache import MetadataCache

logger = logging.getLogger(__name__)


class TMDbService:
    """The Movie Database (TMDb) API Integration Service.
    
    Fetches official HD posters, high-res backdrops, native Indonesian synopses,
    accurate cast/crew, release years, official ratings, and direct YouTube trailers.
    """

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    GENRE_MAP = {
        28: "Aksi",
        12: "Petualangan",
        16: "Animasi",
        35: "Komedi",
        80: "Kriminal",
        99: "Dokumenter",
        18: "Drama",
        10751: "Keluarga",
        14: "Fantasi",
        36: "Sejarah",
        27: "Horor",
        10402: "Musik",
        9648: "Misteri",
        10749: "Romantis",
        878: "Sci-Fi",
        10770: "Film TV",
        53: "Thriller",
        10752: "Perang",
        37: "Western",
        # TV Genres
        10759: "Aksi & Petualangan",
        10762: "Anak-anak",
        10763: "Berita",
        10764: "Reality",
        10765: "Sci-Fi & Fantasi",
        10766: "Soap",
        10767: "Talkshow",
        10768: "Perang & Politik"
    }

    def __init__(self, cache: Optional[MetadataCache] = None, api_key: Optional[str] = None):
        self.cache = cache or MetadataCache()
        self.api_key = api_key
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

    def get_api_key(self) -> str:
        """Resolves the TMDb API key from explicit arg, env var, or database settings."""
        if self.api_key:
            return self.api_key.strip()
        env_key = os.getenv("TMDB_API_KEY", "").strip()
        if env_key:
            return env_key
        return self.cache.get_setting("tmdb_api_key", "").strip()

    def is_enabled(self) -> bool:
        """Returns True if a TMDb API key is configured."""
        return bool(self.get_api_key())

    def validate_key(self, api_key: str) -> bool:
        """Validates a TMDb API key by querying configuration."""
        if not api_key or not api_key.strip():
            return False
        clean_key = api_key.strip()
        url = f"{self.BASE_URL}/configuration?api_key={clean_key}"
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("images"))
        except Exception as e:
            logger.debug(f"TMDb key validation failed: {e}")
            return False

    def _http_get(self, endpoint: str, params: Dict[str, Any], timeout: float = 3.5) -> Optional[Dict[str, Any]]:
        api_key = self.get_api_key()
        if not api_key:
            return None
        
        query_params = dict(params)
        query_params["api_key"] = api_key
        encoded_query = urllib.parse.urlencode(query_params)
        full_url = f"{self.BASE_URL}/{endpoint}?{encoded_query}"

        try:
            req = urllib.request.Request(full_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.warning("TMDb API Error: 401 Unauthorized. Invalid API key.")
            elif e.code == 429:
                logger.warning("TMDb API Error: 429 Rate Limit exceeded.")
            else:
                logger.debug(f"TMDb HTTP error {e.code} on {endpoint}: {e}")
        except Exception as e:
            logger.debug(f"TMDb request failed on {endpoint}: {e}")
        return None

    def search_movie(
        self,
        title: str,
        year: Optional[int] = None,
        is_series: bool = False
    ) -> Dict[str, Any]:
        """Search TMDb for a movie or TV series and return rich metadata."""
        if not self.is_enabled() or not title:
            return {}

        clean_title = re.sub(r"[^\w\s]", " ", title).strip()
        if not clean_title:
            return {}

        cache_key = f"tmdb_v2_{clean_title.lower()}_{year}_{1 if is_series else 0}"
        cached_data = self.cache.get_setting(cache_key, "")
        if cached_data:
            try:
                return json.loads(cached_data)
            except Exception:
                pass

        # 1. Search in Indonesian (id-ID)
        endpoint = "search/tv" if is_series else "search/movie"
        params: Dict[str, Any] = {
            "query": clean_title,
            "language": "id-ID",
            "include_adult": "false"
        }
        if year and not is_series:
            params["year"] = int(year)
        elif year and is_series:
            params["first_air_date_year"] = int(year)

        search_resp = self._http_get(endpoint, params)
        results = search_resp.get("results", []) if search_resp else []

        # If 0 results, retry without year filter or in en-US
        if not results and year:
            params_noyear = dict(params)
            params_noyear.pop("year", None)
            params_noyear.pop("first_air_date_year", None)
            search_resp = self._http_get(endpoint, params_noyear)
            results = search_resp.get("results", []) if search_resp else []

        if not results:
            # Fallback to multi-search in en-US
            multi_params = {
                "query": clean_title,
                "language": "en-US",
                "include_adult": "false"
            }
            search_resp = self._http_get("search/multi", multi_params)
            multi_items = search_resp.get("results", []) if search_resp else []
            results = [it for it in multi_items if it.get("media_type") in ("movie", "tv")]

        if not results:
            return {}

        # Pick best candidate
        best_item = self._pick_best_match(results, clean_title, year, is_series)
        if not best_item:
            return {}

        tmdb_id = best_item.get("id")
        media_type = best_item.get("media_type") or ("tv" if is_series or "first_air_date" in best_item else "movie")

        # 2. Fetch full details with credits and videos
        detail_endpoint = f"{media_type}/{tmdb_id}"
        details_id = self._http_get(
            detail_endpoint,
            {"language": "id-ID", "append_to_response": "credits,videos"}
        ) or {}

        # If Indonesian overview is blank, fetch en-US details for plot/overview
        details_en = {}
        if not details_id.get("overview"):
            details_en = self._http_get(
                detail_endpoint,
                {"language": "en-US", "append_to_response": "credits,videos"}
            ) or {}

        # Combine details prioritizing Indonesian
        result = self._extract_metadata(details_id, details_en, media_type)
        if result:
            try:
                self.cache.set_setting(cache_key, json.dumps(result))
            except Exception:
                pass

        return result

    def _pick_best_match(
        self,
        results: List[Dict[str, Any]],
        title: str,
        year: Optional[int],
        is_series: bool
    ) -> Optional[Dict[str, Any]]:
        import difflib
        import re
        q_clean = title.lower().strip()
        best_cand = None
        best_score = 0.0

        for it in results:
            cand_title = (it.get("title") or it.get("name") or "").lower().strip()
            cand_orig = (it.get("original_title") or it.get("original_name") or "").lower().strip()

            # Extract year
            date_str = it.get("release_date") or it.get("first_air_date") or ""
            cand_year = None
            if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
                cand_year = int(date_str[:4])

            # Disqualify if years differ significantly and title is not nearly identical
            if year and cand_year and abs(year - cand_year) > 1:
                # Calculate quick title ratio
                r_quick = max(
                    difflib.SequenceMatcher(None, q_clean, cand_title).ratio(),
                    difflib.SequenceMatcher(None, q_clean, cand_orig).ratio()
                )
                if r_quick < 0.90:
                    continue

            # Similarity ratio
            ratio_title = difflib.SequenceMatcher(None, q_clean, cand_title).ratio()
            ratio_orig = difflib.SequenceMatcher(None, q_clean, cand_orig).ratio()
            base_ratio = max(ratio_title, ratio_orig)

            # Whole-word substring match bonus (MUST respect word boundaries)
            if re.search(r"\b" + re.escape(q_clean) + r"\b", cand_title) or re.search(r"\b" + re.escape(q_clean) + r"\b", cand_orig):
                base_ratio = max(base_ratio, 0.85)

            if base_ratio < 0.55:
                continue

            score = base_ratio * 100.0

            # Year bonus / penalty
            if year and cand_year:
                if year == cand_year:
                    score += 25.0
                elif abs(year - cand_year) == 1:
                    score += 10.0
                else:
                    score -= 30.0

            # Popularity / vote count bonus
            pop = it.get("popularity", 0.0)
            score += min(pop * 0.05, 10.0)

            if score > best_score and score >= 60.0:
                best_score = score
                best_cand = it

        return best_cand

    def _extract_metadata(
        self,
        details_id: Dict[str, Any],
        details_en: Dict[str, Any],
        media_type: str
    ) -> Dict[str, Any]:
        """Extracts normalized metadata dictionary matching Film Thumbnail Bot conventions."""
        main = details_id if details_id else details_en
        fallback = details_en if details_id else {}

        verified_title = main.get("title") or main.get("name") or fallback.get("title") or fallback.get("name")
        original_title = main.get("original_title") or main.get("original_name")

        # Year
        date_str = main.get("release_date") or main.get("first_air_date") or fallback.get("release_date") or fallback.get("first_air_date") or ""
        year = None
        if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
            year = int(date_str[:4])

        # Rating
        vote_avg = main.get("vote_average") or fallback.get("vote_average") or 0.0
        vote_cnt = main.get("vote_count") or fallback.get("vote_count") or 0
        rating_str = ""
        if vote_avg > 0:
            formatted_votes = f"{vote_cnt:,}" if vote_cnt else "0"
            rating_str = f"{round(vote_avg, 1)} / 10 • TMDb ({formatted_votes} ulasan)"

        # Genres
        genres_list = main.get("genres") or fallback.get("genres") or []
        translated_genres = []
        for g in genres_list:
            gid = g.get("id")
            name = g.get("name", "")
            if gid in self.GENRE_MAP:
                translated_genres.append(self.GENRE_MAP[gid])
            elif name:
                translated_genres.append(name)
        genre_str = ", ".join(translated_genres)

        # Overview / Synopsis
        overview = (main.get("overview") or fallback.get("overview") or "").strip()

        # Credits: Director & Cast
        credits = main.get("credits") or fallback.get("credits") or {}
        directors = []
        for crew in credits.get("crew", []):
            if crew.get("job") == "Director" or crew.get("department") == "Directing":
                c_name = crew.get("name")
                if c_name and c_name not in directors:
                    directors.append(c_name)
                    if len(directors) >= 2:
                        break
        director_str = ", ".join(directors)

        actors = []
        for cast in credits.get("cast", []):
            a_name = cast.get("name")
            if a_name and a_name not in actors:
                actors.append(a_name)
                if len(actors) >= 4:
                    break
        actors_str = ", ".join(actors)

        # Poster & Backdrop URLs
        poster_path = main.get("poster_path") or fallback.get("poster_path")
        backdrop_path = main.get("backdrop_path") or fallback.get("backdrop_path")

        poster_url = f"{self.IMAGE_BASE_URL}/original{poster_path}" if poster_path else None
        backdrop_url = f"{self.IMAGE_BASE_URL}/original{backdrop_path}" if backdrop_path else None

        # Videos: Official YouTube Trailer
        videos = main.get("videos", {}).get("results", []) or fallback.get("videos", {}).get("results", [])
        trailer_url = None
        for v in videos:
            if v.get("site") == "YouTube":
                v_type = (v.get("type") or "").lower()
                if v_type in ("trailer", "teaser") and v.get("key"):
                    trailer_url = f"https://www.youtube.com/watch?v={v['key']}"
                    if v_type == "trailer":
                        break  # preferred

        res: Dict[str, Any] = {
            "source": "tmdb",
            "tmdb_id": main.get("id"),
            "media_type": media_type
        }
        if verified_title:
            res["verified_title"] = verified_title
        if original_title:
            res["original_title"] = original_title
        if year:
            res["year"] = year
        if rating_str:
            res["rating"] = rating_str
            res["rating_value"] = round(vote_avg, 1)
        if genre_str:
            res["genre"] = genre_str
        if director_str:
            res["director"] = director_str
        if actors_str:
            res["actors"] = actors_str
        if overview:
            res["plot"] = overview
        if poster_url:
            res["poster_url"] = poster_url
        if backdrop_url:
            res["backdrop_url"] = backdrop_url
        if trailer_url:
            res["trailer_url"] = trailer_url

        return res

    async def async_search_movie(
        self,
        title: str,
        year: Optional[int] = None,
        is_series: bool = False
    ) -> Dict[str, Any]:
        """Asynchronously searches TMDb in a background thread."""
        return await asyncio.to_thread(self.search_movie, title, year, is_series)

    def suggest_movie_correction(self, raw_query: str) -> Optional[Dict[str, Any]]:
        """Intelligently detects typos and release year mismatches for movie queries.
        Returns suggestion dictionary with rich metadata if a typo/mismatch is found, or None if exact/no match.
        """
        if not self.is_enabled() or not raw_query or not raw_query.strip():
            return None

        from .cache import normalize_movie_title_and_year
        clean_title, year, _ = normalize_movie_title_and_year(raw_query)
        if not clean_title:
            return None

        clean_q = re.sub(r"[^\w\s]", " ", clean_title).strip()
        if not clean_q:
            return None

        direct_resp = self._http_get("search/movie", {"query": clean_q, "language": "id-ID"})
        items = direct_resp.get("results", []) if direct_resp else []

        if not items:
            direct_resp_en = self._http_get("search/movie", {"query": clean_q, "language": "en-US"})
            items = direct_resp_en.get("results", []) if direct_resp_en else []

        def _score_item(it: Dict[str, Any]) -> Tuple[float, str, Optional[int], str, int, Dict[str, Any]]:
            import difflib
            cand_t = it.get("title") or it.get("name") or ""
            cand_orig = it.get("original_title") or it.get("original_name") or ""
            d_str = it.get("release_date") or it.get("first_air_date") or ""
            cand_y = int(d_str[:4]) if d_str and len(d_str) >= 4 and d_str[:4].isdigit() else None
            cand_lang = it.get("original_language") or ""
            tmdb_id = it.get("id") or 0

            r_title = difflib.SequenceMatcher(None, clean_q.lower(), cand_t.lower()).ratio()
            r_orig = difflib.SequenceMatcher(None, clean_q.lower(), cand_orig.lower()).ratio()
            base_r = max(r_title, r_orig)

            score = base_r
            if cand_lang == "id":
                score += 0.25
            elif cand_lang == "ms":
                score += 0.05

            if year and cand_y:
                if cand_y == year:
                    score += 0.30
                elif abs(cand_y - year) == 1:
                    score += 0.15
                else:
                    score -= 0.15
            elif not year and cand_y:
                pop = it.get("popularity", 0.0)
                score += min(0.10, pop / 100.0)

            return score, cand_t, cand_y, cand_lang, tmdb_id, it

        if items:
            best_direct = max(items, key=lambda x: _score_item(x)[0])
            score, cand_t, cand_y, cand_lang, tmdb_id, it = _score_item(best_direct)
            is_exact = (cand_t.lower() == clean_q.lower() or (it.get("original_title") or "").lower() == clean_q.lower())

            # Year correction (exact or near-exact title match, but year is wrong)
            if is_exact and year and cand_y and cand_y != year:
                meta = self.search_movie(cand_t, cand_y)
                return {
                    "title": cand_t,
                    "year": cand_y,
                    "is_typo": False,
                    "is_year_corrected": True,
                    "original_query": raw_query.strip(),
                    "reason": f"Film dirilis pada tahun {cand_y} (bukan {year})",
                    "rating": meta.get("rating") or (f"{round(it.get('vote_average', 0.0), 1)} / 10 • TMDb" if it.get("vote_average") else "-"),
                    "genre": meta.get("genre") or "-",
                    "plot": meta.get("plot") or it.get("overview") or "",
                    "poster_url": meta.get("poster_url") or (f"https://image.tmdb.org/t/p/w500{it['poster_path']}" if it.get("poster_path") else "")
                }

            # Typo in direct results (e.g. "Pengabdi Satan" -> "Pengabdi Setan")
            if not is_exact and score >= 0.90:
                meta = self.search_movie(cand_t, cand_y)
                return {
                    "title": cand_t,
                    "year": cand_y,
                    "is_typo": True,
                    "is_year_corrected": bool(year and cand_y and cand_y != year),
                    "original_query": raw_query.strip(),
                    "reason": f"Koreksi ejaan dari \"{clean_q}\"",
                    "rating": meta.get("rating") or (f"{round(it.get('vote_average', 0.0), 1)} / 10 • TMDb" if it.get("vote_average") else "-"),
                    "genre": meta.get("genre") or "-",
                    "plot": meta.get("plot") or it.get("overview") or "",
                    "poster_url": meta.get("poster_url") or (f"https://image.tmdb.org/t/p/w500{it['poster_path']}" if it.get("poster_path") else "")
                }

        # Typo candidate search (vowel substitutions)
        vowels = "aiueo"
        words = clean_q.split()
        cand_queries = []
        for w_idx, w in enumerate(words):
            w_low = w.lower()
            for i, ch in enumerate(w_low):
                if ch in vowels:
                    for v in vowels:
                        if v != ch:
                            nw = list(words)
                            nw[w_idx] = w_low[:i] + v + w_low[i+1:]
                            cand_queries.append(" ".join(nw))

        all_candidates = []
        for cq in cand_queries[:6]:
            resp = self._http_get("search/movie", {"query": cq, "language": "id-ID"})
            for it in (resp.get("results", []) if resp else []):
                all_candidates.append(it)

        if all_candidates:
            best_typo = max(all_candidates, key=lambda x: _score_item(x)[0])
            score, cand_t, cand_y, cand_lang, tmdb_id, it = _score_item(best_typo)
            if score >= 0.95 and cand_t.lower() != clean_q.lower():
                meta = self.search_movie(cand_t, cand_y)
                return {
                    "title": cand_t,
                    "year": cand_y,
                    "is_typo": True,
                    "is_year_corrected": bool(year and cand_y and cand_y != year),
                    "original_query": raw_query.strip(),
                    "reason": f"Koreksi ejaan dari \"{clean_q}\"",
                    "rating": meta.get("rating") or (f"{round(it.get('vote_average', 0.0), 1)} / 10 • TMDb" if it.get("vote_average") else "-"),
                    "genre": meta.get("genre") or "-",
                    "plot": meta.get("plot") or it.get("overview") or "",
                    "poster_url": meta.get("poster_url") or (f"https://image.tmdb.org/t/p/w500{it['poster_path']}" if it.get("poster_path") else "")
                }

        return None

    async def async_suggest_movie_correction(self, raw_query: str) -> Optional[Dict[str, Any]]:
        """Asynchronously calls suggest_movie_correction in a background thread."""
        return await asyncio.to_thread(self.suggest_movie_correction, raw_query)
