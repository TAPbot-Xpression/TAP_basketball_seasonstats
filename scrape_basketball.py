"""
scrape_basketball.py
Scrapes Summit League Men's Basketball season cumulative player stats and rosters.
Targets ONLY season aggregate tables/data and strictly excludes Game-by-Game tables,
schedule rows, team leader sidebars, and staff.
Outputs individual team JSON files as well as docs/all_teams.json.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city",
        "stats_url": "https://kcroos.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://kcroos.com/sports/mens-basketball/roster",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota",
        "stats_url": "https://fightinghawks.com/sports/mens-basketball/stats",
        "roster_url": "https://fightinghawks.com/sports/mens-basketball/roster",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state",
        "stats_url": "https://gobison.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://gobison.com/sports/mens-basketball/roster",
    },
    {
        "name": "Omaha",
        "slug": "omaha",
        "stats_url": "https://omahamavs.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://omahamavs.com/sports/mens-basketball/roster",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts",
        "stats_url": "https://oruathletics.com/sports/mens-basketball/stats/2025-26?path=mbball",
        "roster_url": "https://oruathletics.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota",
        "stats_url": "https://goyotes.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://goyotes.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state",
        "stats_url": "https://gojacks.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://gojacks.com/sports/mens-basketball/roster",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas",
        "stats_url": "https://tommiesports.com/sports/mbball/stats/2025-26",
        "roster_url": "https://tommiesports.com/sports/mbball/roster",
    },
]

DISCARD_EXACT_NAMES = {
    "ft%", "blk", "ast", "tot", "avg", "pts", "off", "def", "min", "stl",
    "to", "fg%", "3pt%", "3p%", "gp", "gs", "pct", "reb", "player", "no.",
    "total", "totals", "team", "opponent", "opponents", "view bio", "bio",
    "team tm team", "tm", "overall", "conference", "image", "full name", "name",
    "scoring", "averages"
}

STAFF_KEYWORDS = [
    "coach", "trainer", "director", "coordinator", "manager", "athletic",
    "operations", "strength", "conditioning", "physician", "assistant"
]


def fetch_url(url: str) -> Optional[str]:
    """Fetch URL with custom headers and error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def clean_name(raw_name: str) -> str:
    """
    Cleans raw player name strings:
    - Removes 'View Bio', 'Image', stray quotes
    - Resolves duplicated names like 'Branch, Karmello Branch' or 'Evans, CjEvans, Cj'
    - Transforms 'Branch, Karmello' -> 'Karmello Branch'
    - Eliminates embedded jersey digits
    """
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").replace("Image", "").strip()
    text = re.sub(r"['\"]+", "", text).strip()

    if not text:
        return ""

    # Check for concatenated duplicate like 'Hudgens, Trent02Hudgens, Trent' or 'Evans, CjEvans, Cj'
    match_dup = re.search(r"^(.*?)(?:\d{1,2})?\1$", text)
    if match_dup and len(match_dup.group(1)) > 3:
        text = match_dup.group(1)

    # Standardize comma format 'Last, First'
    if "," in text:
        parts = [p.strip() for p in text.split(",", 1)]
        last = parts[0]
        first = parts[1] if len(parts) > 1 else ""

        # Remove digits
        last = re.sub(r"\b\d{1,2}\b", "", last).strip()
        first = re.sub(r"\b\d{1,2}\b", "", first).strip()

        # If first contains last already (e.g. 'Karmello Branch')
        if last.lower() in first.lower() and len(first.split()) > 1:
            text = first
        elif first and last:
            text = f"{first} {last}"
        else:
            text = first or last

    # Remove stray embedded digits and multiple spaces
    text = re.sub(r"\b\d{1,2}\b", "", text)
    text = " ".join(text.split()).strip()
    return text


def clean_number(raw_num: str) -> str:
    """Extracts jersey number cleanly (e.g. '00', '01', '7', '21')."""
    if raw_num is None:
        return ""
    text = str(raw_num).strip().replace("#", "")
    m = re.match(r"^(\d{1,2})$", text)
    if m:
        return m.group(1)
    return ""


