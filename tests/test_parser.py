import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.services.metadata.parser import FilenameParser
from bot.services.metadata.caption import CaptionGenerator

def test_parse(filename, expected_title, expected_year=None, expected_res=None):
    meta = FilenameParser().parse(filename)
    status = "✅" 
    issues = []
    if meta.get("title") != expected_title:
        status = "❌"
        issues.append(f"title: '{meta.get('title')}' != '{expected_title}'")
    if expected_year is not None and meta.get("year") != expected_year:
        status = "❌"
        issues.append(f"year: {meta.get('year')} != {expected_year}")
    if expected_res and meta.get("resolution") != expected_res:
        status = "❌"
        issues.append(f"res: {meta.get('resolution')} != {expected_res}")
    print(f"{status} {filename}")
    if issues:
        print(f"   Issues: {issues}")
    return status == "✅"

if __name__ == "__main__":
    results = []
    # 12 Mandatory test cases from prompt
    results.append(test_parse("Kupilih.Jalur.Langit.2026.1080p.WEB.DL.x264.AAC.2.0.N3X.mkv",
        "Kupilih Jalur Langit", 2026, "1080p"))
    results.append(test_parse("Avatar.2009.1080p.BluRay.x264",
        "Avatar", 2009, "1080p"))
    results.append(test_parse("Blade.Runner.2049.2017.1080p.WEB-DL.x265",
        "Blade Runner 2049", 2017, "1080p"))
    results.append(test_parse("The.Dark.Knight.2008.2160p.WEB-DL",
        "The Dark Knight", 2008, "2160p"))
    results.append(test_parse("2001.A.Space.Odyssey.1968.1080p.BluRay",
        "2001 A Space Odyssey", 1968, "1080p"))
    results.append(test_parse("1917.2019.1080p.WEB-DL.x265",
        "1917", 2019, "1080p"))
    results.append(test_parse("Mission.Impossible.Dead.Reckoning.Part.One.2023.1080p",
        "Mission Impossible Dead Reckoning Part One", 2023, "1080p"))
    results.append(test_parse("The.Last.Of.Us.S02E05.1080p.WEB-DL.x265",
        "The Last Of Us", None, "1080p"))
    results.append(test_parse("Movie_Name_2026_1080p_WEB-DL_x265",
        "Movie Name", 2026, "1080p"))
    results.append(test_parse("Movie.Name[2026]1080p.WEB-DL.mkv",
        "Movie Name", 2026, "1080p"))
    results.append(test_parse("Movie.Name.2026.2160p.WEB-DL.DV.HDR10+.x265.10Bit.DDP5.1",
        "Movie Name", 2026, "2160p"))
    results.append(test_parse("Anime.Title.S01E12.1080p.WEBRip.AAC",
        "Anime Title", None, "1080p"))

    print(f"\n{sum(results)}/{len(results)} mandatory tests passed.")
