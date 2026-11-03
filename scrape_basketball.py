"""
scrape_basketball.py
Unified Summit League Basketball player season stats and roster scraper (Men's & Women's).

Fixes in this version:
  - Removed "to" from DISCARD_EXACT_TOKENS so Turnovers are no longer filtered out.
  - Restored __NUXT_DATA__ regex patterns that were silently stripped in prior version.
  - Nuxt roster parsing now correctly resolves position/year from embedded JSON.
  - Table scoring logic retained: picks the table with the most complete stat coverage.
  - Leading zero removal on jersey numbers ('05' -> '5', '00' -> '0').

Output stats per player:
- AVG (Scoring PPG)
- FG%
- 3PT%
- FT%
- TOT (Total Rebounds)
- AST (Assists)
- TO (Turnovers)
- STL (Steals)
- BLK (Blocks)

Roster info:
- Name ("Firstname Lastname")
- Jersey Number (normalized, no leading zero)
- Position (G or F)
- Year (FR, SO, JR, SR, GR, R-*)
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

# ── Summit League Men's Basketball Configuration ──────────────────────────────
MENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city",
        "stats_url": "https://kcroos.com/sports/mens-basketball/stats",
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
        "stats_url": "https://gobison.com/sports/mens-basketball/stats",
        "roster_url": "https://gobison.com/sports/mens-basketball/roster",
    },
    {
        "name": "Omaha",
        "slug": "omaha",
        "stats_url": "https://omahamavs.com/sports/mens-basketball/stats",
        "roster_url": "https://omahamavs.com/sports/mens-basketball/roster",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts",
        "stats_url": "https://oruathletics.com/sports/mens-basketball/stats?path=mbball",
        "roster_url": "https://oruathletics.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota",
        "stats_url": "https://goyotes.com/sports/mens-basketball/stats",
        "roster_url": "https://goyotes.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state",
        "stats_url": "https://gojacks.com/sports/mens-basketball/stats",
        "roster_url": "https://gojacks.com/sports/mens-basketball/roster",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas",
        "stats_url": "https://tommiesports.com/sports/mbball/stats",
        "roster_url": "https://tommiesports.com/sports/mbball/roster",
    },
]

# ── Summit League Women's Basketball Configuration ────────────────────────────
WOMENS_TEAMS_CONFIG = [
    {
        "name": "Kansas City",
        "slug": "kansas_city_women",
        "stats_url": "https://kcroos.com/sports/womens-basketball/stats",
        "roster_url": "https://kcroos.com/sports/womens-basketball/roster",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota_women",
        "stats_url": "https://fightinghawks.com/sports/womens-basketball/stats",
        "roster_url": "https://fightinghawks.com/sports/womens-basketball/roster",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state_women",
        "stats_url": "https://gobison.com/sports/womens-basketball/stats",
        "roster_url": "https://gobison.com/sports/womens-basketball/roster",
    },
    {
        "name": "Omaha",
        "slug": "omaha_women",
        "stats_url": "https://omahamavs.com/sports/womens-basketball/stats",
        "roster_url": "https://omahamavs.com/sports/womens-basketball/roster",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts_women",
        "stats_url": "https://oruathletics.com/sports/womens-basketball/stats?path=wbball",
        "roster_url": "https://oruathletics.com/sports/womens-basketball/roster",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota_women",
        "stats_url": "https://goyotes.com/sports/womens-basketball/stats",
        "roster_url": "https://goyotes.com/sports/womens-basketball/roster",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state_women",
        "stats_url": "https://gojacks.com/sports/womens-basketball/stats",
        "roster_url": "https://gojacks.com/sports/womens-basketball/roster",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas_women",
        "stats_url": "https://tommiesports.com/sports/wbball/stats",
        "roster_url": "https://tommiesports.com/sports/wbball/roster",
    },
]

# FIX: "to" removed from this set — it was silently discarding all Turnover values.
# Stat column header labels (used as data-label values) are filtered separately in get_stat().
DISCARD_EXACT_TOKENS = {
    "ft%", "blk", "ast", "tot", "avg", "pts", "off", "def", "min", "stl",
    "fg%", "3pt%", "3p%", "gp", "gs", "pct", "reb", "player", "no.",
    "total", "totals", "team", "opponent", "opponents", "view bio", "bio",
    "team tm team", "teamtmteam", "tm", "overall", "conference", "image",
    "full name", "name", "scoring", "averages", "minutes", "fg", "3pt", "ft",
    "rebounds", "player name", "title", "yr.", "bio link", "statistic",
    "high", "opponent(s)", "opp", "technical fouls", "deadball rebounds"
}

STAFF_KEYWORDS = [
    "coach", "trainer", "director", "coordinator", "manager", "athletic",
    "operations", "strength", "conditioning", "physician", "assistant",
    "communications", "compliance", "academic", "marketing"
]

# Standard Sidearm cumulative stats table column offsets (0-indexed):
# 0:NO  1:PLAYER  2:GP  3:GS  4:MIN  5:AVG(MIN)
# 6:FGM  7:FGA  8:FG%  -- wait, scoring section:
# Sidearm layout: 0:NO 1:PLAYER 2:GP 3:GS 4:MIN 5:PTS 6:AVG 7:FGM 8:FGA 9:FG% 10:3FGM 11:3FGA 12:3FG% 13:FTM 14:FTA 15:FT% 16:OFF 17:DEF 18:TOT 19:PF 20:AST 21:TO 22:STL 23:BLK
OLD_STYLE_COL_OFFSETS = {
    "avg": 6,
    "fg_pct": 9,
    "three_pt_pct": 12,
    "ft_pct": 15,
    "tot_reb": 18,
    "ast": 20,
    "to": 21,
    "stl": 22,
    "blk": 23,
}


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
    """Normalizes basketball positions to G (Guard) or F (Forward/Center)."""
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
    if "SENIOR" in y or "SR" in y:
        return "R-SR" if is_rs else "SR"
    if "JUNIOR" in y or "JR" in y:
        return "R-JR" if is_rs else "JR"
    if "SOPHOMORE" in y or "SO" in y:
        return "R-SO" if is_rs else "SO"
    if "FRESHMAN" in y or "FR" in y:
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
    if any(tok in condensed for tok in ["teamtm", "teamteam", "total", "opponent", "opponents"]):
        return False
    if re.match(r"^(\.\d+|\d+(\.\d+)?|\d{1,2}/\d{1,2}/\d{2,4})$", raw_low):
        return False
    if re.search(r"\b(vs|at|\d+-\d+)\b", raw_low):
        return False
    if any(staff in raw_low for staff in STAFF_KEYWORDS):
        return False
    if "/" in raw_low and any(st in raw_low for st in ["minn", "wis", "iowa", "neb", "calif", "tex"]):
        return False

    return True


# ── Nuxt JSON script tag pattern (defined once, used in both roster & stats) ──
# FIX: Previously this regex was silently stripped to r'' causing phantom "//" matches.
NUXT_DATA_SCRIPT_RE = re.compile(
    r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE
)
NUXT_DATA_VAR_RE = re.compile(r"__NUXT_DATA__\s*=\s*(\[.*?\]);", re.DOTALL)
NUXT_WINDOW_RE = re.compile(r"window\.__NUXT__\s*=\s*(.*?);\s*</script>", re.DOTALL)


def _extract_nuxt_json(html: str) -> Optional[list]:
    """Attempts to extract and parse the __NUXT_DATA__ JSON array from page HTML."""
    for pattern in [NUXT_DATA_SCRIPT_RE, NUXT_DATA_VAR_RE, NUXT_WINDOW_RE]:
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list) and len(data) > 10:
                return data
        except Exception:
            continue
    return None


def scrape_roster(roster_url: str) -> Dict[str, Dict[str, str]]:
    """
    Multi-tier roster scraper for Position (G/F) and Academic Year.
      Tier 1: Sidearm __NUXT_DATA__ JSON payload (modern sites)
      Tier 2: Sidearm DOM roster card elements
      Tier 3: Traditional HTML roster tables
    """
    html = fetch_url(roster_url)
    roster_lookup: Dict[str, Dict[str, str]] = {}
    if not html:
        return roster_lookup

    # ── Tier 1: Nuxt JSON ─────────────────────────────────────────────────────
    data = _extract_nuxt_json(html)
    if data:
        def resolve_val(v: Any) -> str:
            if isinstance(v, int) and 0 <= v < len(data):
                t = data[v]
                if isinstance(t, (str, int, float)):
                    return str(t)
            return str(v) if v is not None else ""

        for item in data:
            if not isinstance(item, dict):
                continue
            # Skip non-player objects
            if any(k in item for k in ["opponent", "winOrLoss", "boxscoreUrl", "menuItems"]):
                continue

            first = resolve_val(item.get("firstName") or item.get("first_name") or "")
            last  = resolve_val(item.get("lastName") or item.get("last_name") or "")
            full  = resolve_val(item.get("name") or item.get("fullName") or item.get("displayName") or "")
            raw   = f"{first} {last}".strip() if (first and last and first != "None" and last != "None") else full
            cand_name = clean_name(raw)

            if not is_valid_player_name(cand_name):
                continue

            num = clean_number(resolve_val(
                item.get("jersey") or item.get("uniform") or item.get("playerUniform") or ""))
            pos = normalize_position(resolve_val(
                item.get("position") or item.get("positionShort") or item.get("posShort") or ""))
            yr  = normalize_year(resolve_val(
                item.get("year") or item.get("academicYear") or item.get("class") or
                item.get("classStandings") or item.get("eligibility") or ""))

            info = {"name": cand_name, "number": num, "position": pos, "year": yr}
            roster_lookup[cand_name.lower()] = info
            if num:
                roster_lookup[f"#{num}"] = info

    if roster_lookup:
        logger.debug(f"  Roster via Nuxt JSON: {len(roster_lookup)} entries")
        return roster_lookup

    # ── Tier 2: Sidearm DOM Cards ─────────────────────────────────────────────
    soup = BeautifulSoup(html, "html.parser")

    for staff in soup.find_all(class_=re.compile(r"staff|coaches|coach", re.I)):
        staff.decompose()
    for hdr in soup.find_all(["h2", "h3", "h4"], string=re.compile(r"coaching staff|coaches", re.I)):
        parent = hdr.find_parent(["section", "div"])
        if parent:
            parent.decompose()

    player_items = soup.find_all(class_=re.compile(
        r"roster-player|roster__item|sidearm-roster-player|s-person-details|s-person-card", re.I))

    for p in player_items:
        name_el = p.find(class_=re.compile(
            r"name|player-name|s-person-details__personal|s-person-card__title", re.I))
        raw_name = name_el.get_text(separator=" ", strip=True) if name_el else ""
        c_name = clean_name(raw_name)
        if not is_valid_player_name(c_name):
            continue

        num_el = p.find(class_=re.compile(
            r"jersey|number|player-number|s-person-details__bio-stats-item--jersey", re.I))
        c_num = clean_number(num_el.get_text(strip=True) if num_el else "")

        pos_el = p.find(class_=re.compile(
            r"position|pos|s-person-details__bio-stats-item--position", re.I))
        c_pos = normalize_position(pos_el.get_text(strip=True) if pos_el else "")

        yr_el = p.find(class_=re.compile(
            r"academic-year|year|class|s-person-details__bio-stats-item--year", re.I))
        c_yr = normalize_year(yr_el.get_text(strip=True) if yr_el else "")

        info = {"name": c_name, "number": c_num, "position": c_pos, "year": c_yr}
        roster_lookup[c_name.lower()] = info
        if c_num:
            roster_lookup[f"#{c_num}"] = info

    if roster_lookup:
        logger.debug(f"  Roster via DOM cards: {len(roster_lookup)} entries")
        return roster_lookup

    # ── Tier 3: HTML Roster Tables ────────────────────────────────────────────
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
            if (not name_cand and is_valid_player_name(c_clean)
                    and not normalize_position(col) and not normalize_year(col)):
                name_cand = c_clean

        if name_cand and is_valid_player_name(name_cand):
            info = {"name": name_cand, "number": num, "position": pos, "year": yr}
            roster_lookup[name_cand.lower()] = info
            if num:
                roster_lookup[f"#{num}"] = info

    logger.debug(f"  Roster via HTML table: {len(roster_lookup)} entries")
    return roster_lookup


def _build_col_map_from_headers(header_cols: List[str]) -> Dict[str, int]:
    """Maps stat keys to column indices from flattened header labels."""
    col_map: Dict[str, int] = {}
    avg_count = 0

    for idx, col in enumerate(header_cols):
        c = col.strip().upper()
        if c in ("#", "NO", "NO.", "UNIFORM"):
            col_map.setdefault("number", idx)
        elif c in ("PLAYER", "NAME", "PLAYER NAME"):
            col_map.setdefault("name", idx)
        elif c in ("AVG", "PPG", "PTS/G", "PTS_AVG", "SCORING AVG"):
            avg_count += 1
            # Sidearm tables have two AVG columns: MIN/G avg and PTS avg.
            # The second AVG encountered is the scoring average.
            if avg_count == 2:
                col_map["avg"] = idx
            else:
                col_map.setdefault("avg", idx)
        elif c in ("FG%", "FGPCT", "FG PCT"):
            col_map.setdefault("fg_pct", idx)
        elif c in ("3PT%", "3P%", "3FG%", "3FG PCT", "3PT PCT"):
            col_map.setdefault("three_pt_pct", idx)
        elif c in ("FT%", "FTPCT", "FT PCT"):
            col_map.setdefault("ft_pct", idx)
        elif c in ("TOT", "TOTAL", "REB", "REBOUNDS", "TOT REB") and "tot_reb" not in col_map:
            col_map["tot_reb"] = idx
        elif c in ("AST", "APG", "ASSISTS"):
            col_map.setdefault("ast", idx)
        elif c in ("TO", "TOPG", "TURNOVERS", "T/O"):
            col_map.setdefault("to", idx)
        elif c in ("STL", "SPG", "STEALS"):
            col_map.setdefault("stl", idx)
        elif c in ("BLK", "BPG", "BLOCKS"):
            col_map.setdefault("blk", idx)

    return col_map


def parse_old_style_html_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parses Sidearm HTML cumulative stats tables.
    Scores all candidate tables and picks the one with the most complete stat coverage
    (most players with TOT, AST, TO, STL, BLK populated).
    """
    best_players: List[Dict[str, Any]] = []
    best_score = -1

    for table in soup.find_all("table"):
        parent_text = " ".join(
            p.get_text() for p in table.parents if p.name in ["div", "section"]
        )[:400].lower()
        if any(bad in parent_text for bad in ["game-by-game", "schedule", "highs"]):
            continue

        thead = table.find("thead")
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        if not rows:
            continue

        # Flatten multi-tier colspan headers
        flat_headers: List[str] = []
        if thead:
            for hr in thead.find_all("tr"):
                for cell in hr.find_all(["th", "td"]):
                    colspan = int(cell.get("colspan", 1))
                    label = cell.get_text(strip=True).upper()
                    flat_headers.extend([label] * colspan)

        col_map = _build_col_map_from_headers(flat_headers)
        table_players: List[Dict[str, Any]] = []

        for row in rows:
            if row.find("th") and not row.find("td"):
                continue

            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            cell_texts = [c.get_text(strip=True) for c in cells]

            # Build data-label map for responsive table layouts
            label_map: Dict[str, str] = {}
            for cell in cells:
                lbl = cell.get("data-label", "").strip().upper()
                if lbl:
                    label_map[lbl] = cell.get_text(strip=True)

            # ── Resolve player name ──────────────────────────────────────────
            raw_name = ""
            name_a = row.find("a", href=re.compile(r"roster", re.I))
            if name_a:
                raw_name = name_a.get_text(separator=" ", strip=True)
            elif "NAME" in label_map:
                raw_name = label_map["NAME"]
            elif "PLAYER" in label_map:
                raw_name = label_map["PLAYER"]
            elif "name" in col_map and col_map["name"] < len(cell_texts):
                raw_name = cell_texts[col_map["name"]]
            elif len(cell_texts) > 1:
                raw_name = cell_texts[1]

            c_name = clean_name(raw_name)
            if not is_valid_player_name(c_name):
                continue

            # ── Resolve jersey number ────────────────────────────────────────
            raw_num = ""
            jersey_el = row.find(class_=re.compile(r"jersey|number", re.I))
            if jersey_el:
                raw_num = jersey_el.get_text(strip=True)
            elif "number" in col_map and col_map["number"] < len(cell_texts):
                raw_num = cell_texts[col_map["number"]]
            elif re.match(r"^\d{1,2}$", cell_texts[0]):
                raw_num = cell_texts[0]
            c_num = clean_number(raw_num)

            # ── Stat resolver: data-label > col_map > fixed offset ───────────
            def get_stat(key: str, data_labels: List[str]) -> str:
                # 1. Try data-label attributes (responsive layout)
                for lbl in data_labels:
                    if lbl in label_map:
                        v = label_map[lbl].strip()
                        if v and v.lower() not in DISCARD_EXACT_TOKENS and "view bio" not in v.lower():
                            return v
                # 2. Try header-mapped column index
                if key in col_map and col_map[key] < len(cell_texts):
                    v = cell_texts[col_map[key]].strip()
                    if v and v.lower() not in DISCARD_EXACT_TOKENS and "view bio" not in v.lower():
                        return v
                # 3. Fall back to fixed Sidearm column offset
                offset = OLD_STYLE_COL_OFFSETS.get(key)
                if offset is not None and offset < len(cell_texts):
                    v = cell_texts[offset].strip()
                    if v and v.lower() not in DISCARD_EXACT_TOKENS and "view bio" not in v.lower():
                        return v
                return ""

            scoring_avg  = get_stat("avg",          ["PTS/G", "PPG", "AVG", "PTS_AVG", "POINTS/G", "SCORING AVG"])
            fg_pct       = get_stat("fg_pct",        ["FG%", "FG PCT"])
            three_pt_pct = get_stat("three_pt_pct",  ["3PT%", "3FG PCT", "3P%", "3FG%", "3PT PCT"])
            ft_pct       = get_stat("ft_pct",        ["FT%", "FT PCT"])
            tot_reb      = get_stat("tot_reb",        ["TOT", "REB", "TOTAL", "TOTAL REBOUNDS", "TOT REB", "REBOUNDS"])
            ast          = get_stat("ast",            ["AST", "APG", "ASSISTS"])
            to           = get_stat("to",             ["TO", "T/O", "TOPG", "TURNOVERS"])
            stl          = get_stat("stl",            ["STL", "SPG", "STEALS"])
            blk          = get_stat("blk",            ["BLK", "BPG", "BLOCKS"])

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

        if table_players:
            # Score by total populated defensive/playmaking stats
            total_stats_found = sum(
                bool(p.get("tot_reb")) + bool(p.get("ast")) + bool(p.get("to")) +
                bool(p.get("stl")) + bool(p.get("blk")) + bool(p.get("avg"))
                for p in table_players
            )
            if total_stats_found > best_score:
                best_score = total_stats_found
                best_players = table_players

    return best_players