def normalize_position(pos_str: str) -> str:
    """Normalizes basketball positions strictly to G (Guard) or F (Forward)."""
    if not pos_str:
        return ""
    pos_upper = pos_str.upper().strip()
    if "GUARD" in pos_upper or "G/F" in pos_upper or pos_upper == "G":
        return "G"
    if "FORWARD" in pos_upper or "F/C" in pos_upper or "CENTER" in pos_upper or pos_upper in ("F", "C"):
        return "F"
    if re.search(r"\bG\b", pos_upper):
        return "G"
    if re.search(r"\bF\b", pos_upper):
        return "F"
    return ""


def normalize_year(yr_str: str) -> str:
    """
    Standardizes academic class years:
    FR, SO, JR, SR, GR, 5TH, or Redshirts (R-FR, R-SO, R-JR, R-SR).
    """
    if not yr_str:
        return ""
    y = yr_str.upper().strip()
    is_rs = "R-" in y or "RS" in y or "REDSHIRT" in y

    if "5TH" in y or "GRADUATE" in y or "GR" in y:
        return "GR"
    if "SENIOR" in y or "SR" in y:
        return "R-SR" if is_rs else "SR"
    if "JUNIOR" in y or "JR" in y:
        return "R-JR" if is_rs else "JR"
    if "SOPHOMORE" in y or "SO" in y:
        return "R-SO" if is_rs else "SO"
    if "FRESHMAN" in y or "FR" in y:
        return "R-FR" if is_rs else "FR"
    return ""


def is_valid_player_row(name: str) -> bool:
    """Validates that candidate is an actual basketball player row."""
    if not name or len(name.strip()) < 2:
        return False

    low = name.strip().lower()

    if low in DISCARD_EXACT_NAMES:
        return False

    # Discard single words that look like first names only or pure numbers/decimals/dates
    if re.match(r"^(\.\d+|\d+(\.\d+)?|\d{1,2}/\d{1,2}/\d{2,4})$", low):
        return False

    # Discard game logs ('at TCU', 'vs Omaha', scores '45-81')
    if re.search(r"\b(vs|at|\d+-\d+)\b", low):
        return False

    # Discard summary and staff keywords
    if any(tok in low for tok in ["team tm", "opponents", "opponent", "total", "totals", "attendance"]):
        return False
    if any(staff in low for staff in STAFF_KEYWORDS):
        return False

    return True


def scrape_roster(roster_url: str) -> Dict[str, Dict[str, str]]:
    """
    Scrapes team roster for validation, Position (G/F), and Academic Year.
    Excludes staff and non-players.
    """
    html = fetch_url(roster_url)
    roster_lookup: Dict[str, Dict[str, str]] = {}
    if not html:
        return roster_lookup

    soup = BeautifulSoup(html, "html.parser")

    # Filter out staff containers if present
    for staff_section in soup.find_all(class_=re.compile(r"staff|coaches", re.I)):
        staff_section.decompose()

    players = soup.find_all(class_=re.compile(r"roster-player|roster__item|sidearm-roster-player|s-person-details", re.I))

    for p in players:
        name_el = p.find(class_=re.compile(r"name|player-name", re.I))
        raw_name = name_el.get_text(separator=" ", strip=True) if name_el else ""
        c_name = clean_name(raw_name)

        if not c_name or not is_valid_player_row(c_name):
            continue

        num_el = p.find(class_=re.compile(r"jersey|number|player-number", re.I))
        raw_num = num_el.get_text(strip=True) if num_el else ""
        c_num = clean_number(raw_num)

        pos_el = p.find(class_=re.compile(r"position|pos", re.I))
        raw_pos = pos_el.get_text(strip=True) if pos_el else ""
        c_pos = normalize_position(raw_pos)

        yr_el = p.find(class_=re.compile(r"academic-year|year|class", re.I))
        raw_yr = yr_el.get_text(strip=True) if yr_el else ""
        c_yr = normalize_year(raw_yr)

        info = {
            "name": c_name,
            "number": c_num,
            "position": c_pos,
            "year": c_yr
        }
        roster_lookup[c_name.lower()] = info
        if c_num:
            roster_lookup[f"#{c_num}"] = info

    # Strategy 2: Sidearm Table format
    if not roster_lookup:
        for row in soup.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) >= 3:
                num = ""
                pos = ""
                yr = ""
                name_cand = ""
                for col in cols:
                    if not num and col.isdigit():
                        num = clean_number(col)
                    if not pos:
                        pos = normalize_position(col)
                    if not yr:
                        yr = normalize_year(col)
                    c_clean = clean_name(col)
                    if not name_cand and is_valid_player_row(c_clean) and not normalize_position(col) and not normalize_year(col):
                        name_cand = c_clean

                if name_cand and is_valid_player_row(name_cand):
                    info = {
                        "name": name_cand,
                        "number": num,
                        "position": pos,
                        "year": yr
                    }
                    roster_lookup[name_cand.lower()] = info
                    if num:
                        roster_lookup[f"#{num}"] = info

    return roster_lookup


