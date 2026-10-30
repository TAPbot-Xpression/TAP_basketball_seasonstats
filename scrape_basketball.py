"""
scrape_basketball.py
Scrapes Summit League Men's Basketball season stats and rosters.
Outputs individual team JSON files as well as docs/all_teams.json.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
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
        "Chrome/122.0.0.0 Safari/537.36"
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

# Unwanted strings that signal non-player rows (headers, footers, stat words)
HEADER_FOOTER_TOKENS = {
    "ft%", "blk", "ast", "tot", "avg", "pts", "off", "def", "min", "stl",
    "to", "fg%", "3pt%", "3p%", "gp", "gs", "pct", "reb", "player", "no.",
    "total", "totals", "team", "opponent", "opponents", "view bio", "bio",
    "team tm team", "tm"
}


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
    Cleans raw names from stats or roster tables.
    Handles duplicate repetition: 'Greyson 03 Uelmen, Greyson Uelmen' -> 'Greyson Uelmen'
    Handles 'Lastname, Firstname' -> 'Firstname Lastname'
    Strips embedded jersey numbers, 'View Bio', heights, weights, hometowns.
    """
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").strip()

    # If comma exists, check if it's repeated 'First ## Last, First Last' or standard 'Last, First'
    if "," in text:
        parts = text.split(",")
        if len(parts) == 2:
            p1 = parts[0].strip()
            p2 = parts[1].strip()
            # If right side is just Clean 'First Last' and left side contains numbers
            p1_no_digits = re.sub(r"\b\d{1,2}\b", "", p1).strip()
            p1_cleaned = " ".join(p1_no_digits.split())
            if p1_cleaned == p2:
                text = p2
            elif len(p2.split()) == 1 and len(p1.split()) == 1:
                # Standard 'Lastname, Firstname' -> 'Firstname Lastname'
                text = f"{p2} {p1}"
            else:
                text = p2 if len(p2) >= len(p1) else p1

    # Remove jersey numbers embedded between names e.g., 'Greyson 03 Uelmen' -> 'Greyson Uelmen'
    text = re.sub(r"\b\d{1,2}\b", "", text)

    # Normalize whitespace
    text = " ".join(text.split()).strip()
    return text


def clean_number(raw_num: str) -> str:
    """Cleans jersey number, stripping '#' or extra text."""
    if not raw_num:
        return ""
    m = re.search(r"\b(\d{1,2})\b", str(raw_num))
    return m.group(1) if m else ""


def normalize_position(pos_str: str) -> str:
    """
    Ensures position only returns G (Guard) or F (Forward), or combo G/F.
    Ignores heights, weights, and hometown text.
    """
    if not pos_str:
        return ""
    pos_upper = pos_str.upper().strip()

    # Match G, F, G/F, F/C, C, Guard, Forward
    if "GUARD" in pos_upper or "G/F" in pos_upper or pos_upper == "G":
        return "G"
    if "FORWARD" in pos_upper or "F/C" in pos_upper or "CENTER" in pos_upper or pos_upper in ("F", "C"):
        return "F"
    
    # Direct short checks
    if re.search(r"\bG\b", pos_upper):
        return "G"
    if re.search(r"\bF\b", pos_upper):
        return "F"

    return ""


def normalize_year(yr_str: str) -> str:
    """
    Standardizes basketball class year to:
    FR, SO, JR, SR, 5TH, GR, or Redshirt variants (R-FR, R-SO, R-JR, R-SR).
    """
    if not yr_str:
        return ""
    y = yr_str.upper().strip()

    # Check for Redshirt prefix
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
    """Validates if row represents a real player and not a header/stat row."""
    if not name or len(name.strip()) < 2:
        return False
    
    low = name.strip().lower()
    
    # Check if name is just a stat header or summary keyword
    if low in HEADER_FOOTER_TOKENS:
        return False
    
    # Discard if name starts with decimal (e.g. .750, .000) or pure digits
    if re.match(r"^(\.\d+|\d+(\.\d+)?)", low):
        return False

    # Discard 'Team', 'Opponent', 'Totals'
    if any(tok in low for tok in ["team tm", "opponent", "total", "view bio"]):
        return False

    return True