def parse_nuxt_data_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses modern Sidearm Nuxt / NextGen JSON payloads embedded in stats page HTML.
    FIX: Uses pre-compiled regex constants instead of inline strings that were
    silently stripped in prior versions, causing phantom '//' player entries.
    """
    players = []

    data = _extract_nuxt_json(html)
    if not data:
        return players

    def resolve(val: Any) -> str:
        if isinstance(val, int) and 0 <= val < len(data):
            target = data[val]
            if isinstance(target, (str, int, float)):
                return str(target)
        return str(val) if val is not None else ""

    for item in data:
        if not isinstance(item, dict):
            continue
        if any(k in item for k in ["opponent", "winOrLoss", "boxscoreUrl", "menuItems"]):
            continue
        if item.get("isAFooterStat") is True:
            continue

        raw_name = item.get("playerName") or item.get("nameFromStats") or item.get("name")
        if raw_name is None:
            continue

        c_name = clean_name(resolve(raw_name))
        if not is_valid_player_name(c_name):
            continue

        c_num = clean_number(resolve(
            item.get("playerUniform") or item.get("jersey") or item.get("number") or ""))

        ppg       = resolve(item.get("pointsPerGame")               or item.get("pts_avg")    or item.get("ppg")      or "")
        fg_pct    = resolve(item.get("fieldGoalsPercentage")         or item.get("fg_pct")     or item.get("fgPct")    or "")
        three_pct = resolve(item.get("threePointFieldGoalsPercentage") or item.get("three_pt_pct") or item.get("threePtPct") or "")
        ft_pct    = resolve(item.get("freeThrowsPercentage")         or item.get("ft_pct")     or item.get("ftPct")    or "")
        tot_reb   = resolve(item.get("rebounds")                     or item.get("totalRebounds") or item.get("tot_reb") or "")
        ast       = resolve(item.get("assists")                      or item.get("ast")        or "")
        to        = resolve(item.get("turnovers")                    or item.get("to")         or "")
        stl       = resolve(item.get("steals")                       or item.get("stl")        or "")
        blk       = resolve(item.get("blocks")                       or item.get("blk")        or "")

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

    return players


def scrape_team(team_cfg: Dict[str, str], gender: str = "men") -> Dict[str, Any]:
    """Scrapes season cumulative stats & roster for a single Summit League team."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    gender_label = "Women's" if gender == "women" else "Men's"
    logger.info(f"Processing {team_name} ({gender_label})...")

    roster_lookup = scrape_roster(team_cfg["roster_url"])
    logger.info(f"  Loaded {len(roster_lookup)} roster entries for {team_name}")

    stats_html = fetch_url(team_cfg["stats_url"])
    stats_players: List[Dict[str, Any]] = []

    if stats_html:
        soup = BeautifulSoup(stats_html, "html.parser")
        stats_players = parse_old_style_html_table(soup)
        if not stats_players:
            logger.info(f"  No HTML table found for {team_name}, trying Nuxt JSON...")
            stats_players = parse_nuxt_data_stats(stats_html)

    logger.info(f"  Parsed {len(stats_players)} player stat lines for {team_name}")

    merged_players = []
    seen_names: set = set()

    for sp in stats_players:
        name = sp.get("name", "")
        if not name or name.lower() in seen_names or not is_valid_player_name(name):
            continue
        seen_names.add(name.lower())

        r_info = roster_lookup.get(name.lower())
        if not r_info and sp.get("number"):
            r_info = roster_lookup.get(f"#{sp['number']}")

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


def process_league(teams_config: List[Dict[str, str]], aggregate_filename: str, gender: str):
    """Processes all teams and writes individual + aggregate JSON files."""
    all_teams_data = []

    for team_cfg in teams_config:
        team_data = scrape_team(team_cfg, gender=gender)
        all_teams_data.append(team_data)

        slug = team_data["slug"]
        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)
            logger.info(f"  Wrote {dest}")

        time.sleep(1.5)

    for dest in [aggregate_filename, os.path.join("docs", aggregate_filename)]:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(all_teams_data, f, indent=2)
        logger.info(f"  Wrote aggregate {dest}")


def main():
    os.makedirs("docs", exist_ok=True)

    logger.info("=== Starting Men's Basketball Scraping ===")
    process_league(MENS_TEAMS_CONFIG, "all_teams.json", gender="men")

    logger.info("=== Starting Women's Basketball Scraping ===")
    process_league(WOMENS_TEAMS_CONFIG, "women_teams.json", gender="women")

    logger.info("Done — Both Men's and Women's Summit League basketball stats updated!")


if __name__ == "__main__":
    main()