def parse_nuxt_json_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses Sidearm Nuxt payload focusing exclusively on individual player objects
    containing season totals/averages and ignoring game-by-game items.
    """
    players = []
    patterns = [
        r"__NUXT_DATA__\s*=\s*(\[.*?\]);",
        r"window\.__NUXT__\s*=\s*(.*?);\s*</script>",
        r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>'
    ]

    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
            if not isinstance(data, list):
                continue

            for item in data:
                if isinstance(item, dict):
                    # Discard game-by-game logs and footers
                    if "opponent" in item or "winOrLoss" in item or "boxscoreUrl" in item:
                        continue
                    if item.get("isAFooterStat") is True:
                        continue

                    # Look for player name key
                    raw_name = item.get("playerName") or item.get("nameFromStats") or item.get("name") or item.get("player")
                    if not raw_name or not isinstance(raw_name, str):
                        continue

                    c_name = clean_name(raw_name)
                    if not is_valid_player_row(c_name):
                        continue

                    raw_num = item.get("playerUniform") or item.get("jersey") or item.get("number") or ""
                    c_num = clean_number(str(raw_num))

                    # Must have cumulative / season stats
                    avg_val = str(item.get("pointsPerGame") or item.get("pts_avg") or item.get("ppg") or item.get("avg") or "")
                    min_val = str(item.get("minutesPerGame") or item.get("min_avg") or item.get("mpg") or "")
                    tot_reb = str(item.get("reboundsPerGame") or item.get("reb_avg") or item.get("rpg") or item.get("totalRebounds") or "")
                    ast_val = str(item.get("assistsPerGame") or item.get("ast_avg") or item.get("apg") or item.get("assists") or "")
                    to_val = str(item.get("turnoversPerGame") or item.get("to_avg") or item.get("turnovers") or "")
                    stl_val = str(item.get("stealsPerGame") or item.get("stl_avg") or item.get("steals") or "")
                    blk_val = str(item.get("blocksPerGame") or item.get("blk_avg") or item.get("blocks") or "")

                    fg_pct = str(item.get("fieldGoalsPercentage") or item.get("fg_pct") or item.get("fgPct") or "")
                    three_pct = str(item.get("threePointFieldGoalsPercentage") or item.get("three_pt_pct") or item.get("threePtPct") or "")
                    ft_pct = str(item.get("freeThrowsPercentage") or item.get("ft_pct") or item.get("ftPct") or "")

                    # Verify at least one essential basketball field is populated
                    if not any([avg_val, min_val, fg_pct, ft_pct, tot_reb]):
                        continue

                    players.append({
                        "name": c_name,
                        "number": c_num,
                        "avg": avg_val,
                        "fg_pct": fg_pct,
                        "three_pt_pct": three_pct,
                        "ft_pct": ft_pct,
                        "tot_reb": tot_reb,
                        "ast": ast_val,
                        "to": to_val,
                        "stl": stl_val,
                        "blk": blk_val,
                        "min": min_val
                    })
        except Exception:
            continue

        if players:
            break

    return players


def parse_html_table_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses Sidearm statistical tables, isolating the full season cumulative Player Stats table.
    Explicitly ignores Game-by-Game tables, Opponent comparisons, and category leader blocks.
    """
    soup = BeautifulSoup(html, "html.parser")
    players = []

    for table in soup.find_all("table"):
        # Check parents to avoid Game-by-Game or Leaders containers
        parent_text = " ".join([p.get_text() for p in table.parents if p.name in ["div", "section"]])[:400].lower()
        if any(bad in parent_text for bad in ["game-by-game", "schedule", "highs/lows", "stats-leader"]):
            continue

        rows = table.find_all("tr")
        if not rows:
            continue

        # Look for the subheader row containing standard basketball columns
        header_row = None
        for r in rows[:4]:
            txts = [c.get_text(strip=True).upper() for c in r.find_all(["th", "td"])]
            # Must have basketball season headers
            if ("PLAYER" in txts or "NAME" in txts) and ("MIN" in txts or "AVG" in txts or "PTS" in txts):
                if not any(k in txts for k in ["OPPONENT", "DATE", "RESULT", "SCORE", "W/L"]):
                    header_row = r
                    break

        if not header_row:
            continue

        header_cols = [c.get_text(strip=True).upper() for c in header_row.find_all(["th", "td"])]

        # Map column positions by index
        col_map: Dict[str, int] = {}
        saw_first_avg = False

        for idx, col in enumerate(header_cols):
            c = col.strip().upper()
            if c in ("#", "NO", "NO."):
                col_map["number"] = idx
            elif c in ("PLAYER", "NAME"):
                col_map["name"] = idx
            elif c == "MIN" and "min" not in col_map:
                col_map["min"] = idx
            elif c in ("AVG", "PPG", "PTS/G"):
                if not saw_first_avg:
                    # In Sidearm basketball, MINUTES has an AVG column first (min per game)
                    # and SCORING has an AVG column second (pts per game)
                    if "min" in col_map and col_map["min"] == idx - 1:
                        col_map["min_avg"] = idx
                    else:
                        col_map["avg"] = idx
                    saw_first_avg = True
                else:
                    col_map["avg"] = idx
            elif c in ("FG%", "FGPCT"):
                col_map["fg_pct"] = idx
            elif c in ("3PT%", "3P%", "3FG%"):
                col_map["three_pt_pct"] = idx
            elif c in ("FT%", "FTPCT"):
                col_map["ft_pct"] = idx
            elif c in ("TOT", "REB", "RPG", "REB/G"):
                col_map["tot_reb"] = idx
            elif c in ("AST", "APG"):
                col_map["ast"] = idx
            elif c in ("TO", "TOPG", "TURNOVERS"):
                col_map["to"] = idx
            elif c in ("STL", "SPG"):
                col_map["stl"] = idx
            elif c in ("BLK", "BPG"):
                col_map["blk"] = idx

        for row in rows:
            if row == header_row:
                continue

            cells = row.find_all(["td", "th"])
            if not cells or len(cells) < 4:
                continue

            row_texts = [td.get_text(strip=True) for td in cells]

            # Player name extraction
            raw_name = ""
            raw_num = ""

            name_link = row.find("a", href=re.compile(r"roster/[^/]+/\d+", re.I))
            if name_link:
                raw_name = name_link.get_text(strip=True)
            elif "name" in col_map and col_map["name"] < len(row_texts):
                raw_name = row_texts[col_map["name"]]
            elif len(row_texts) > 1 and not row_texts[1].replace(".", "").isdigit():
                raw_name = row_texts[1]

            c_name = clean_name(raw_name)
            if not is_valid_player_row(c_name):
                continue

            # Jersey Number
            if "number" in col_map and col_map["number"] < len(row_texts):
                raw_num = row_texts[col_map["number"]]
            elif row_texts[0].isdigit() or row_texts[0] in ("00", "0"):
                raw_num = row_texts[0]

            c_num = clean_number(raw_num)

            def get_stat(key: str) -> str:
                if key in col_map and col_map[key] < len(row_texts):
                    v = row_texts[col_map[key]].strip()
                    if v.lower() in DISCARD_EXACT_NAMES or v == "View Bio":
                        return ""
                    return v
                return ""

            scoring_avg = get_stat("avg")
            min_val = get_stat("min_avg") or get_stat("min")

            players.append({
                "name": c_name,
                "number": c_num,
                "avg": scoring_avg,
                "fg_pct": get_stat("fg_pct"),
                "three_pt_pct": get_stat("three_pt_pct"),
                "ft_pct": get_stat("ft_pct"),
                "tot_reb": get_stat("tot_reb"),
                "ast": get_stat("ast"),
                "to": get_stat("to"),
                "stl": get_stat("stl"),
                "blk": get_stat("blk"),
                "min": min_val
            })

        if players:
            break

    return players


