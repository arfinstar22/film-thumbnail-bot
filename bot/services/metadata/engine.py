import asyncio
import difflib
import logging
import re
from typing import Any, Dict, Optional

from .parser import FilenameParser
from .caption import CaptionGenerator
from .cache import MetadataCache
from .synopsis import WikipediaSynopsisService, ensure_indonesian_text
from .rating import MovieRatingService
from .banner import BannerGenerator
from .thumbnail import ThumbnailGenerator
from .tmdb import normalize_title_for_match

logger = logging.getLogger(__name__)


def resolve_verified_identity(
    parsed_title: str,
    parsed_year: Optional[int],
    rate_res: Dict[str, Any],
    title_confidence: float = 1.0
):
    """Tentukan apakah hasil TMDb layak dipakai, dan judul/tahun mana yang benar.

    Mengembalikan (accepted, title, year). Tahun yang tertanam di judul
    (Dilan 1990, 1917) atau typo judul tidak dianggap mismatch.
    """
    verified = str(rate_res.get("verified_title") or "").strip()
    rate_year = rate_res.get("year")
    o = normalize_title_for_match(parsed_title)
    v = normalize_title_for_match(verified) if verified else o

    close = bool(o and v) and (
        o == v or difflib.SequenceMatcher(None, o, v).ratio() >= 0.85
    )
    numeric_extension = False
    if o and v.startswith(o + " "):
        extra = v[len(o) + 1:].strip()
        numeric_extension = bool(re.fullmatch(r"[\d ivx]+", extra))
    whole_word = bool(o and v) and f" {o} " in f" {v} "
    year_in_verified = bool(parsed_year) and bool(
        re.search(rf"(?<!\d){int(parsed_year)}(?!\d)", verified)
    )

    if parsed_year and rate_year and abs(int(parsed_year) - int(rate_year)) > 1:
        # Tahun beda jauh: hanya boleh kalau judul PERSIS sama (modulo tanda baca),
        # tahunnya bagian dari judul, atau judul hasilnya memperpanjang angka tahun.
        identical = bool(o and v) and o == v
        if not (identical or numeric_extension or year_in_verified):
            return False, parsed_title, parsed_year

    new_title = parsed_title
    if verified and (close or numeric_extension or (title_confidence < 0.6 and whole_word)):
        new_title = verified

    # Tahun hasil TMDb hanya menimpa tahun file kalau file tidak punya tahun,
    # atau tahun itu jelas bagian judul (Dilan 1990: "1990" bukan tahun rilis).
    # Selisih 1 tahun (festival vs rilis luas) tidak perlu menimpa tahun file.
    if not parsed_year:
        new_year = int(rate_year) if rate_year else parsed_year
    elif year_in_verified or numeric_extension:
        new_year = int(rate_year) if rate_year else parsed_year
    else:
        new_year = parsed_year
    return True, new_title, new_year


RESCUE_FIELDS = (
    "poster_url", "backdrop_url", "trailer_url", "rating", "genre", "director",
    "actors", "original_title", "tmdb_id", "year", "plot", "tagline",
    "production_countries", "country_codes", "certification", "runtime_minutes",
    "collection", "collection_checked",
)


async def rescue_poster_metadata(
    metadata: Dict[str, Any],
    title: str,
    year: Optional[int],
    tmdb_service
) -> Dict[str, Any]:
    """Poster kosong = banner/thumbnail tanpa gambar. Coba TMDb sekali lagi
    (tanpa tahun, lalu dengan tahun) sebelum menyerah."""
    if not title or metadata.get("poster_url"):
        return metadata
    for probe_year in (None, year):
        if probe_year is None and year is None:
            pass
        try:
            res = await tmdb_service.async_search_movie(title, probe_year)
        except Exception:
            res = {}
        if res and res.get("poster_url"):
            for field in RESCUE_FIELDS:
                if res.get(field) and not metadata.get(field):
                    metadata[field] = res[field]
            if res.get("plot") and not metadata.get("synopsis"):
                metadata["synopsis"] = res["plot"]
            break
    return metadata