def scrape_roster(roster_url: str) -> Dict[str, Dict[str, str]]:
    """
    Scrapes the roster site to build a lookup by cleaned player name and jersey number.
    Extracts validated: Name, Jersey, Position (G or F), and Year (FR, SO, JR, SR, GR, etc.)
    Ignores weight, height (e.g. 6' 1"), and hometown text.
    """
    html = fetch_url(roster_url)
    roster_lookup: Dict[str, Dict[str, str]] = {}
    if not html:
        return roster_lookup

    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: Sidearm roster cards/items (.sidearm-roster-player, .roster-card)
    players = soup.find_all(class_=re.compile(r"roster-player|roster__item|sidearm-roster-player", re.I))

    for p in players:
        # Extract name
        name_el = p.find(class_=re.compile(r"name|player-name", re.I))
        raw_name = name_el.get_text(separator=" ", strip=True) if name_el else ""
        c_name = clean_name(raw_name)

        # Extract number
        num_el = p.find(class_=re.compile(r"jersey|number|player-number", re.I))
        raw_num = num_el.get_text(strip=True) if num_el else ""
        c_num = clean_number(raw_num)

        # Extract position (G / F)
        pos_el = p.find(class_=re.compile(r"position|pos", re.I))
        raw_pos = pos_el.get_text(strip=True) if pos_el else ""
        c_pos = normalize_position(raw_pos)

        # Extract year
        yr_el = p.find(class_=re.compile(r"academic-year|year|class", re.I))
        raw_yr = yr_el.get_text(strip=True) if yr_el else ""
        c_yr = normalize_year(raw_yr)

        if c_name and is_valid_player_row(c_name):
            info = {
                "name": c_name,
                "number": c_num,
                "position": c_pos,
                "year": c_yr
            }
            roster_lookup[c_name.lower()] = info
            if c_num:
                roster_lookup[f"#{c_num}"] = info

    # Strategy 2: Sidearm Table format (<table class="sidearm-table">)
    if not roster_lookup:
        for row in soup.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) >= 3:
                raw_text = " ".join(cols)
                # Check for year and position tokens
                pos = ""
                yr = ""
                num = ""
                for col in cols:
                    if not num and col.isdigit():
                        num = clean_number(col)
                    if not pos:
                        pos = normalize_position(col)
                    if not yr:
                        yr = normalize_year(col)

                # Name is usually one of the first non-numeric columns
                name_cand = ""
                for col in cols:
                    c_clean = clean_name(col)
                    if is_valid_player_row(c_clean) and not normalize_position(col) and not normalize_year(col):
                        name_cand = c_clean
                        break

                if name_cand:
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
    """Attempts to extract stats from Sidearm Nuxt JSON blob."""
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
            # Search dictionary structures inside array for basketball keys
            for item in data:
                if isinstance(item, dict) and "pts" in item and "min" in item:
                    raw_name = item.get("name") or item.get("player") or item.get("playerName") or ""
                    c_name = clean_name(str(raw_name))
                    if not is_valid_player_row(c_name):
                        continue

                    players.append({
                        "name": c_name,
                        "number": clean_number(str(item.get("jersey") or item.get("number") or "")),
                        "avg": str(item.get("pts_avg") or item.get("ppg") or item.get("avg") or ""),
                        "fg_pct": str(item.get("fg_pct") or item.get("fgPct") or ""),
                        "three_pt_pct": str(item.get("three_pt_pct") or item.get("3pt_pct") or item.get("threePtPct") or ""),
                        "ft_pct": str(item.get("ft_pct") or item.get("ftPct") or ""),
                        "tot_reb": str(item.get("reb_avg") or item.get("rpg") or item.get("tot_reb") or ""),
                        "ast": str(item.get("ast_avg") or item.get("apg") or item.get("ast") or ""),
                        "to": str(item.get("to_avg") or item.get("to") or item.get("turnovers") or ""),
                        "stl": str(item.get("stl_avg") or item.get("stl") or ""),
                        "blk": str(item.get("blk_avg") or item.get("blk") or ""),
                        "min": str(item.get("min_avg") or item.get("mpg") or item.get("min") or "")
                    })
        except Exception:
            continue

        if players:
            break

    return players