def scrape_team(team_cfg: Dict[str, str]) -> Dict[str, Any]:
    """Scrapes season stats & roster for a single team and cleanly pairs them."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    logger.info(f"Processing {team_name}...")

    # 1. Fetch Roster
    roster_lookup = scrape_roster(team_cfg["roster_url"])
    logger.info(f"  Found {len(roster_lookup)} roster entries for {team_name}")

    # 2. Fetch Stats page
    stats_html = fetch_url(team_cfg["stats_url"])
    stats_players = []

    if stats_html:
        stats_players = parse_html_table_stats(stats_html)
        if not stats_players:
            stats_players = parse_nuxt_json_stats(stats_html)

    logger.info(f"  Parsed {len(stats_players)} season player stat entries for {team_name}")

    merged_players = []
    seen_names = set()

    for sp in stats_players:
        name = sp.get("name", "")
        if not name or name.lower() in seen_names or not is_valid_player_row(name):
            continue

        seen_names.add(name.lower())

        # Cross-reference with roster for validated Pos and Year
        r_info = roster_lookup.get(name.lower())
        if not r_info and sp.get("number"):
            r_info = roster_lookup.get(f"#{sp['number']}")

        final_name = r_info["name"] if (r_info and r_info.get("name")) else name
        final_number = sp.get("number") or (r_info.get("number") if r_info else "")
        final_pos = r_info.get("position", "") if r_info else ""
        final_year = r_info.get("year", "") if r_info else ""

        merged_players.append({
            "name": final_name,
            "number": final_number,
            "position": final_pos,
            "year": final_year,
            "avg": sp.get("avg", ""),
            "fg_pct": sp.get("fg_pct", ""),
            "three_pt_pct": sp.get("three_pt_pct", ""),
            "ft_pct": sp.get("ft_pct", ""),
            "tot_reb": sp.get("tot_reb", ""),
            "ast": sp.get("ast", ""),
            "to": sp.get("to", ""),
            "stl": sp.get("stl", ""),
            "blk": sp.get("blk", ""),
            "min": sp.get("min", "")
        })

    # Include remaining roster players (who have not accumulated stats yet)
    for key, r_info in roster_lookup.items():
        if key.startswith("#"):
            continue
        pname = r_info["name"]
        if pname.lower() not in seen_names and is_valid_player_row(pname):
            seen_names.add(pname.lower())
            merged_players.append({
                "name": pname,
                "number": r_info.get("number", ""),
                "position": r_info.get("position", ""),
                "year": r_info.get("year", ""),
                "avg": "",
                "fg_pct": "",
                "three_pt_pct": "",
                "ft_pct": "",
                "tot_reb": "",
                "ast": "",
                "to": "",
                "stl": "",
                "blk": "",
                "min": ""
            })

    return {
        "team": team_name,
        "slug": slug,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "players": merged_players
    }


def main():
    os.makedirs("docs", exist_ok=True)
    all_teams_data = []

    for team_cfg in TEAMS_CONFIG:
        team_data = scrape_team(team_cfg)
        all_teams_data.append(team_data)

        slug = team_data["slug"]
        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)

        time.sleep(1.5)

    for dest in ["all_teams.json", os.path.join("docs", "all_teams.json")]:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(all_teams_data, f, indent=2)

    logger.info("Successfully updated all Summit League basketball stats!")


if __name__ == "__main__":
    main()
