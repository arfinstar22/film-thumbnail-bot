"""Smart Telegram movie hashtag generator."""
import re
from typing import List, Optional, Union


def generate_smart_hashtags(
    title: Optional[str] = None,
    year: Optional[Union[int, str]] = None,
    genre: Optional[str] = None,
    actors: Optional[str] = None,
    max_tags: int = 6
) -> str:
    """Generate concise, searchable Telegram hashtags for movie posts.

    Example:
    title="Khadam", year=2026, genre="Drama, Horor, Thriller", actors="Aghniny Haque, Remy Ishak"
    -> "#Khadam #Film2026 #Horor #Thriller #Drama #AghninyHaque"
    """
    tags: List[str] = []

    # 1. Title Tag
    if title:
        clean_title = re.sub(r"[^\w]", "", title.title())
        if clean_title and len(clean_title) >= 2:
            tags.append(f"#{clean_title}")

    # 2. Year Tag
    if year:
        try:
            y_int = int(str(year)[:4])
            if 1900 <= y_int <= 2099:
                tags.append(f"#Film{y_int}")
        except Exception:
            pass

    # 3. Genre Tags
    if genre:
        raw_genres = [g.strip() for g in genre.replace("/", ",").split(",") if g.strip()]
        for g in raw_genres:
            g_tag = re.sub(r"[^\w]", "", g.title())
            if g_tag and f"#{g_tag}" not in tags:
                tags.append(f"#{g_tag}")
            if len(tags) >= max_tags - 1:
                break

    # 4. Lead Actor Tag
    if actors and len(tags) < max_tags:
        actor_list = [a.strip() for a in actors.split(",") if a.strip()]
        if actor_list:
            lead_actor = re.sub(r"[^\w]", "", actor_list[0].title())
            if lead_actor and len(lead_actor) >= 3 and f"#{lead_actor}" not in tags:
                tags.append(f"#{lead_actor}")

    return " ".join(tags[:max_tags])