def parse_html_table_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses stats from Sidearm HTML statistical tables.
    Explicitly ignores header / footer labels (TOT, FT%, BLK, AST, etc.).
    Extracts AVG, FG%, 3PT%, FT%, TOT, AST, TO, STL, BLK, MIN.
    """
    soup = BeautifulSoup(html, "html.parser")
    players = []

    # Find basketball season stats table (typically includes GP, GS, PTS, AVG, etc.)
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cols = [th.get_text(strip=True).upper() for th in rows[0].find_all(["th", "td"])]
        if not any(k in header_cols for k in ["PTS", "AVG", "PPG", "3PT", "FG%", "MIN"]):
            continue

        # Map header column positions
        col_map = {}
        for idx, col in enumerate(header_cols):
            c_clean = col.strip().upper()
            if c_clean in ("PLAYER", "NAME"):
                col_map["name"] = idx
            elif c_clean in ("#", "NO", "NO.", "JERSEY"):
                col_map["number"] = idx
            elif c_clean in ("AVG", "PPG", "PTS/G"):
                col_map["avg"] = idx
            elif c_clean in ("FG%", "FGPCT"):
                col_map["fg_pct"] = idx
            elif c_clean in ("3PT%", "3P%", "3FG%"):
                col_map["three_pt_pct"] = idx
            elif c_clean in ("FT%", "FTPCT"):
                col_map["ft_pct"] = idx
            elif c_clean in ("TOT", "REB", "RPG", "REB/G"):
                col_map["tot_reb"] = idx
            elif c_clean in ("AST", "APG"):
                col_map["ast"] = idx
            elif c_clean in ("TO", "TOPG", "TURNOVERS"):
                col_map["to"] = idx
            elif c_clean in ("STL", "SPG"):
                col_map["stl"] = idx
            elif c_clean in ("BLK", "BPG"):
                col_map["blk"] = idx
            elif c_clean in ("MIN", "MPG", "MIN/G"):
                col_map["min"] = idx

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            row_texts = [td.get_text(strip=True) for td in cells]
            
            # Check row text for headers or footers to ignore
            first_cell = row_texts[0] if row_texts else ""
            if not is_valid_player_row(first_cell) and len(row_texts) > 1:
                # Test second cell if first is jersey number
                if not is_valid_player_row(row_texts[1]):
                    continue

            # Extract name and number
            raw_name = ""
            raw_num = ""

            if "name" in col_map and col_map["name"] < len(row_texts):
                raw_name = row_texts[col_map["name"]]
            elif len(row_texts) > 1:
                raw_name = row_texts[1] if row_texts[0].isdigit() else row_texts[0]

            if "number" in col_map and col_map["number"] < len(row_texts):
                raw_num = row_texts[col_map["number"]]
            elif row_texts and row_texts[0].isdigit():
                raw_num = row_texts[0]

            c_name = clean_name(raw_name)
            if not is_valid_player_row(c_name):
                continue

            # Extract stat columns safely
            def get_val(key: str) -> str:
                if key in col_map and col_map[key] < len(row_texts):
                    v = row_texts[col_map[key]]
                    # Ensure it's not a misplaced header tag
                    return "" if v.upper() in HEADER_FOOTER_TOKENS else v
                return ""

            players.append({
                "name": c_name,
                "number": clean_number(raw_num),
                "avg": get_val("avg"),
                "fg_pct": get_val("fg_pct"),
                "three_pt_pct": get_val("three_pt_pct"),
                "ft_pct": get_val("ft_pct"),
                "tot_reb": get_val("tot_reb"),
                "ast": get_val("ast"),
                "to": get_val("to"),
                "stl": get_val("stl"),
                "blk": get_val("blk"),
                "min": get_val("min")
            })

    return players


def scrape_team(team_cfg: Dict[str, str]) -> Dict[str, Any]:
    """Scrapes both stats & roster for a single team and merges them."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    logger.info(f"Processing {team_name}...")

    # 1. Fetch Roster for verification, Position (G/F), and Year (FR, SO, JR, SR, GR)
    roster_lookup = scrape_roster(team_cfg["roster_url"])
    logger.info(f"  Found {len(roster_lookup)} roster entries for {team_name}")

    # 2. Fetch Stats page
    stats_html = fetch_url(team_cfg["stats_url"])
    stats_players = []

    if stats_html:
        # Try Nuxt JSON first
        stats_players = parse_nuxt_json_stats(stats_html)
        # Fall back to HTML table parser
        if not stats_players:
            stats_players = parse_html_table_stats(stats_html)

    logger.info(f"  Parsed {len(stats_players)} stat entries for {team_name}")

    merged_players = []
    seen_names = set()

    # 3. Pull player name & number from Stats first, then check with Roster
    for sp in stats_players:
        name = sp.get("name", "")
        if not name or name.lower() in seen_names:
            continue

        seen_names.add(name.lower())

        # Cross-reference with roster
        r_info = roster_lookup.get(name.lower())
        if not r_info and sp.get("number"):
            r_info = roster_lookup.get(f"#{sp['number']}")

        # Verified fields
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

    # If stats table missed any roster players, add them with blank stats
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

        # Write individual team JSON to root and docs/
        slug = team_data["slug"]
        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)

        time.sleep(1.5)  # Polite crawling delay

    # Write combined all_teams.json to root and docs/
    for dest in ["all_teams.json", os.path.join("docs", "all_teams.json")]:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(all_teams_data, f, indent=2)

    logger.info("Successfully updated all Summit League basketball stats!")


if __name__ == "__main__":
    main()
