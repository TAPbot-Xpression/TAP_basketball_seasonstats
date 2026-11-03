"""
scrape_basketball.py
Unified Summit League Basketball player season stats and roster scraper (Men's & Women's).

Features:
  - Generates individual team JSON files (<slug>.json and <slug>_women.json in root & docs/).
  - Old Sidearm HTML tables: Targets <section id="individual-overall"> to extract ALL 9 stats
    (AVG, FG%, 3PT%, FT%, TOT, AST, TO, STL, BLK) using exact data-label matching.
  - New Sidearm Nuxt JSON: Supports all property aliases across Nuxt Sidearm versions.
  - Normalizes jersey numbers (removes leading zeros: '05' -> '5', '00' -> '0').
  - Extracts Position (G/F) and Academic Year (FR, SO, JR, SR, GR, R-*).
  - Robust multi-tier roster matching: Exact match -> Jersey fallback -> Suffix-agnostic ->
    Last-name + number correlation -> Fuzzy string distance matching (difflib).
"""

import difflib
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

# ── Summit League Men's Basketball Configuration ──────────────────────────────
MENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city",
        "stats_url": "https://kcroos.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://kcroos.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota",
        "stats_url": "https://fightinghawks.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://fightinghawks.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state",
        "stats_url": "https://gobison.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://gobison.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "Omaha",
        "slug": "omaha",
        "stats_url": "https://omahamavs.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://omahamavs.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts",
        "stats_url": "https://oruathletics.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://oruathletics.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota",
        "stats_url": "https://goyotes.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://goyotes.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state",
        "stats_url": "https://gojacks.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://gojacks.com/sports/mens-basketball/roster/2026-27",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas",
        "stats_url": "https://tommiesports.com/sports/mbball/stats/2026-27",
        "roster_url": "https://tommiesports.com/sports/mbball/roster/2026-27",
    },
]

# ── Summit League Women's Basketball Configuration ────────────────────────────
WOMENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city_women",
        "stats_url": "https://kcroos.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://kcroos.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota_women",
        "stats_url": "https://fightinghawks.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://fightinghawks.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state_women",
        "stats_url": "https://gobison.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://gobison.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "Omaha",
        "slug": "omaha_women",
        "stats_url": "https://omahamavs.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://omahamavs.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts_women",
        "stats_url": "https://oruathletics.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://oruathletics.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota_women",
        "stats_url": "https://goyotes.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://goyotes.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state_women",
        "stats_url": "https://gojacks.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://gojacks.com/sports/womens-basketball/roster/2026-27",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas_women",
        "stats_url": "https://tommiesports.com/sports/wbball/stats/2026-27",
        "roster_url": "https://tommiesports.com/sports/wbball/roster/2026-27",
    },
]

DISCARD_EXACT_TOKENS = {
    "ft%", "blk", "ast", "tot", "avg", "pts", "off", "def", "min", "stl",
    "fg%", "3pt%", "3p%", "gp", "gs", "pct", "reb", "player", "no.",
    "total", "totals", "team", "opponent", "opponents", "view bio", "bio",
    "team tm team", "teamtmteam", "tm", "overall", "conference", "image",
    "full name", "name", "scoring", "averages", "minutes", "fg", "3pt", "ft",
    "rebounds", "player name", "title", "yr.", "bio link", "statistic",
    "high", "opponent(s)", "opp", "technical fouls", "deadball rebounds",
    "//", "date", "score", "mar", "unassigned"
}

STAFF_KEYWORDS = [
    "coach", "trainer", "director", "coordinator", "manager", "athletic",
    "operations", "strength", "conditioning", "physician", "assistant",
    "communications", "compliance", "academic", "marketing"
]


