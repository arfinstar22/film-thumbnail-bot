import asyncio
import difflib
import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .cache import MetadataCache
from .synopsis import ensure_indonesian_text

logger = logging.getLogger(__name__)


def normalize_title_for_match(text: str) -> str:
    """Normalisasi judul untuk pencocokan: huruf kecil, tanpa aksen/tanda baca,
    '&'/'dan' diseragamkan jadi 'and', apostrof dibuang (Satan's == Satans)."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("&", " and ")
    t = re.sub(r"['\u2019`\u00b4]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(?:and|dan)\b", " and ", t)
    return re.sub(r"\s+", " ", t).strip()


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
        # P1 FIX: retry + backoff untuk 429/timeout sementara.
        # Tidak mengubah parsing/selection — hanya ketahanan jaringan.
        import time as _t
        api_key = self.get_api_key()
        if not api_key:
            return None

        query_params = dict(params)
        query_params["api_key"] = api_key
        encoded_query = urllib.parse.urlencode(query_params)
        full_url = f"{self.BASE_URL}/{endpoint}?{encoded_query}"

        for attempt in range(3):
            try:
                req = urllib.request.Request(full_url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.warning("TMDb API Error: 401 Unauthorized. Invalid API key.")
                    return None
                elif e.code == 429:
                    wait_s = 1.0 * (attempt + 1)
                    logger.warning(f"TMDb API Error: 429 Rate Limit exceeded. Retry in {wait_s}s (attempt {attempt + 1}/3).")
                    _t.sleep(wait_s)
                    continue
                else:
                    logger.debug(f"TMDb HTTP error {e.code} on {endpoint}: {e}")
                    return None
            except Exception as e:
                # Timeout / DNS sementara → retry 1x, selebihnya serahkan ke fallback
                if attempt < 2 and ("timed out" in str(e).lower() or "temporary" in str(e).lower() or "urlopen" in str(type(e).__name__).lower()):
                    _t.sleep(0.5 * (attempt + 1))
                    continue
                logger.debug(f"TMDb request failed on {endpoint}: {e}")
                return None
        return None

    def search_movie(
        self,
        title: str,
        year: Optional[int] = None,
        is_series: bool = False
    ) -> Dict[str, Any]:
        """Search TMDb for a movie or TV series and return rich metadata.

        Pencocokan bertahap (id-ID -> tanpa tahun -> en-US -> multi -> per kata ->
        judul alternatif/terjemahan). Ini menangani judul Indonesia yang punya
        judul internasional (Impetigore / Perempuan Tanah Jahanam, Satan's Slaves /
        Pengabdi Setan), typo ejaan, dan tahun rilis yang beda 1 tahun.
        """
        if not self.is_enabled() or not title:
            return {}

        clean_title = re.sub(r"\s+", " ", str(title)).strip()
        if not clean_title:
            return {}

        cache_key = (
            f"tmdb_v3_{re.sub(r'[^a-z0-9]+', '_', normalize_title_for_match(clean_title))}"
            f"_{year}_{1 if is_series else 0}"
        )
        cached_data = self.cache.get_setting(cache_key, "")
        if cached_data:
            try:
                return json.loads(cached_data)
            except Exception:
                pass

        pool = self._search_pool(clean_title, year, is_series)
        best_item, best_type, _ = self._pick_best_from_pool(pool, clean_title, year, is_series)

        # Belum ada yang yakin: coba cocokkan lewat judul alternatif/terjemahan resmi.
        if not best_item and pool:
            best_item, best_type, _ = self._pick_with_alternative_titles(
                pool[:5], clean_title, year, is_series
            )

        if not best_item:
            return {}

        tmdb_id = best_item.get("id")
        media_type = best_type or best_item.get("media_type") or (
            "tv" if is_series or "first_air_date" in best_item else "movie"
        )

        # 2. Fetch full details with credits, videos, certification, images, and watch providers
        detail_endpoint = f"{media_type}/{tmdb_id}"
        append_extra = "release_dates" if media_type == "movie" else "content_ratings"
        append_all = (
            f"credits,videos,images,watch/providers,{append_extra},"
            "alternative_titles,translations,external_ids"
        )
        details_id = self._http_get(
            detail_endpoint,
            {
                "language": "id-ID",
                "append_to_response": append_all,
                "include_image_language": "id,en,null"
            }
        ) or {}

        # If Indonesian overview is blank, fetch en-US details for plot/overview
        details_en = {}
        if not details_id.get("overview"):
            details_en = self._http_get(
                detail_endpoint,
                {
                    "language": "en-US",
                    "append_to_response": append_all,
                    "include_image_language": "id,en,null"
                }
            ) or {}

        # Combine details prioritizing Indonesian. Kalau detail gagal total,
        # tetap pakai data hasil pencarian (judul, tahun, rating kasar).
        result = self._extract_metadata(
            details_id or best_item,
            details_en,
            media_type
        )
        if result:
            try:
                self.cache.set_setting(cache_key, json.dumps(result))
            except Exception:
                pass

        return result

    def _search_pool(
        self,
        query: str,
        year: Optional[int],
        is_series: bool
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Kumpulkan kandidat dari beberapa strategi pencarian, dedupe per (tipe, id)."""
        endpoint = "search/tv" if is_series else "search/movie"
        year_key = "first_air_date_year" if is_series else "year"
        attempts: List[Tuple[str, Dict[str, Any]]] = []
        if year:
            attempts.append((endpoint, {
                "query": query, "language": "id-ID",
                "include_adult": "false", year_key: int(year)
            }))
        attempts.append((endpoint, {
            "query": query, "language": "id-ID", "include_adult": "false"
        }))
        attempts.append((endpoint, {
            "query": query, "language": "en-US", "include_adult": "false"
        }))
        attempts.append(("search/multi", {
            "query": query, "language": "en-US", "include_adult": "false"
        }))

        pool: List[Tuple[str, Dict[str, Any]]] = []
        seen = set()

        def _add(endpoint_name: str, resp: Optional[Dict[str, Any]]):
            for it in (resp or {}).get("results", []):
                mtype = it.get("media_type") or (
                    "tv" if endpoint_name == "search/tv" or "first_air_date" in it
                    else "movie"
                )
                if mtype not in ("movie", "tv"):
                    continue
                key = (mtype, it.get("id"))
                if not it.get("id") or key in seen:
                    continue
                seen.add(key)
                pool.append((mtype, it))

        for ep, params in attempts:
            _add(ep, self._http_get(ep, params))
            if pool and self._pick_best_from_pool(pool, query, year, is_series)[0]:
                return pool

        # Typo ejaan: TMDb sangat literal ("Pengadi Setan" -> 0 hasil).
        # Cari per kata kunci terpanjang lalu skor ulang seluruh kandidat.
        words = [w for w in normalize_title_for_match(query).split() if len(w) >= 4]
        for word in sorted(set(words), key=len, reverse=True)[:2]:
            word_years = [int(year), None] if year else [None]
            for wy in word_years:
                params = {"query": word, "language": "id-ID", "include_adult": "false"}
                if wy:
                    params[year_key] = wy
                _add(endpoint, self._http_get(endpoint, params))
                if pool and self._pick_best_from_pool(pool, query, year, is_series)[0]:
                    return pool

        return pool

    def _pick_with_alternative_titles(
        self,
        candidates: List[Tuple[str, Dict[str, Any]]],
        title: str,
        year: Optional[int],
        is_series: bool
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], float]:
        """Cocokkan ulang kandidat teratas memakai judul alternatif & terjemahan resmi TMDb."""
        best_item, best_type, best_score = None, None, 0.0
        for mtype, item in candidates:
            details = self._http_get(
                f"{mtype}/{item.get('id')}",
                {"language": "en-US", "append_to_response": "alternative_titles,translations"}
            ) or {}
            alt_titles: List[str] = []
            for alt in (details.get("alternative_titles") or {}).get("titles", []):
                if alt.get("title"):
                    alt_titles.append(alt["title"])
            for tr in (details.get("translations") or {}).get("translations", []):
                data = tr.get("data") or {}
                for key in ("title", "name"):
                    if data.get(key):
                        alt_titles.append(data[key])
            if not alt_titles:
                continue
            enriched = dict(item)
            enriched["_alt_titles"] = alt_titles
            found, ftype, score = self._pick_best_from_pool(
                [(mtype, enriched)], title, year, is_series, return_score=True
            )
            if found and score > best_score:
                best_item, best_type, best_score = found, ftype, score
        return best_item, best_type, best_score

    def _pick_best_from_pool(
        self,
        pool: List[Tuple[str, Dict[str, Any]]],
        title: str,
        year: Optional[int],
        is_series: bool,
        return_score: bool = False
    ):
        best_item, best_type, best_score = None, None, 0.0
        for mtype, item in pool:
            found, score, _ = self._pick_best_match(
                [item], title, year, is_series, return_score=True
            )
            if found and score > best_score:
                best_item, best_type, best_score = found, mtype, score
        if return_score:
            return best_item, best_type, best_score
        return best_item, best_type, best_score

    def _pick_best_match(
        self,
        results: List[Dict[str, Any]],
        title: str,
        year: Optional[int],
        is_series: bool,
        return_score: bool = False
    ):
        """Skor kandidat: kemiripan judul (termasuk judul alternatif), tahun, bahasa asli."""
        q_norm = normalize_title_for_match(title)
        if not q_norm:
            return (None, None, 0.0) if return_score else None

        best_cand = None
        best_type = None
        best_score = 0.0

        for it in results:
            cand_titles = [
                it.get("title"), it.get("name"),
                it.get("original_title"), it.get("original_name"),
            ]
            cand_titles.extend(it.get("_alt_titles") or [])
            cand_norms = [normalize_title_for_match(t) for t in cand_titles if t]
            cand_norms = [t for t in cand_norms if t]
            if not cand_norms:
                continue

            cand_norm = cand_norms[0]
            base_ratio = max(
                (difflib.SequenceMatcher(None, q_norm, cn).ratio() for cn in cand_norms),
                default=0.0
            )

            # Whole-word containment bonus (harus respect word boundaries)
            for cn in cand_norms:
                if f" {q_norm} " in f" {cn} ":
                    base_ratio = max(base_ratio, 0.85)

            # Sub-judul beda ejaan (Danur 2 Madelaine vs Danur 2: Maddah):
            # izinkan bila 2 kata pertama sama dan tahunnya persis sama.
            q_tokens = q_norm.split()
            c_tokens = cand_norm.split()
            prefix_match = (
                len(q_tokens) >= 2
                and len(c_tokens) >= 2
                and q_tokens[:2] == c_tokens[:2]
            )
            if prefix_match and base_ratio < 0.85 and year:
                date_str = it.get("release_date") or it.get("first_air_date") or ""
                if not (date_str[:4].isdigit() and int(date_str[:4]) == int(year)):
                    prefix_match = False

            # Extract year
            date_str = it.get("release_date") or it.get("first_air_date") or ""
            cand_year = None
            if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
                cand_year = int(date_str[:4])

            # Tahun bagian dari judul (Dilan 1990, 1917, Blade Runner 2049) bukan mismatch.
            year_is_title_part = bool(
                year and re.search(rf"(?<!\d){int(year)}(?!\d)", " ".join(cand_norms))
            )

            if year and cand_year and abs(year - cand_year) > 1 and not year_is_title_part:
                # Tahun beda jauh hanya boleh lolos kalau judul PERSIS sama DAN
                # filmnya Indonesia (rilis Indonesia sering beda tahun).
                # Contoh salah: "Photocopier" (2021) tidak boleh jadi film 2013.
                if not (base_ratio >= 1.0 and it.get("original_language") == "id"):
                    continue

            if base_ratio < 0.85 and not prefix_match:
                continue

            score = base_ratio * 100.0

            media_type = it.get("media_type") or ("tv" if "first_air_date" in it else "movie")
            is_tv = media_type == "tv"
            if is_series != is_tv:
                score -= 40.0

            # Year bonus / penalty
            if year and cand_year:
                if year == cand_year:
                    score += 25.0
                elif abs(year - cand_year) == 1:
                    score += 10.0
                elif not year_is_title_part:
                    score -= 30.0

            # Film Indonesia diprioritaskan (channel ini mayoritas film Indonesia).
            if it.get("original_language") == "id":
                score += 8.0

            # Popularity / vote count kecil saja, jangan sampai mengalahkan judul+tahun.
            pop = it.get("popularity", 0.0) or 0.0
            score += min(pop * 0.03, 6.0)

            if score > best_score and score >= 60.0:
                best_score = score
                best_cand = it
                best_type = media_type

        if return_score:
            return best_cand, best_score, best_type
        return best_cand

    @staticmethod
    def _translated_field(details: Dict[str, Any], field: str) -> str:
        """Ambil field terjemahan Indonesia resmi dari append_to_response=translations."""
        translations = (
            (details.get("translations") or {}).get("translations")
            or details.get("translations")
            or []
        )
        if isinstance(translations, list):
            for tr in translations:
                if tr.get("iso_639_1") != "id":
                    continue
                data = tr.get("data") or {}
                value = data.get(field)
                if value and str(value).strip():
                    return str(value).strip()
        return ""

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

        # Overview / Synopsis (Guaranteed 100% Bahasa Indonesia)
        raw_overview = (
            (main.get("overview") or "").strip()
            or self._translated_field(main, "overview")
            or self._translated_field(fallback, "overview")
            or (fallback.get("overview") or "").strip()
        )
        overview = ensure_indonesian_text(raw_overview) if raw_overview else ""

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

        # AKURASI+SPEED: poster w500 (cukup tajam di HP, 5x lebih ringan dari /original).
        # Backdrop w780 (tetap HD untuk banner, 3x lebih ringan). Tampilan tidak berubah, load lebih cepat.
        poster_url = f"{self.IMAGE_BASE_URL}/w500{poster_path}" if poster_path else None
        backdrop_url = f"{self.IMAGE_BASE_URL}/w780{backdrop_path}" if backdrop_path else None

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

        # Tagline
        tagline = (
            (main.get("tagline") or "").strip()
            or self._translated_field(main, "tagline")
            or (fallback.get("tagline") or "").strip()
        )

        # Production Countries with flag codes
        prod_countries = main.get("production_countries") or fallback.get("production_countries") or []
        countries_display = [pc.get("name", "") for pc in prod_countries if pc.get("name")]
        country_codes = [pc.get("iso_3166_1", "") for pc in prod_countries if pc.get("iso_3166_1")]
        countries_str = ", ".join(countries_display)

        # Spoken Languages
        spoken_langs = main.get("spoken_languages") or fallback.get("spoken_languages") or []
        languages_str = ", ".join([lang.get("name", "") for lang in spoken_langs if lang.get("name")])
        orig_lang = main.get("original_language") or fallback.get("original_language") or ""

        # Runtime (minutes)
        runtime = main.get("runtime") or fallback.get("runtime")

        # Budget & Revenue
        budget = main.get("budget") or fallback.get("budget") or 0
        revenue = main.get("revenue") or fallback.get("revenue") or 0

        # Popularity
        popularity = main.get("popularity") or fallback.get("popularity") or 0.0

        # Full Release Date (reuse date_str from year extraction above)
        release_date_full = date_str

        # Content Rating / Certification (priority: ID → US → first available)
        certification = ""
        if media_type == "movie":
            rd_results = (main.get("release_dates") or {}).get("results", []) or (fallback.get("release_dates") or {}).get("results", [])
            for priority in ["ID", "US"]:
                for rd in rd_results:
                    if rd.get("iso_3166_1") == priority:
                        for r in rd.get("release_dates", []):
                            cert = (r.get("certification") or "").strip()
                            if cert:
                                certification = cert
                                break
                    if certification:
                        break
                if certification:
                    break
        else:
            cr_results = (main.get("content_ratings") or {}).get("results", []) or (fallback.get("content_ratings") or {}).get("results", [])
            for priority in ["ID", "US"]:
                for cr in cr_results:
                    if cr.get("iso_3166_1") == priority:
                        cert = (cr.get("rating") or "").strip()
                        if cert:
                            certification = cert
                            break
                if certification:
                    break

        # Screenwriter
        writers = []
        for crew in credits.get("crew", []):
            if crew.get("job") in ("Screenplay", "Writer", "Story"):
                w_name = crew.get("name")
                if w_name and w_name not in writers:
                    writers.append(w_name)
                    if len(writers) >= 2:
                        break
        writer_str = ", ".join(writers)

        # Production Companies
        prod_companies = main.get("production_companies") or fallback.get("production_companies") or []
        studio_names = [pc.get("name", "") for pc in prod_companies if pc.get("name")]
        studio_str = ", ".join(studio_names[:2])

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
        if vote_cnt:
            res["vote_count"] = int(vote_cnt)
        if vote_avg > 0:
            res["tmdb_rating"] = round(float(vote_avg), 1)
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
        if tagline:
            res["tagline"] = tagline
        if original_title:
            res["original_title"] = original_title
        if countries_str:
            res["production_countries"] = countries_str
        if country_codes:
            res["country_codes"] = country_codes
        if languages_str:
            res["spoken_languages"] = languages_str
        if orig_lang:
            res["original_language"] = orig_lang
        if runtime:
            res["runtime_minutes"] = runtime
        if budget > 0:
            res["budget"] = budget
        if revenue > 0:
            res["revenue"] = revenue
        if popularity:
            res["popularity"] = popularity
        if release_date_full:
            res["release_date"] = release_date_full
        if certification:
            res["certification"] = certification
        if writer_str:
            res["writer"] = writer_str
        if studio_str:
            res["studio"] = studio_str

        # Extract cuplikan adegan film (movie still) from TMDB backdrops
        still_url = ""
        gallery_images = []
        img_data = main.get("images") or fallback.get("images") or {}
        primary_bd_fp = (main.get("backdrop_path") or fallback.get("backdrop_path") or "").strip()
        primary_po_fp = (main.get("poster_path") or fallback.get("poster_path") or "").strip()

        # Find all scene stills (backdrops) distinct from primary backdrop and poster
        bds = img_data.get("backdrops", [])
        cuplikan_candidates = [
            b for b in bds
            if b.get("file_path") and b.get("file_path").strip() not in (primary_bd_fp, primary_po_fp)
        ]

        if cuplikan_candidates:
            # Prefer textless scene stills (iso_639_1 is None or empty)
            textless = [b for b in cuplikan_candidates if b.get("iso_639_1") in (None, "", "null")]
            best_cuplikan = textless[0] if textless else cuplikan_candidates[0]
            chosen_fp = best_cuplikan.get("file_path")
            if chosen_fp:
                still_url = f"https://image.tmdb.org/t/p/w1280{chosen_fp}"
                gallery_images.append(still_url)
        elif main.get("still_path") or fallback.get("still_path"):
            # For TV episodes that have still_path directly
            sp = (main.get("still_path") or fallback.get("still_path") or "").strip()
            if sp:
                still_url = f"https://image.tmdb.org/t/p/w1280{sp}"
                gallery_images.append(still_url)

        if still_url:
            res["still_url"] = still_url
        if gallery_images:
            res["gallery_images"] = gallery_images

        # Watch Providers (ID first, fallback to US)
        wp_data = (main.get("watch/providers") or fallback.get("watch/providers") or {}).get("results", {})
        id_wp = wp_data.get("ID") or wp_data.get("US") or {}
        providers_list = []
        for p in id_wp.get("flatrate", []):
            p_name = p.get("provider_name")
            if p_name and p_name not in providers_list:
                providers_list.append(p_name)
        if not providers_list:
            for p in (id_wp.get("rent", []) + id_wp.get("buy", [])):
                p_name = p.get("provider_name")
                if p_name and p_name not in providers_list:
                    providers_list.append(p_name)
        if providers_list:
            res["watch_providers"] = providers_list

        # OMDb Extra: Awards, Rotten Tomatoes, Metascore, IMDb rating
        imdb_id = (
            (main.get("external_ids") or {}).get("imdb_id")
            or (fallback.get("external_ids") or {}).get("imdb_id")
            or main.get("imdb_id")
            or fallback.get("imdb_id")
        )
        if imdb_id:
            res["imdb_id"] = imdb_id
        omdb_extra = self._fetch_omdb_extra(imdb_id, verified_title or main.get("title") or fallback.get("title"), year)
        if omdb_extra.get("awards"):
            res["awards"] = omdb_extra["awards"]
        if omdb_extra.get("rotten_tomatoes"):
            res["rotten_tomatoes"] = omdb_extra["rotten_tomatoes"]
        if omdb_extra.get("metascore"):
            res["metascore"] = omdb_extra["metascore"]
        if omdb_extra.get("imdb_rating"):
            res["imdb_rating"] = omdb_extra["imdb_rating"]

        # Franchise / Universe Collection
        collection_raw = main.get("belongs_to_collection") or fallback.get("belongs_to_collection")
        if collection_raw and isinstance(collection_raw, dict) and collection_raw.get("id"):
            try:
                cid = collection_raw["id"]
                col_data = self.get_collection(cid)
                if col_data and len(col_data.get("parts", [])) > 1:
                    res["collection"] = col_data
            except Exception as ce:
                logger.debug(f"Failed to fetch collection {collection_raw}: {ce}")

        return res

    def _fetch_omdb_extra(self, imdb_id: Optional[str], title: Optional[str], year: Optional[int]) -> Dict[str, Any]:
        """Fetch Awards, Rotten Tomatoes, and Metascore from OMDb API."""
        out: Dict[str, Any] = {}
        urls = []
        if imdb_id and str(imdb_id).startswith("tt"):
            urls.append(f"http://www.omdbapi.com/?i={imdb_id}&apikey=trilogy")
        if title:
            q_t = urllib.parse.quote(str(title).strip())
            if year:
                urls.append(f"http://www.omdbapi.com/?t={q_t}&y={year}&apikey=trilogy")
            urls.append(f"http://www.omdbapi.com/?t={q_t}&apikey=trilogy")

        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("Response") == "True":
                        # Awards
                        awards = data.get("Awards")
                        if awards and awards != "N/A":
                            out["awards"] = awards

                        # Metascore
                        ms = data.get("Metascore")
                        if ms and ms != "N/A":
                            out["metascore"] = ms

                        # IMDb rating
                        imdb_r = data.get("imdbRating")
                        if imdb_r and imdb_r != "N/A":
                            out["imdb_rating"] = imdb_r

                        # Rotten Tomatoes
                        ratings = data.get("Ratings") or []
                        for r in ratings:
                            if r.get("Source") == "Rotten Tomatoes":
                                out["rotten_tomatoes"] = r.get("Value")
                                break
                        if out:
                            return out
            except Exception:
                pass
        return out

    def get_collection(self, collection_id: int) -> Optional[Dict[str, Any]]:
        """Fetch details of a movie franchise/collection and all its parts in chronological order."""
        if not self.is_enabled() or not collection_id:
            return None

        cache_key = f"tmdb_col_{collection_id}"
        cached = self.cache.get_setting(cache_key, "")
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

        col = self._http_get(f"collection/{collection_id}", {"language": "id-ID"})
        if not col or not col.get("parts"):
            col = self._http_get(f"collection/{collection_id}", {"language": "en-US"})
        if not col:
            return None

        raw_name = (col.get("name") or "").strip()
        clean_name = raw_name
        if clean_name.lower().endswith(" collection"):
            clean_name = f"Seri {clean_name[:-11].strip()}"
        elif clean_name.lower().endswith(" koleksi"):
            clean_name = f"Seri {clean_name[:-8].strip()}"
        elif not clean_name.lower().startswith("seri ") and not clean_name.lower().startswith("koleksi "):
            clean_name = f"Seri {clean_name}"

        parts_raw = col.get("parts", [])
        clean_parts = []
        for p in parts_raw:
            p_title = (p.get("title") or p.get("original_title") or "").strip()
            p_date = (p.get("release_date") or "").strip()
            p_year = int(p_date[:4]) if p_date and len(p_date) >= 4 and p_date[:4].isdigit() else None
            if p_title:
                clean_parts.append({
                    "id": p.get("id"),
                    "title": p_title,
                    "year": p_year,
                    "release_date": p_date,
                })

        # Sort chronologically by release_date / year ascending
        clean_parts.sort(key=lambda x: (x.get("release_date") or "9999", x.get("year") or 9999))

        result = {
            "id": collection_id,
            "name": clean_name,
            "parts": clean_parts
        }
        try:
            self.cache.set_setting(cache_key, json.dumps(result))
        except Exception:
            pass

        return result

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