class MetadataEngine:
    """Smart Offline Filename Metadata Engine.
    100% fast, deterministic, no AI API needed."""

    def __init__(self, groq_api_key: Optional[str] = None):
        self.parser = FilenameParser()
        self.banner_gen = BannerGenerator()
        self.thumb_gen = ThumbnailGenerator()
        self.cache = MetadataCache()
        self.caption_gen = CaptionGenerator(cache=self.cache)
        self.rating_service = MovieRatingService(cache=self.cache)
        self.tmdb_service = self.rating_service.tmdb
        self.synopsis_service = WikipediaSynopsisService(cache=self.cache)
        if not self.tmdb_service.is_enabled():
            logger.warning(
                "TMDb API tidak aktif. Poster HD, tagline, dan 'Urutan Nonton' "
                "tidak dapat dideteksi; bot memakai fallback OMDb/IMDb. "
                "Set TMDB_API_KEY di Render atau jalankan /settmdb <api_key>."
            )

    async def process(
        self,
        filename: str,
        extra: Optional[Dict[str, Any]] = None,
        watermark: Optional[str] = None,
        enable_synopsis: bool = True
    ) -> Dict[str, Any]:
        metadata = self.parser.parse(filename)
        if extra:
            metadata.update(extra)

        title = metadata.get("title")
        year = metadata.get("year")
        season = metadata.get("season")
        episode = metadata.get("episode")
        is_series = bool(season is not None or episode is not None)

        if title:
            tasks = []
            if enable_synopsis and not metadata.get("synopsis"):
                tasks.append(self.synopsis_service.get_synopsis(title, year, is_series=is_series, genre=metadata.get("genre")))
            else:
                tasks.append(asyncio.sleep(0, result=""))

            if not metadata.get("rating") or not metadata.get("genre"):
                tasks.append(self.rating_service.get_rating_and_genre(title, year))
            else:
                tasks.append(asyncio.sleep(0, result={}))

            syn_res, rate_res = await asyncio.gather(*tasks)

            if rate_res:
                conf = metadata.get("confidence", {}).get("title", 1.0)
                accepted, new_title, new_year = resolve_verified_identity(
                    title, year, rate_res, conf
                )
                if not accepted:
                    logger.warning(
                        f"Year/title mismatch: parsed '{title}' ({year}) vs TMDb "
                        f"'{rate_res.get('verified_title')}' ({rate_res.get('year')}). Ignoring rate_res."
                    )
                    rate_res = {}
                else:
                    if new_title and new_title.lower() != (title or "").lower():
                        logger.info(f"Verified movie title corrected: '{title}' -> '{new_title}'")
                        title = new_title
                        metadata["title"] = title
                        if not syn_res and enable_synopsis:
                            try:
                                syn_res = await self.synopsis_service.get_synopsis(
                                    title, new_year, is_series=is_series, genre=metadata.get("genre")
                                )
                            except Exception:
                                pass
                    if new_year and new_year != year:
                        logger.info(f"Release year corrected: {year} -> {new_year}")
                        year = int(new_year)
                        metadata["year"] = year

                if rate_res.get("rating") and not metadata.get("rating"):
                    metadata["rating"] = rate_res["rating"]
                if rate_res.get("genre") and not metadata.get("genre"):
                    metadata["genre"] = rate_res["genre"]
                if rate_res.get("director") and not metadata.get("director"):
                    metadata["director"] = rate_res["director"]
                if rate_res.get("actors") and not metadata.get("actors"):
                    metadata["actors"] = rate_res["actors"]
                if rate_res.get("poster_url") and not metadata.get("poster_url"):
                    metadata["poster_url"] = rate_res["poster_url"]
                if rate_res.get("backdrop_url") and not metadata.get("backdrop_url"):
                    metadata["backdrop_url"] = rate_res["backdrop_url"]
                if rate_res.get("trailer_url") and not metadata.get("trailer_url"):
                    metadata["trailer_url"] = rate_res["trailer_url"]
                if rate_res.get("collection") and not metadata.get("collection"):
                    metadata["collection"] = rate_res["collection"]

                for field in (
                    "tagline", "original_title", "production_countries", "country_codes",
                    "spoken_languages", "original_language", "runtime_minutes",
                    "budget", "revenue", "popularity", "release_date",
                    "certification", "writer", "studio",
                    "awards", "rotten_tomatoes", "metascore", "imdb_rating",
                    "imdb_id", "tmdb_id", "vote_count", "tmdb_rating",
                    "watch_providers", "gallery_images", "still_url"
                ):
                    if rate_res.get(field) and not metadata.get(field):
                        metadata[field] = rate_res[field]

            if syn_res and not metadata.get("synopsis"):
                metadata["synopsis"] = syn_res
            elif enable_synopsis and not metadata.get("synopsis"):
                if rate_res and rate_res.get("plot"):
                    translated_plot = self.synopsis_service.translate_if_needed(rate_res["plot"])
                    if translated_plot:
                        metadata["synopsis"] = translated_plot
                if not metadata.get("synopsis"):
                    metadata["synopsis"] = self.synopsis_service.get_fallback_synopsis(
                        title, year, metadata.get("genre") or (rate_res.get("genre") if rate_res else None)
                    )

            if metadata.get("synopsis"):
                metadata["synopsis"] = ensure_indonesian_text(metadata["synopsis"])

            # Poster kosong bikin banner & thumbnail hampa. Coba TMDb sekali lagi.
            metadata = await rescue_poster_metadata(
                metadata, title or "", year, self.tmdb_service
            )

        caption = self.caption_gen.generate(metadata, custom_watermark=watermark)
        self.cache.save_caption(filename, caption)
        return {"caption": caption, "source": "local", "metadata": metadata}

    def extract_metadata(self, caption: str = "", filename: str = "") -> Dict[str, Any]:
        """Extracts title, year, rating, genre, etc. from caption text or filename."""
        import re
        meta: Dict[str, Any] = {}
        if filename:
            try:
                meta = self.parser.parse(filename)
            except Exception:
                meta = {}

        if caption:
            clean = re.sub(r"<[^>]+>", "", caption).strip()
            lines = [line.strip() for line in clean.splitlines() if line.strip()]
            if lines and not meta.get("title"):
                first_line = lines[0]
                m = re.search(r"^(.*?)\s*\((\d{4})\)", first_line)
                if m:
                    meta["title"] = m.group(1).strip()
                    try:
                        meta["year"] = int(m.group(2))
                    except Exception:
                        pass
                else:
                    meta["title"] = first_line

            # Rating
            rate_match = re.search(r"(?:Rating|IMDb|Skor|⭐)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*10)?", clean, re.IGNORECASE)
            if rate_match and not meta.get("rating"):
                meta["rating"] = rate_match.group(1).strip()

            # Genre
            genre_match = re.search(r"(?:Genre|🎭)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if genre_match and not meta.get("genre"):
                meta["genre"] = genre_match.group(1).strip()

            # Director
            dir_match = re.search(r"(?:Sutradara|Director)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if dir_match and not meta.get("director"):
                meta["director"] = dir_match.group(1).strip()

            # Actors
            act_match = re.search(r"(?:Pemeran|Aktor|Bintang|Cast|Actors|👥)\s*[:：]?\s*([^\n|]+)", clean, re.IGNORECASE)
            if act_match and not meta.get("actors"):
                meta["actors"] = act_match.group(1).strip()

            # Synopsis
            syn_match = re.search(r"(?:Sinopsis|Storyline|Deskripsi)\s*[:：]?\s*\n*(.*?)(?=\n\n|\Z)", clean, re.IGNORECASE | re.DOTALL)
            if syn_match and not meta.get("synopsis"):
                meta["synopsis"] = ensure_indonesian_text(syn_match.group(1).strip())

        return meta

    async def enrich_metadata(self, raw_meta: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        """Enriches raw metadata with synopsis, rating, and genre."""
        meta = dict(raw_meta or {})
        title = meta.get("title") or query
        year = meta.get("year")
        season = meta.get("season")
        episode = meta.get("episode")
        is_series = bool(season is not None or episode is not None)

        tasks = []
        if not meta.get("synopsis") and title:
            tasks.append(self.synopsis_service.get_synopsis(title, year, is_series=is_series, genre=meta.get("genre")))
        else:
            tasks.append(asyncio.sleep(0, result=""))

        if (not meta.get("rating") or not meta.get("genre")) and title:
            tasks.append(self.rating_service.get_rating_and_genre(title, year))
        else:
            tasks.append(asyncio.sleep(0, result={}))

        syn_res, rate_res = await asyncio.gather(*tasks)

        if rate_res:
            conf = meta.get("confidence", {}).get("title", 1.0)
            accepted, new_title, new_year = resolve_verified_identity(
                title or "", year, rate_res, conf
            )
            if not accepted:
                logger.warning(
                    f"Enrich metadata: year/title mismatch ({title} {year} vs "
                    f"{rate_res.get('verified_title')} {rate_res.get('year')}). Ignoring rate_res."
                )
                rate_res = {}
            elif new_title and new_title.lower() != (title or "").lower():
                logger.info(f"Enrich verified title corrected: '{title}' -> '{new_title}'")
                title = new_title
                meta["title"] = title
                if not syn_res:
                    try:
                        syn_res = await self.synopsis_service.get_synopsis(
                            title, new_year or year, is_series=is_series, genre=meta.get("genre")
                        )
                    except Exception:
                        pass
            if rate_res and new_year and new_year != year:
                year = int(new_year)
                meta["year"] = year

            if rate_res.get("rating") and not meta.get("rating"):
                meta["rating"] = rate_res["rating"]
            if rate_res.get("genre") and not meta.get("genre"):
                meta["genre"] = rate_res["genre"]
            if rate_res.get("director") and not meta.get("director"):
                meta["director"] = rate_res["director"]
            if rate_res.get("actors") and not meta.get("actors"):
                meta["actors"] = rate_res["actors"]
            if rate_res.get("poster_url") and not meta.get("poster_url"):
                meta["poster_url"] = rate_res["poster_url"]

        if syn_res and not meta.get("synopsis"):
            meta["synopsis"] = syn_res
        elif not meta.get("synopsis") and title:
            if rate_res and rate_res.get("plot"):
                translated_plot = self.synopsis_service.translate_if_needed(rate_res["plot"])
                if translated_plot:
                    meta["synopsis"] = translated_plot
            if not meta.get("synopsis"):
                meta["synopsis"] = self.synopsis_service.get_fallback_synopsis(
                    title, year, meta.get("genre") or (rate_res.get("genre") if rate_res else None)
                )

        if meta.get("synopsis"):
            meta["synopsis"] = ensure_indonesian_text(meta["synopsis"])

        meta = await rescue_poster_metadata(meta, title or "", year, self.tmdb_service)

        return meta