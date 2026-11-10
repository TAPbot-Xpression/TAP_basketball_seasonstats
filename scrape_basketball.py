"""
scrape_basketball.py
Unified Summit League Basketball player season stats and roster scraper (Men's & Women's).

Features:
  - Playwright integration: Uses headless Chromium with realistic headers/viewport to bypass
    Sidearm bot challenges and wait for full DOM hydration.
  - Print Roster URLs: Uses the exact print-view URLs supplied for each team (men's and women's).
  - Print-Table Parser: Parses tabular and stacked Sidearm print layouts.
  - Old Sidearm HTML tables: Targets <section id="individual-overall"> and matches exact
    data-label attributes (AVG, FG%, 3PT%, FT%, REB/TOT, AST, TO, STL, BLK) based on live
    Sidearm table markup (North Dakota, Oral Roberts, South Dakota).
  - New Sidearm Nuxt JSON: Supports all property aliases across Nuxt Sidearm versions for stats.
  - Normalizes jersey numbers (removes leading zeros: '05' -> '5', '00' -> '0').
  - Normalizes Position (G/F) and Academic Year (FR, SO, JR, SR, GR, R-*).
  - Robust multi-tier roster matching: Exact match -> Jersey fallback -> Suffix-agnostic ->
    Last-name + number correlation -> Fuzzy string distance matching (difflib).
  - Generates individual team JSON files (<slug>.json in root & docs/).
"""

import difflib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Summit League Men's Basketball Configuration ──────────────────────────────
MENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city",
        "stats_url": "https://kcroos.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://kcroos.com/sports/mens-basketball/roster/print/2026-27",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota",
        "stats_url": "https://fightinghawks.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://fightinghawks.com/sports/mens-basketball/roster?print=true",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state",
        "stats_url": "https://gobison.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://gobison.com/sports/mens-basketball/roster/print",
    },
    {
        "name": "Omaha",
        "slug": "omaha",
        "stats_url": "https://omahamavs.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://omahamavs.com/sports/mens-basketball/roster/print",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts",
        "stats_url": "https://oruathletics.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://oruathletics.com/sports/mens-basketball/roster?print=true",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota",
        "stats_url": "https://goyotes.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://goyotes.com/sports/mens-basketball/roster?print=true",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state",
        "stats_url": "https://gojacks.com/sports/mens-basketball/stats/2026-27",
        "roster_url": "https://gojacks.com/sports/mens-basketball/roster/print",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas",
        "stats_url": "https://tommiesports.com/sports/mbball/stats/2026-27",
        "roster_url": "https://tommiesports.com/sports/mbball/roster/print",
    },
]

# ── Summit League Women's Basketball Configuration ────────────────────────────
WOMENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city_women",
        "stats_url": "https://kcroos.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://kcroos.com/sports/womens-basketball/roster/print/2026-27",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota_women",
        "stats_url": "https://fightinghawks.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://fightinghawks.com/sports/womens-basketball/roster?print=true",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state_women",
        "stats_url": "https://gobison.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://gobison.com/sports/womens-basketball/roster/print/2026-27",
    },
    {
        "name": "Omaha",
        "slug": "omaha_women",
        "stats_url": "https://omahamavs.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://omahamavs.com/sports/womens-basketball/roster/print/2026-27",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts_women",
        "stats_url": "https://oruathletics.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://oruathletics.com/sports/womens-basketball/roster/2026-27?print=true",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota_women",
        "stats_url": "https://goyotes.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://goyotes.com/sports/womens-basketball/roster?print=true",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state_women",
        "stats_url": "https://gojacks.com/sports/womens-basketball/stats/2026-27",
        "roster_url": "https://gojacks.com/sports/womens-basketball/roster/print",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas_women",
        "stats_url": "https://tommiesports.com/sports/wbball/stats/2026-27",
        "roster_url": "https://tommiesports.com/sports/wbball/roster/print/2026-27",
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
    "//", "date", "score", "mar", "unassigned", "pos.", "ht.", "wt.", "cl.",
    "hometown", "high school", "previous school", "major"
}

STAFF_KEYWORDS = [
    "coach", "trainer", "director", "coordinator", "manager", "athletic",
    "operations", "strength", "conditioning", "physician", "assistant",
    "communications", "compliance", "academic", "marketing"
]


# ── Playwright Page Fetcher ───────────────────────────────────────────────────