def fetch_url(url: str) -> Optional[str]:
    """Fetch URL with custom headers and timeout handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def clean_name(raw_name: str) -> str:
    """Normalizes player names to standard 'Firstname Lastname'."""
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").replace("Image", "").strip()
    text = re.sub(r"['\"]+", "", text).strip()
    if "@" in text or not text:
        return ""

    # Remove jersey tags like #00 or inline numbers with hash
    text = re.sub(r"#\d{1,2}\b", " ", text)

    # Detect concatenated repeat patterns: 'Hudgens, Trent02Hudgens, Trent'
    dup_m = re.search(r"^(.*?)(?:\d{1,2})?\1$", text)
    if dup_m and len(dup_m.group(1)) > 3:
        text = dup_m.group(1)

    text = text.strip().rstrip(",").strip()

    if "," in text:
        parts = [p.strip() for p in text.split(",", 1)]
        p1 = re.sub(r"\b\d{1,2}\b", "", parts[0]).strip()
        p2 = re.sub(r"\b\d{1,2}\b", "", parts[1]).strip() if len(parts) > 1 else ""

        p1_words = p1.split()
        p2_words = p2.split()

        if len(p1_words) >= 2 and len(p2_words) == 1 and p1_words[0].lower() == p2_words[0].lower():
            text = p1
        elif len(p2_words) >= 2 and len(p1_words) >= 1 and p2_words[-1].lower() == p1_words[-1].lower():
            text = p2
        elif p1.lower() == p2.lower():
            text = p1
        elif p1 and p2:
            text = f"{p2} {p1}"
        else:
            text = p2 or p1

    text = re.sub(r"\b\d{1,2}\b", "", text)
    text = " ".join(text.split()).strip()

    words = text.split()
    half = len(words) // 2
    if len(words) >= 4 and half * 2 == len(words) and words[:half] == words[half:]:
        text = " ".join(words[:half])

    return text


def clean_number(raw_num: Any) -> str:
    """Extracts jersey number and removes leading zeros ('05' -> '5', '00' -> '0')."""
    if raw_num is None:
        return ""
    text = str(raw_num).strip().replace("#", "")
    m = re.match(r"^(\d{1,2})$", text)
    if not m:
        return ""
    return str(int(m.group(1)))


def normalize_position(pos_str: str) -> str:
    """Normalizes basketball positions strictly to G (Guard) or F (Forward)."""
    if not pos_str:
        return ""
    p = pos_str.upper().strip()
    if "GUARD" in p or p in ("G", "G/F", "PG", "SG"):
        return "G"
    if "FORWARD" in p or "CENTER" in p or p in ("F", "C", "F/C", "SF", "PF"):
        return "F"
    if re.search(r"\bG\b", p):
        return "G"
    if re.search(r"\bF\b", p):
        return "F"
    return ""


def normalize_year(yr_str: str) -> str:
    """Standardizes academic class standings (FR, SO, JR, SR, GR, R-*)."""
    if not yr_str:
        return ""
    y = yr_str.upper().strip()
    is_rs = "R-" in y or "RS" in y or "REDSHIRT" in y

    if "5TH" in y or "GRADUATE" in y or "GR" in y or "GRAD" in y:
        return "GR"
    if "SENIOR" in y or "SR" in y or "SR." in y:
        return "R-SR" if is_rs else "SR"
    if "JUNIOR" in y or "JR" in y or "JR." in y:
        return "R-JR" if is_rs else "JR"
    if "SOPHOMORE" in y or "SO" in y or "SO." in y:
        return "R-SO" if is_rs else "SO"
    if "FRESHMAN" in y or "FR" in y or "FR." in y:
        return "R-FR" if is_rs else "FR"
    return ""


def is_valid_player_name(name: str) -> bool:
    """Validates that a string represents an actual basketball player name."""
    if not name or len(name.strip()) < 2:
        return False

    raw_low = name.strip().lower()
    condensed = re.sub(r"[\s\-_]+", "", raw_low)

    if raw_low in DISCARD_EXACT_TOKENS or condensed in DISCARD_EXACT_TOKENS:
        return False
    if any(tok in condensed for tok in ["teamtm", "teamteam", "total", "opponent", "opponents", "gamebygame", "comparison"]):
        return False
    if re.match(r"^(\.\d+|\d+(\.\d+)?|\d{1,2}/\d{1,2}/\d{2,4})$", raw_low):
        return False
    if re.search(r"\b(vs|at|\d+-\d+)\b", raw_low):
        return False
    if any(staff in raw_low for staff in STAFF_KEYWORDS):
        return False
    if "/" in raw_low and any(st in raw_low for st in ["minn", "wis", "iowa", "neb", "calif", "tex"]):
        return False
    if raw_low.startswith("//") or raw_low == "/" or raw_low == "null":
        return False

    return True


def strip_suffixes(name: str) -> str:
    """Removes common suffixes (Jr., III, etc.) and punctuation for comparison."""
    cleaned = re.sub(r"\b(jr\.?|sr\.?|iii|iv|ii)\b", "", name.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def find_roster_entry(
    name: str,
    number: str,
    roster_lookup: Dict[str, Dict[str, str]]
) -> Optional[Dict[str, str]]:
    """
    Robust multi-tier lookup to match a stats player against roster entries:
      1. Exact normalized name match
      2. Jersey number fallback (#number)
      3. Suffix-agnostic exact match
      4. Matching last name + matching jersey number
      5. Fuzzy matching via difflib sequence similarity
    """
    if not roster_lookup:
        return None

    raw_low = name.lower().strip()

    # Tier 1: Exact name match
    if raw_low in roster_lookup:
        return roster_lookup[raw_low]

    # Tier 2: Exact jersey number match
    if number and f"#{number}" in roster_lookup:
        return roster_lookup[f"#{number}"]

    # Tier 3: Suffix-agnostic match
    base_name = strip_suffixes(raw_low)
    for r_key, r_info in roster_lookup.items():
        if r_key.startswith("#"):
            continue
        if strip_suffixes(r_key) == base_name:
            return r_info

    # Tier 4: Last name + Number correlation
    name_parts = raw_low.split()
    if name_parts:
        last_name = name_parts[-1]
        for r_key, r_info in roster_lookup.items():
            if r_key.startswith("#"):
                continue
            r_parts = r_key.split()
            if r_parts and r_parts[-1] == last_name:
                if not number or r_info.get("number") == number:
                    return r_info

    # Tier 5: Fuzzy name matching
    roster_player_names = [k for k in roster_lookup.keys() if not k.startswith("#")]
    close_matches = difflib.get_close_matches(raw_low, roster_player_names, n=1, cutoff=0.72)
    if close_matches:
        return roster_lookup[close_matches[0]]

    return None


def scrape_roster(roster_url: str) -> Dict[str, Dict[str, str]]:
    """Scrapes team roster for Position (G/F) and Academic Year."""
    html = fetch_url(roster_url)
    roster_lookup: Dict[str, Dict[str, str]] = {}
    if not html:
        return roster_lookup

    soup = BeautifulSoup(html, "html.parser")

    for staff in soup.find_all(class_=re.compile(r"staff|coaches|coach", re.I)):
        staff.decompose()
    for hdr in soup.find_all(["h2", "h3", "h4"], string=re.compile(r"coaching staff|coaches", re.I)):
        parent = hdr.find_parent(["section", "div"])
        if parent:
            parent.decompose()

    player_items = soup.find_all(class_=re.compile(
        r"roster-player|roster__item|sidearm-roster-player|s-person-details", re.I))

    for p in player_items:
        name_el = p.find(class_=re.compile(r"name|player-name", re.I))
        raw_name = name_el.get_text(separator=" ", strip=True) if name_el else ""
        c_name = clean_name(raw_name)
        if not is_valid_player_name(c_name):
            continue

        num_el = p.find(class_=re.compile(r"jersey|number|player-number", re.I))
        c_num = clean_number(num_el.get_text(strip=True) if num_el else "")

        pos_el = p.find(class_=re.compile(r"position|pos", re.I))
        c_pos = normalize_position(pos_el.get_text(strip=True) if pos_el else "")

        yr_el = p.find(class_=re.compile(r"academic-year|year|class", re.I))
        c_yr = normalize_year(yr_el.get_text(strip=True) if yr_el else "")

        info = {"name": c_name, "number": c_num, "position": c_pos, "year": c_yr}
        roster_lookup[c_name.lower()] = info
        if c_num != "":
            roster_lookup[f"#{c_num}"] = info

    if not roster_lookup:
        for row in soup.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cols) < 3:
                continue
            num = pos = yr = name_cand = ""
            for col in cols:
                if not num and re.match(r"^\d{1,2}$", col):
                    num = clean_number(col)
                if not pos and normalize_position(col):
                    pos = normalize_position(col)
                if not yr and normalize_year(col):
                    yr = normalize_year(col)
                c_clean = clean_name(col)
                if not name_cand and is_valid_player_name(c_clean) and not normalize_position(col) and not normalize_year(col):
                    name_cand = c_clean

            if name_cand and is_valid_player_name(name_cand):
                info = {"name": name_cand, "number": num, "position": pos, "year": yr}
                roster_lookup[name_cand.lower()] = info
                if num != "":
                    roster_lookup[f"#{num}"] = info

    return roster_lookup


def parse_old_style_html_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parses Sidearm HTML tables specifically from <section id="individual-overall"> (or full cumulative table).
    Extracts all 9 stats via exact data-label attributes:
      - FG%, 3PT%, FT%
      - PTS or AVG (Scoring PPG)
      - REB or TOT (Total Rebounds)
      - AST, TO, STL, BLK
    """
    players: List[Dict[str, Any]] = []

    target_sections = soup.find_all("section", id=re.compile(r"individual-overall|individual-scoring|individual-averages", re.I))
    candidate_tables = []
    if target_sections:
        for sec in target_sections:
            candidate_tables.extend(sec.find_all("table"))
    else:
        candidate_tables = soup.find_all("table")

    for table in candidate_tables:
        parent_tags = [p for p in table.parents if p.name in ["div", "section"]]
        parent_ids = " ".join(p.get("id", "") for p in parent_tags).lower()
        parent_classes = " ".join(" ".join(p.get("class", [])) for p in parent_tags).lower()
        parent_text = " ".join(p.get_text() for p in parent_tags[:2])[:300].lower()

        if any(bad in parent_ids for bad in ["game-comparison", "game-by-game", "game-highs"]):
            continue
        if any(bad in parent_classes for bad in ["game-comparison", "game-by-game"]):
            continue
        if any(bad in parent_text for bad in ["game-by-game", "schedule", "highs", "comparison"]):
            continue

        caption = table.find("caption")
        if caption and any(bad in caption.get_text().lower() for bad in ["comparison", "game by game", "game highs"]):
            continue

        thead = table.find("thead")
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        if not rows:
            continue

        if thead:
            thead_text = thead.get_text().upper()
            if any(bad in thead_text for bad in ["OPPONENT", "DATE", "RESULT", "SCORE", "MAR"]):
                continue

        table_players: List[Dict[str, Any]] = []

        for row in rows:
            if row.find("th") and not row.find("td"):
                continue
            if "footer_row" in row.get("class", []):
                continue

            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            cell_texts = [c.get_text(strip=True) for c in cells]

            label_map: Dict[str, str] = {}
            for cell in cells:
                lbl = cell.get("data-label", "").strip().upper()
                if lbl:
                    label_map[lbl] = cell.get_text(strip=True)

            raw_name = ""
            name_a = row.find("a", href=re.compile(r"roster", re.I)) or row.find("a", attrs={"data-player-id": True})
            if name_a:
                raw_name = name_a.get_text(separator=" ", strip=True)
            elif "NAME" in label_map:
                raw_name = label_map["NAME"]
            elif "PLAYER" in label_map:
                raw_name = label_map["PLAYER"]
            elif len(cell_texts) > 1:
                raw_name = cell_texts[1]

            c_name = clean_name(raw_name)
            if not is_valid_player_name(c_name):
                continue

            raw_num = ""
            jersey_el = row.find(class_=re.compile(r"jersey|number", re.I)) or row.find("td", class_=re.compile(r"hide-on-medium-down", re.I))
            if jersey_el and re.match(r"^\d{1,2}$", jersey_el.get_text(strip=True)):
                raw_num = jersey_el.get_text(strip=True)
            elif cell_texts[0].isdigit() or cell_texts[0] in ("00", "0"):
                raw_num = cell_texts[0]
            c_num = clean_number(raw_num)

            def get_stat(data_labels: List[str]) -> str:
                for lbl in data_labels:
                    if lbl in label_map:
                        v = label_map[lbl].strip()
                        if v and v.lower() not in DISCARD_EXACT_TOKENS and "view bio" not in v.lower():
                            return v
                return ""

            scoring_avg  = get_stat(["AVG", "PTS/G", "PPG", "PTS_AVG", "POINTS/G", "PTS"])
            fg_pct       = get_stat(["FG%", "FG PCT", "PCT"])
            three_pt_pct = get_stat(["3PT%", "3FG PCT", "3P%", "3FG%", "3PT PCT"])
            ft_pct       = get_stat(["FT%", "FT PCT", "FTPCT"])
            tot_reb      = get_stat(["REB", "TOT", "TOTAL", "TOTAL REBOUNDS", "TOT REB", "REBOUNDS", "REB/G"])
            ast          = get_stat(["AST", "APG", "ASSISTS", "AST/G"])
            to           = get_stat(["TO", "TOPG", "TURNOVERS", "TO/G"])
            stl          = get_stat(["STL", "SPG", "STEALS", "STL/G"])
            blk          = get_stat(["BLK", "BPG", "BLOCKS", "BLK/G"])

            if not any([scoring_avg, fg_pct, ft_pct, tot_reb]):
                continue

            table_players.append({
                "name": c_name,
                "number": c_num,
                "avg": scoring_avg,
                "fg_pct": fg_pct,
                "three_pt_pct": three_pt_pct,
                "ft_pct": ft_pct,
                "tot_reb": tot_reb,
                "ast": ast,
                "to": to,
                "stl": stl,
                "blk": blk,
            })

        if len(table_players) >= 5:
            players = table_players
            break

    return players


def parse_nuxt_data_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses Sidearm Nuxt JSON payloads for modern websites.
    Supports all stat field alias variations across Sidearm Nuxt versions.
    """
    players = []
    patterns = [
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
        r"__NUXT_DATA__\s*=\s*(\[.*?\]);",
        r"window\.__NUXT__\s*=\s*(.*?);\s*</script>",
    ]

    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
            if not isinstance(data, list):
                continue

            def resolve(val: Any) -> str:
                if isinstance(val, int) and 0 <= val < len(data):
                    target = data[val]
                    if isinstance(target, (str, int, float)):
                        return str(target)
                return str(val) if val is not None else ""

            def find_stat(item: dict, keys: List[str]) -> str:
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        res = resolve(v).strip()
                        if res and res != "None" and res.lower() not in DISCARD_EXACT_TOKENS:
                            return res
                return ""

            for item in data:
                if not isinstance(item, dict):
                    continue
                if "opponent" in item or "winOrLoss" in item or "boxscoreUrl" in item:
                    continue
                if item.get("isAFooterStat") is True:
                    continue

                raw_name = (item.get("playerName") or item.get("nameFromStats") or
                            item.get("name") or item.get("fullName") or item.get("displayName"))
                if raw_name is None:
                    continue

                c_name = clean_name(resolve(raw_name))
                if not is_valid_player_name(c_name):
                    continue

                c_num = clean_number(resolve(
                    item.get("playerUniform") or item.get("jersey") or item.get("number") or item.get("uniform")))

                ppg = find_stat(item, [
                    "pointsPerGame", "pts_avg", "ppg", "scoringAvg", "ptsPerGame",
                    "points_per_game", "ptsAvg", "scoring_avg", "pts"
                ])
                fg_pct = find_stat(item, [
                    "fieldGoalsPercentage", "fg_pct", "fgPct", "fieldGoalPct",
                    "field_goal_percentage", "fgPercentage"
                ])
                three_pct = find_stat(item, [
                    "threePointFieldGoalsPercentage", "three_pt_pct", "threePtPct",
                    "threePointPercentage", "three_point_percentage", "threePct"
                ])
                ft_pct = find_stat(item, [
                    "freeThrowsPercentage", "ft_pct", "ftPct", "freeThrowPct",
                    "free_throw_percentage", "ftPercentage"
                ])
                tot_reb = find_stat(item, [
                    "rebounds", "totalRebounds", "tot_reb", "reb_avg",
                    "reboundsPerGame", "rebPerGame", "rebounds_per_game"
                ])
                ast = find_stat(item, [
                    "assists", "ast", "ast_avg", "assistsPerGame", "astPerGame"
                ])
                to = find_stat(item, [
                    "turnovers", "to", "to_avg", "turnoversPerGame", "toPerGame"
                ])
                stl = find_stat(item, [
                    "steals", "stl", "stl_avg", "stealsPerGame", "stlPerGame"
                ])
                blk = find_stat(item, [
                    "blocks", "blk", "blk_avg", "blocksPerGame", "blkPerGame"
                ])

                if not any([ppg, fg_pct, ft_pct, tot_reb, ast]):
                    continue

                players.append({
                    "name": c_name,
                    "number": c_num,
                    "avg": ppg,
                    "fg_pct": fg_pct,
                    "three_pt_pct": three_pct,
                    "ft_pct": ft_pct,
                    "tot_reb": tot_reb,
                    "ast": ast,
                    "to": to,
                    "stl": stl,
                    "blk": blk,
                })
        except Exception:
            continue

        if len(players) >= 5:
            break

    return players


def scrape_team(team_cfg: Dict[str, str], gender: str = "men") -> Dict[str, Any]:
    """Scrapes season cumulative stats & roster for a single Summit League team."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    gender_label = "Women's" if gender == "women" else "Men's"
    logger.info(f"Processing {team_name} ({gender_label})...")

    # 1. Fetch Roster
    roster_lookup = scrape_roster(team_cfg["roster_url"])
    logger.info(f"  Loaded {len(roster_lookup)} roster entries for {team_name}")

    # 2. Fetch Stats page (HTML table first, then Nuxt JSON fallback)
    stats_html = fetch_url(team_cfg["stats_url"])
    stats_players: List[Dict[str, Any]] = []

    if stats_html:
        soup = BeautifulSoup(stats_html, "html.parser")
        stats_players = parse_old_style_html_table(soup)
        if not stats_players:
            stats_players = parse_nuxt_data_stats(stats_html)

    logger.info(f"  Parsed {len(stats_players)} player stat lines for {team_name}")

    # 3. Merge stats with roster info using multi-tier matcher
    merged_players = []
    seen_names: set = set()

    for sp in stats_players:
        name = sp.get("name", "")
        if not name or name.lower() in seen_names or not is_valid_player_name(name):
            continue
        seen_names.add(name.lower())

        r_info = find_roster_entry(name, sp.get("number", ""), roster_lookup)

        final_name   = r_info["name"] if (r_info and r_info.get("name")) else name
        final_number = sp.get("number") or (r_info.get("number") if r_info else "")
        final_pos    = r_info.get("position", "") if r_info else ""
        final_year   = r_info.get("year", "") if r_info else ""

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
        })

    return {
        "team": team_name,
        "slug": slug,
        "gender": gender,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "players": merged_players,
    }


def process_league(teams_config: List[Dict[str, str]], gender: str):
    """Processes all teams in a conference division and writes individual JSON files."""
    for team_cfg in teams_config:
        team_data = scrape_team(team_cfg, gender=gender)
        slug = team_data["slug"]

        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)

        time.sleep(1.5)


def main():
    os.makedirs("docs", exist_ok=True)

    # 1. Process Men's Basketball
    logger.info("=== Starting Men's Basketball Scraping ===")
    process_league(MENS_TEAMS_CONFIG, gender="men")

    # 2. Process Women's Basketball
    logger.info("=== Starting Women's Basketball Scraping ===")
    process_league(WOMENS_TEAMS_CONFIG, gender="women")

    logger.info("Done — Individual Summit League basketball stats JSONs updated!")


if __name__ == "__main__":
    main()