def fetch_page_html(page: Page, url: str) -> Optional[str]:
    """Fetches URL content using an active Playwright browser page with network wait."""
    try:
        logger.info(f"Navigating to {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        time.sleep(1.0)
        return page.content()
    except Exception as e:
        logger.error(f"Failed to fetch {url} via Playwright: {e}")
        return None


# ── Cleaning and Normalization Helpers ─────────────────────────────────────────

def clean_name(raw_name: str) -> str:
    """Normalizes player names to standard 'Firstname Lastname'."""
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").replace("Image", "").strip()
    text = re.sub(r"['\"]+", "", text).strip()
    if "@" in text or not text:
        return ""

    text = re.sub(r"#\d{1,2}\b", " ", text)

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
    """
    Normalizes basketball positions strictly to G (Guard) or F (Forward).
    Uses whole-cell matching so names/hometowns are never mistaken for positions.
    """
    if not pos_str:
        return ""
    p = pos_str.upper().strip().rstrip(".")
    if re.fullmatch(r"(G|PG|SG|GUARD)(\s*/\s*\w+)?", p):
        return "G"
    if re.fullmatch(r"(F|C|SF|PF|FORWARD|CENTER)(\s*/\s*\w+)?", p):
        return "F"
    return ""


def normalize_year(yr_str: str) -> str:
    """
    Standardizes academic class standings (FR, SO, JR, SR, GR, R-*).
    Uses whole-cell matching (not substring) so names like 'Grant', 'Jason',
    'Madson' or 'Franks' are never mistaken for a class year.
    """
    if not yr_str:
        return ""

    y = yr_str.upper().strip()
    y = y.replace("REDSHIRT", "R-").replace("RS-", "R-")
    y = re.sub(r"[.\s]+", "", y)

    is_rs = y.startswith("R-")
    base = y[2:] if is_rs else y

    if base in ("GR", "GRAD", "GRADUATE", "5TH", "5THYEAR", "5"):
        return "GR"
    if base in ("SR", "SENIOR"):
        return "R-SR" if is_rs else "SR"
    if base in ("JR", "JUNIOR"):
        return "R-JR" if is_rs else "JR"
    if base in ("SO", "SOPHOMORE"):
        return "R-SO" if is_rs else "SO"
    if base in ("FR", "FRESHMAN"):
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
    """Multi-tier lookup to match a stats player against roster entries."""
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


# ── Roster & Stats Parsers ────────────────────────────────────────────────────

def parse_print_roster(html: str) -> Dict[str, Dict[str, str]]:
    """
    Parses Sidearm Print roster pages (tables or stacked card blocks).
    Extracts player Name, Jersey Number, Position (G/F), and Academic Year.
    """
    roster_lookup: Dict[str, Dict[str, str]] = {}
    soup = BeautifulSoup(html, "html.parser")

    # Decompose staff sections
    for staff in soup.find_all(class_=re.compile(r"staff|coaches|coach", re.I)):
        staff.decompose()
    for hdr in soup.find_all(["h2", "h3", "h4"], string=re.compile(r"coaching staff|coaches", re.I)):
        parent = hdr.find_parent(["section", "div", "table"])
        if parent:
            parent.decompose()

    # Method A: Structured HTML Table Rows
    for row in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue

        num = ""
        pos = ""
        yr = ""
        name_cand = ""

        for col in cells:
            if not num and re.match(r"^\d{1,2}$", col):
                num = clean_number(col)
                continue
            if not pos and normalize_position(col):
                pos = normalize_position(col)
                continue
            if not yr and normalize_year(col):
                yr = normalize_year(col)
                continue

            c_clean = clean_name(col)
            if not name_cand and is_valid_player_name(c_clean):
                name_cand = c_clean

        if name_cand and is_valid_player_name(name_cand):
            info = {"name": name_cand, "number": num, "position": pos, "year": yr}
            roster_lookup[name_cand.lower()] = info
            if num != "":
                roster_lookup[f"#{num}"] = info

    # Method B: Text/Card-Based Block Parsing
    if not roster_lookup:
        body_text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r"^\d{1,2}$", line):
                p_num = clean_number(line)
                p_name = ""
                p_pos = ""
                p_yr = ""

                j = i + 1
                limit = min(len(lines), i + 8)
                while j < limit:
                    nxt = lines[j]
                    if re.match(r"^\d{1,2}$", nxt) and j > i + 1:
                        break

                    if not p_pos and normalize_position(nxt):
                        p_pos = normalize_position(nxt)
                    elif not p_yr and normalize_year(nxt):
                        p_yr = normalize_year(nxt)
                    elif not p_name and is_valid_player_name(clean_name(nxt)):
                        p_name = clean_name(nxt)

                    j += 1

                if p_name and is_valid_player_name(p_name):
                    info = {"name": p_name, "number": p_num, "position": p_pos, "year": p_yr}
                    roster_lookup[p_name.lower()] = info
                    if p_num != "":
                        roster_lookup[f"#{p_num}"] = info
                i = j - 1
            i += 1

    return roster_lookup


def parse_old_style_html_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parses Sidearm HTML stats tables from <section id="individual-overall"> (or full cumulative table).
    Extracts all 9 stats via exact data-label attributes matching live Sidearm responsive markup.
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

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        if not rows:
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

            # Build exact data-label dictionary for this row
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
                """Returns the first non-empty value matching any data-label candidate."""
                for lbl in data_labels:
                    if lbl in label_map:
                        v = label_map[lbl].strip()
                        # Only reject obvious non-stat values like 'View Bio' or empty strings
                        if v and "view bio" not in v.lower() and v.lower() != "null":
                            return v
                return ""

            # Explicit mapping to Sidearm HTML table data-labels
            scoring_avg  = get_stat(["AVG", "PTS/G", "PPG", "PTS_AVG", "POINTS/G", "PTS"])
            fg_pct       = get_stat(["FG%", "FG PCT", "PCT"])
            three_pt_pct = get_stat(["3PT%", "3FG PCT", "3P%", "3FG%", "3PT PCT"])
            ft_pct       = get_stat(["FT%", "FT PCT", "FTPCT"])
            tot_reb      = get_stat(["REB", "TOT", "TOTAL", "TOTAL REBOUNDS", "TOT REB", "REBOUNDS", "REB/G"])
            ast          = get_stat(["AST", "APG", "ASSISTS", "AST/G"])
            to           = get_stat(["TO", "TOPG", "TURNOVERS", "TO/G"])
            stl          = get_stat(["STL", "SPG", "STEALS", "STL/G"])
            blk          = get_stat(["BLK", "BPG", "BLOCKS", "BLK/G"])

            # Verify that at least basic stats were extracted
            if not any([scoring_avg, fg_pct, ft_pct, tot_reb, ast]):
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
    """Parses Sidearm Nuxt JSON payloads for stats on modern layouts."""
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

                ppg = find_stat(item, ["pointsPerGame", "pts_avg", "ppg", "scoringAvg", "ptsPerGame", "points_per_game", "ptsAvg", "scoring_avg", "pts"])
                fg_pct = find_stat(item, ["fieldGoalsPercentage", "fg_pct", "fgPct", "fieldGoalPct", "field_goal_percentage", "fgPercentage"])
                three_pct = find_stat(item, ["threePointFieldGoalsPercentage", "three_pt_pct", "threePtPct", "threePointPercentage", "three_point_percentage", "threePct"])
                ft_pct = find_stat(item, ["freeThrowsPercentage", "ft_pct", "ftPct", "freeThrowPct", "free_throw_percentage", "ftPercentage"])
                tot_reb = find_stat(item, ["rebounds", "totalRebounds", "tot_reb", "reb_avg", "reboundsPerGame", "rebPerGame", "rebounds_per_game"])
                ast = find_stat(item, ["assists", "ast", "ast_avg", "assistsPerGame", "astPerGame"])
                to = find_stat(item, ["turnovers", "to", "to_avg", "turnoversPerGame", "toPerGame"])
                stl = find_stat(item, ["steals", "stl", "stl_avg", "stealsPerGame", "stlPerGame"])
                blk = find_stat(item, ["blocks", "blk", "blk_avg", "blocksPerGame", "blkPerGame"])

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


# ── Execution Logic ───────────────────────────────────────────────────────────

def scrape_team(page: Page, team_cfg: Dict[str, str], gender: str = "men") -> Dict[str, Any]:
    """Scrapes season cumulative stats & print roster for a single Summit League team."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    gender_label = "Women's" if gender == "women" else "Men's"
    logger.info(f"Processing {team_name} ({gender_label})...")

    # 1. Fetch Print Roster
    roster_html = fetch_page_html(page, team_cfg["roster_url"])
    roster_lookup = parse_print_roster(roster_html) if roster_html else {}
    logger.info(f"  Loaded {len(roster_lookup)} roster entries for {team_name}")

    # 2. Fetch Stats Page
    stats_html = fetch_page_html(page, team_cfg["stats_url"])
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


def process_league(page: Page, teams_config: List[Dict[str, str]], gender: str):
    """Processes all teams in a conference division and writes JSON output files."""
    for team_cfg in teams_config:
        team_data = scrape_team(page, team_cfg, gender=gender)
        slug = team_data["slug"]

        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)

        time.sleep(1.0)


def main():
    os.makedirs("docs", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )
        page = context.new_page()

        # 1. Process Men's Basketball
        logger.info("=== Starting Men's Basketball Scraping ===")
        process_league(page, MENS_TEAMS_CONFIG, gender="men")

        # 2. Process Women's Basketball
        logger.info("=== Starting Women's Basketball Scraping ===")
        process_league(page, WOMENS_TEAMS_CONFIG, gender="women")

        browser.close()

    logger.info("Done — Individual Summit League basketball stats and rosters JSONs updated!")


if __name__ == "__main__":
    main()
