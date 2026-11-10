"""
scrape_basketball.py
Unified Summit League Basketball player season stats and roster scraper (Men's & Women's).

Features:
  - High-Performance Concurrent Scraping:
      * Uses Async Playwright with an asyncio Semaphore pool (concurrency = 5).
      * Scrapes all 16 Men's and Women's teams in parallel (~20-30 seconds).
  - Position & Academic Class Standardization:
      * Supports 'G' (Guard), 'F' (Forward), and 'W' (Winger / Wing, e.g., SDSU).
      * Standardizes academic standing (FR, SO, JR, SR, GR, R-FR, R-SO, R-JR, R-SR).
      * Supports ordinal year designations (1st, 2nd, 3rd, 4th, 5th / 1st Year, etc. for NDSU).
  - Robust Nuxt & Print Roster Parser:
      * Inspects __NUXT_DATA__ on roster and stats pages to extract Position and Year
        directly from Sidearm state when HTML print tables are client-rendered.
      * Falls back to responsive HTML table and card block parsers.
  - Team & TM Discard Filtering:
      * Completely removes #TM Team, Team, Totals, Opponents, and technical foul rows.
  - Dual Output (Totals & Per-Game Averages):
      * Games Played: gp, gs, min, min_avg
      * Scoring: pts (total points), avg (PTS/G / PPG), fg_pct, three_pt_pct, ft_pct
      * Rebounding: tot_reb (season total), reb_avg (REB/G), off_reb, def_reb
      * Playmaking: ast (season total), ast_avg (AST/G), to (season total), to_avg (TO/G)
      * Defense: stl (season total), stl_avg (STL/G), blk (season total), blk_avg (BLK/G)
  - Nuxt JSON Disambiguation:
      * Disambiguates Scoring PPG vs Rebounding RPG.
      * Includes calculated fallback (Stat / GP) if only cumulative totals are present.
  - Multi-tier matching: Exact match -> Jersey fallback -> Suffix-agnostic ->
    Last-name + number correlation -> Fuzzy string distance matching (difflib).
"""

import asyncio
import difflib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 5

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
    "team tm team", "teamtmteam", "tm", "#tm", "tm team", "#tm team", "overall",
    "conference", "image", "full name", "name", "scoring", "averages", "minutes",
    "fg", "3pt", "ft", "rebounds", "player name", "title", "yr.", "bio link",
    "statistic", "high", "opponent(s)", "opp", "technical fouls", "deadball rebounds",
    "//", "date", "score", "mar", "unassigned", "pos.", "ht.", "wt.", "cl.",
    "hometown", "high school", "previous school", "major"
}

STAFF_KEYWORDS = [
    "coach", "trainer", "director", "coordinator", "manager", "athletic",
    "operations", "strength", "conditioning", "physician", "assistant",
    "communications", "compliance", "academic", "marketing"
]


# ── Async Playwright Fetcher ──────────────────────────────────────────────────

async def fetch_page_html(context: BrowserContext, url: str) -> Optional[str]:
    """Fetches URL content using an async Playwright page."""
    page: Optional[Page] = None
    try:
        page = await context.new_page()
        logger.info(f"Navigating to {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)

        # Allow fast network settling
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        content = await page.content()
        return content
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
    finally:
        if page:
            await page.close()


# ── Normalization Helpers ─────────────────────────────────────────────────────

def clean_name(raw_name: str) -> str:
    """Normalizes player names to standard 'Firstname Lastname'."""
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").replace("Image", "").strip()
    text = re.sub(r"['\"]+", "", text).strip()
    if "@" in text or not text:
        return ""

    # Remove jersey markers like #01 or #TM
    text = re.sub(r"#\d{1,2}\b", " ", text)
    text = re.sub(r"#?tm\b", " ", text, flags=re.I)

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
    if text.upper() in ("TM", "TEAM", "TOT", "TOTAL"):
        return ""
    m = re.match(r"^(\d{1,2})$", text)
    if not m:
        return ""
    return str(int(m.group(1)))


def normalize_position(pos_str: str) -> str:
    """
    Normalizes basketball positions to G (Guard), F (Forward), or W (Winger / Wing).
    """
    if not pos_str:
        return ""
    p = pos_str.upper().strip().rstrip(".")
    # Winger / Wing (e.g. SDSU)
    if re.fullmatch(r"(W|WING|WINGER)(\s*/\s*\w+)?", p):
        return "W"
    # Guard
    if re.fullmatch(r"(G|PG|SG|GUARD)(\s*/\s*\w+)?", p):
        return "G"
    # Forward / Center
    if re.fullmatch(r"(F|C|SF|PF|FORWARD|CENTER)(\s*/\s*\w+)?", p):
        return "F"
    return ""


_CLASS_MAP = {
    # Standard labels
    "FR": "FR", "FRESHMAN": "FR",
    "SO": "SO", "SOPHOMORE": "SO",
    "JR": "JR", "JUNIOR": "JR",
    "SR": "SR", "SENIOR": "SR",
    "GR": "GR", "GRAD": "GR", "GRADUATE": "GR", "GRADUATESTUDENT": "GR",
    "GRADSTUDENT": "GR", "GS": "GR",

    # Ordinal labels (NDSU: 1st, 2nd, 3rd, 4th, 5th, etc.)
    "1ST": "FR", "1STYEAR": "FR", "1": "FR", "FIRSTYEAR": "FR", "FIRST": "FR",
    "2ND": "SO", "2NDYEAR": "SO", "2": "SO", "SECONDYEAR": "SO", "SECOND": "SO",
    "3RD": "JR", "3RDYEAR": "JR", "3": "JR", "THIRDYEAR": "JR", "THIRD": "JR",
    "4TH": "SR", "4THYEAR": "SR", "4": "SR", "FOURTHYEAR": "SR", "FOURTH": "SR",
    "5TH": "GR", "5THYEAR": "GR", "5": "GR", "FIFTHYEAR": "GR", "FIFTH": "GR",
}


def normalize_year(yr_str: str) -> str:
    """
    Standardizes academic class standings (FR, SO, JR, SR, GR, R-*).
    Handles traditional, redshirt, and ordinal (1st Year, 2nd, 3rd, 4th, 5th) notations.
    """
    if not yr_str:
        return ""

    y = re.sub(r"[^A-Z0-9]", "", str(yr_str).upper())
    if not y:
        return ""

    # Direct match in map
    if y in _CLASS_MAP:
        return _CLASS_MAP[y]

    # Handle Redshirt prefixes (R-1st, RS-2nd, Redshirt Junior, etc.)
    for prefix in ("REDSHIRT", "RS", "R"):
        if y.startswith(prefix):
            remainder = y[len(prefix):]
            if remainder in _CLASS_MAP:
                base = _CLASS_MAP[remainder]
                return f"R-{base}" if base != "GR" else "GR"

    return ""


def is_valid_player_name(name: str) -> bool:
    """Validates that a string represents an actual basketball player name."""
    if not name or len(name.strip()) < 2:
        return False

    raw_low = name.strip().lower()
    condensed = re.sub(r"[\s\-_#]+", "", raw_low)

    if raw_low in DISCARD_EXACT_TOKENS or condensed in DISCARD_EXACT_TOKENS:
        return False
    if any(tok in condensed for tok in ["teamtm", "teamteam", "tmteam", "total", "opponent", "opponents", "gamebygame", "comparison"]):
        return False
    if condensed in ("team", "tm", "totals", "total"):
        return False
    if raw_low.startswith("#tm") or raw_low.startswith("tm "):
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

def parse_nuxt_roster_data(html: str) -> Dict[str, Dict[str, str]]:
    """
    Extracts roster metadata (Position, Year, Jersey, Name) from __NUXT_DATA__ payloads.
    Fixes NDSU and modern Sidearm sites where print view renders client-side.
    """
    roster_lookup: Dict[str, Dict[str, str]] = {}
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

            for item in data:
                if not isinstance(item, dict):
                    continue

                raw_name = (item.get("name") or item.get("playerName") or item.get("fullName") or
                            item.get("displayName") or item.get("nameFromStats"))
                if not raw_name:
                    continue

                c_name = clean_name(resolve(raw_name))
                if not is_valid_player_name(c_name):
                    continue

                raw_num = (item.get("uniform") or item.get("jersey") or item.get("playerUniform") or
                           item.get("number") or item.get("jerseyNumber"))
                c_num = clean_number(resolve(raw_num))

                raw_pos = (item.get("position") or item.get("positionShort") or item.get("pos") or
                           item.get("positionName") or item.get("player_position"))
                c_pos = normalize_position(resolve(raw_pos))

                raw_yr = (item.get("academicYear") or item.get("year") or item.get("class") or
                          item.get("academicClass") or item.get("classYear") or item.get("cl") or
                          item.get("yearShort") or item.get("academicYearShort") or item.get("academicStanding"))
                c_yr = normalize_year(resolve(raw_yr))

                if c_name:
                    info = {"name": c_name, "number": c_num, "position": c_pos, "year": c_yr}
                    roster_lookup[c_name.lower()] = info
                    if c_num != "":
                        roster_lookup[f"#{c_num}"] = info
        except Exception:
            continue

        if len(roster_lookup) >= 5:
            break

    return roster_lookup


def parse_print_roster(html: str) -> Dict[str, Dict[str, str]]:
    """
    Parses Sidearm Print roster pages (Nuxt JSON, responsive HTML tables, or stacked card blocks).
    Extracts player Name, Jersey Number, Position (G/F/W), and Academic Year.
    """
    # 1. Try modern Nuxt extraction first (Fixes NDSU)
    roster_lookup = parse_nuxt_roster_data(html)
    if len(roster_lookup) >= 5:
        return roster_lookup

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


def parse_nuxt_data_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses Sidearm Nuxt JSON payloads (__NUXT_DATA__) for stats on modern layouts.
    Extracts unambiguous properties and avoids duplicate HTML column collisions.
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

                # Position and Year if present in stats object
                c_pos = normalize_position(resolve(item.get("position") or item.get("pos") or item.get("positionShort")))
                c_yr  = normalize_year(resolve(
                    item.get("academicYear") or item.get("year") or item.get("class") or
                    item.get("academicClass") or item.get("classYear") or item.get("yearShort")
                ))

                gp = find_stat(item, ["gamesPlayed", "gp", "games", "gp_gs"])
                gs = find_stat(item, ["gamesStarted", "gs", "starts"])
                min_tot = find_stat(item, ["minutesPlayed", "minutes", "min", "totalMinutes"])
                min_avg = find_stat(item, ["minutesPerGame", "min_avg", "mpg", "minutes_per_game", "minPerGame", "avgMinutes"])

                pts = find_stat(item, ["points", "totalPoints", "pts"])
                ppg = find_stat(item, [
                    "pointsPerGame", "pts_avg", "ppg", "scoringAvg", "scoring_avg",
                    "ptsPerGame", "points_per_game", "ptsAvg", "pointsAverage"
                ])

                fg_pct = find_stat(item, ["fieldGoalsPercentage", "fg_pct", "fgPct", "fieldGoalPct", "field_goal_percentage", "fgPercentage"])
                three_pct = find_stat(item, ["threePointFieldGoalsPercentage", "three_pt_pct", "threePtPct", "threePointPercentage", "three_point_percentage", "threePct"])
                ft_pct = find_stat(item, ["freeThrowsPercentage", "ft_pct", "ftPct", "freeThrowPct", "free_throw_percentage", "ftPercentage"])

                off_reb = find_stat(item, ["offensiveRebounds", "off_reb", "offRebounds", "offensiveReboundsTotal"])
                def_reb = find_stat(item, ["defensiveRebounds", "def_reb", "defRebounds", "defensiveReboundsTotal"])
                tot_reb = find_stat(item, ["rebounds", "totalRebounds", "tot_reb", "reboundsTotal"])
                reb_avg = find_stat(item, [
                    "reboundsPerGame", "reb_avg", "rpg", "rebPerGame", "rebounds_per_game",
                    "reboundsAvg", "rebAvg", "reboundsAverage"
                ])

                ast = find_stat(item, ["assists", "ast", "totalAssists", "assistsTotal"])
                ast_avg = find_stat(item, ["assistsPerGame", "ast_avg", "apg", "astPerGame", "assists_per_game", "assistsAvg"])

                to = find_stat(item, ["turnovers", "to", "totalTurnovers", "turnoversTotal"])
                to_avg = find_stat(item, ["turnoversPerGame", "to_avg", "topg", "toPerGame", "turnovers_per_game", "turnoversAvg"])

                stl = find_stat(item, ["steals", "stl", "totalSteals", "stealsTotal"])
                stl_avg = find_stat(item, ["stealsPerGame", "stl_avg", "spg", "stlPerGame", "steals_per_game", "stealsAvg"])

                blk = find_stat(item, ["blocks", "blk", "totalBlocks", "blocksTotal"])
                blk_avg = find_stat(item, ["blocksPerGame", "blk_avg", "bpg", "blkPerGame", "blocks_per_game", "blocksAvg"])

                # Calculate per-game averages if missing
                try:
                    gp_val = float(gp) if gp else 0.0
                    if gp_val > 0:
                        pts_val = float(pts) if pts else 0.0
                        tot_reb_val = float(tot_reb) if tot_reb else 0.0

                        if not ppg and pts_val > 0:
                            ppg = f"{pts_val / gp_val:.1f}"
                        if not min_avg and min_tot:
                            min_avg = f"{float(min_tot) / gp_val:.1f}"
                        if not reb_avg and tot_reb_val > 0:
                            reb_avg = f"{tot_reb_val / gp_val:.1f}"
                        if not ast_avg and ast:
                            ast_avg = f"{float(ast) / gp_val:.1f}"
                        if not to_avg and to:
                            to_avg = f"{float(to) / gp_val:.1f}"
                        if not stl_avg and stl:
                            stl_avg = f"{float(stl) / gp_val:.1f}"
                        if not blk_avg and blk:
                            blk_avg = f"{float(blk) / gp_val:.1f}"
                except Exception:
                    pass

                if not any([ppg, pts, fg_pct, ft_pct, tot_reb, ast]):
                    continue

                players.append({
                    "name": c_name,
                    "number": c_num,
                    "position": c_pos,
                    "year": c_yr,
                    "gp": gp,
                    "gs": gs,
                    "min": min_tot,
                    "min_avg": min_avg,
                    "pts": pts,
                    "avg": ppg,
                    "fg_pct": fg_pct,
                    "three_pt_pct": three_pct,
                    "ft_pct": ft_pct,
                    "off_reb": off_reb,
                    "def_reb": def_reb,
                    "tot_reb": tot_reb,
                    "reb_avg": reb_avg,
                    "ast": ast,
                    "ast_avg": ast_avg,
                    "to": to,
                    "to_avg": to_avg,
                    "stl": stl,
                    "stl_avg": stl_avg,
                    "blk": blk,
                    "blk_avg": blk_avg,
                })
        except Exception:
            continue

        if len(players) >= 5:
            break

    return players


def parse_old_style_html_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parses Sidearm HTML stats pages into both Totals and Per-Game Averages.
    Filters out #TM Team and aggregates multiple cumulative tables.
    """
    players_by_key: Dict[str, Dict[str, Any]] = {}
    player_order: List[str] = []

    all_tables = soup.find_all("table")

    for table in all_tables:
        parent_tags = [p for p in table.parents if p.name in ["div", "section"]]
        parent_ids = " ".join(p.get("id", "") for p in parent_tags).lower()
        parent_classes = " ".join(" ".join(p.get("class", [])) for p in parent_tags).lower()
        parent_text = " ".join(p.get_text() for p in parent_tags[:2])[:300].lower()

        # Discard irrelevant tables
        if any(bad in parent_ids for bad in ["game-comparison", "game-by-game", "game-highs"]):
            continue
        if any(bad in parent_classes for bad in ["game-comparison", "game-by-game"]):
            continue
        if any(bad in parent_text for bad in ["game-by-game", "schedule", "highs", "comparison"]):
            continue

        caption = table.find("caption")
        if caption and any(bad in caption.get_text().lower() for bad in ["comparison", "game by game", "highs"]):
            continue

        thead = table.find("thead")
        if thead:
            th_texts = [th.get_text().strip().upper() for th in thead.find_all(["th", "td"])]
            if any(bad in th_texts for bad in ["OPPONENT", "DATE", "RESULT", "SCORE", "MAR"]):
                continue

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        if not rows:
            continue

        header_map: Dict[int, str] = {}
        if thead:
            header_row = thead.find_all("tr")[-1] if thead.find_all("tr") else thead
            for idx, th in enumerate(header_row.find_all(["th", "td"])):
                header_map[idx] = th.get_text(strip=True).upper()

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
            seen_headers: set = set()
            for idx, cell in enumerate(cells):
                lbl = cell.get("data-label", "").strip().upper()
                if not lbl and idx in header_map:
                    h_val = header_map[idx]
                    if h_val == "AVG":
                        lbl = "AVG" if "AVG" not in seen_headers else "REB_AVG"
                    else:
                        lbl = h_val
                    seen_headers.add(h_val)

                if lbl and lbl not in label_map:
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

            # Drop team / #TM rows explicitly
            if c_name.lower() in ("team", "tm", "tm team", "team tm", "#tm team"):
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
                        if v and "view bio" not in v.lower() and v.lower() != "null":
                            return v
                return ""

            s_gp      = get_stat(["GP", "GAMES", "GP-GS"])
            s_gs      = get_stat(["GS", "STARTS"])
            s_min     = get_stat(["MIN", "TOTAL MIN", "MINUTES"])
            s_min_avg = get_stat(["MIN/G", "MIN/GAME", "MPG", "AVG MIN"])

            s_pts     = get_stat(["PTS", "TOTAL POINTS", "POINTS"])
            s_avg     = get_stat(["AVG", "PTS/G", "PPG", "PTS_AVG", "POINTS/G"])

            s_fg      = get_stat(["FG%", "FG PCT", "PCT"])
            s_3pt     = get_stat(["3PT%", "3FG PCT", "3P%", "3FG%", "3PT PCT"])
            s_ft      = get_stat(["FT%", "FT PCT", "FTPCT"])

            s_off_reb = get_stat(["OFF REB", "OFF", "O-REB"])
            s_def_reb = get_stat(["DEF REB", "DEF", "D-REB"])
            s_tot_reb = get_stat(["REB", "TOT", "TOTAL", "TOTAL REBOUNDS", "TOT REB", "REBOUNDS"])
            s_reb_avg = get_stat(["REB/G", "RPG", "REB_AVG", "REBOUNDS/G"])

            s_ast     = get_stat(["AST", "ASSISTS", "TOTAL AST"])
            s_ast_avg = get_stat(["AST/G", "APG", "AST_AVG", "ASSISTS/G"])

            s_to      = get_stat(["TO", "TURNOVERS", "TOTAL TO"])
            s_to_avg  = get_stat(["TO/G", "TOPG", "TO_AVG", "TURNOVERS/G"])

            s_stl     = get_stat(["STL", "STEALS", "TOTAL STL"])
            s_stl_avg = get_stat(["STL/G", "SPG", "STL_AVG", "STEALS/G"])

            s_blk     = get_stat(["BLK", "BLOCKS", "TOTAL BLK"])
            s_blk_avg = get_stat(["BLK/G", "BPG", "BLK_AVG", "BLOCKS/G"])

            key = c_name.lower()
            if key not in players_by_key:
                player_order.append(key)
                players_by_key[key] = {
                    "name": c_name,
                    "number": c_num,
                    "position": "",
                    "year": "",
                    "gp": s_gp,
                    "gs": s_gs,
                    "min": s_min,
                    "min_avg": s_min_avg,
                    "pts": s_pts,
                    "avg": s_avg,
                    "fg_pct": s_fg,
                    "three_pt_pct": s_3pt,
                    "ft_pct": s_ft,
                    "off_reb": s_off_reb,
                    "def_reb": s_def_reb,
                    "tot_reb": s_tot_reb,
                    "reb_avg": s_reb_avg,
                    "ast": s_ast,
                    "ast_avg": s_ast_avg,
                    "to": s_to,
                    "to_avg": s_to_avg,
                    "stl": s_stl,
                    "stl_avg": s_stl_avg,
                    "blk": s_blk,
                    "blk_avg": s_blk_avg,
                }
            else:
                p = players_by_key[key]
                for field, val in [
                    ("number", c_num), ("gp", s_gp), ("gs", s_gs), ("min", s_min), ("min_avg", s_min_avg),
                    ("pts", s_pts), ("avg", s_avg), ("fg_pct", s_fg), ("three_pt_pct", s_3pt), ("ft_pct", s_ft),
                    ("off_reb", s_off_reb), ("def_reb", s_def_reb), ("tot_reb", s_tot_reb), ("reb_avg", s_reb_avg),
                    ("ast", s_ast), ("ast_avg", s_ast_avg), ("to", s_to), ("to_avg", s_to_avg),
                    ("stl", s_stl), ("stl_avg", s_stl_avg), ("blk", s_blk), ("blk_avg", s_blk_avg)
                ]:
                    if not p.get(field) and val:
                        p[field] = val

    result_list = [players_by_key[k] for k in player_order if any(players_by_key[k][f] for f in ["avg", "pts", "tot_reb", "ast", "fg_pct"])]

    for p in result_list:
        try:
            gp_val = float(p.get("gp", "0"))
            if gp_val > 0:
                if not p.get("min_avg") and p.get("min"):
                    p["min_avg"] = f"{float(p['min']) / gp_val:.1f}"
                if not p.get("avg") and p.get("pts"):
                    p["avg"] = f"{float(p['pts']) / gp_val:.1f}"
                if not p.get("reb_avg") and p.get("tot_reb"):
                    p["reb_avg"] = f"{float(p['tot_reb']) / gp_val:.1f}"
                if not p.get("ast_avg") and p.get("ast"):
                    p["ast_avg"] = f"{float(p['ast']) / gp_val:.1f}"
                if not p.get("to_avg") and p.get("to"):
                    p["to_avg"] = f"{float(p['to']) / gp_val:.1f}"
                if not p.get("stl_avg") and p.get("stl"):
                    p["stl_avg"] = f"{float(p['stl']) / gp_val:.1f}"
                if not p.get("blk_avg") and p.get("blk"):
                    p["blk_avg"] = f"{float(p['blk']) / gp_val:.1f}"
        except Exception:
            pass

    return result_list


# ── Execution Logic ───────────────────────────────────────────────────────────

async def scrape_single_team(
    context: BrowserContext,
    team_cfg: Dict[str, str],
    gender: str,
    semaphore: asyncio.Semaphore
) -> Dict[str, Any]:
    """Scrapes a single team concurrently within the semaphore limit."""
    async with semaphore:
        team_name = team_cfg["name"]
        slug = team_cfg["slug"]
        gender_label = "Women's" if gender == "women" else "Men's"
        logger.info(f"Processing {team_name} ({gender_label})...")

        # Fetch both roster and stats pages in parallel for this team
        roster_task = fetch_page_html(context, team_cfg["roster_url"])
        stats_task = fetch_page_html(context, team_cfg["stats_url"])
        roster_html, stats_html = await asyncio.gather(roster_task, stats_task)

        # 1. Parse Roster
        roster_lookup = parse_print_roster(roster_html) if roster_html else {}
        logger.info(f"  [{team_name}] Loaded {len(roster_lookup)} roster entries")

        # 2. Parse Stats
        stats_players: List[Dict[str, Any]] = []
        if stats_html:
            # Check modern Nuxt payload first
            stats_players = parse_nuxt_data_stats(stats_html)
            if not stats_players:
                soup = BeautifulSoup(stats_html, "html.parser")
                stats_players = parse_old_style_html_table(soup)

        logger.info(f"  [{team_name}] Parsed {len(stats_players)} player stat lines")

        # 3. Merge stats with roster info
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
            final_pos    = (r_info.get("position") if r_info and r_info.get("position") else sp.get("position", ""))
            final_year   = (r_info.get("year") if r_info and r_info.get("year") else sp.get("year", ""))

            merged_players.append({
                "name": final_name,
                "number": final_number,
                "position": final_pos,
                "year": final_year,
                "gp": sp.get("gp", ""),
                "gs": sp.get("gs", ""),
                "min": sp.get("min", ""),
                "min_avg": sp.get("min_avg", ""),
                "pts": sp.get("pts", ""),
                "avg": sp.get("avg", ""),
                "fg_pct": sp.get("fg_pct", ""),
                "three_pt_pct": sp.get("three_pt_pct", ""),
                "ft_pct": sp.get("ft_pct", ""),
                "off_reb": sp.get("off_reb", ""),
                "def_reb": sp.get("def_reb", ""),
                "tot_reb": sp.get("tot_reb", ""),
                "reb_avg": sp.get("reb_avg", ""),
                "ast": sp.get("ast", ""),
                "ast_avg": sp.get("ast_avg", ""),
                "to": sp.get("to", ""),
                "to_avg": sp.get("to_avg", ""),
                "stl": sp.get("stl", ""),
                "stl_avg": sp.get("stl_avg", ""),
                "blk": sp.get("blk", ""),
                "blk_avg": sp.get("blk_avg", ""),
            })

        team_data = {
            "team": team_name,
            "slug": slug,
            "gender": gender,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "players": merged_players,
        }

        # Write output files
        for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(team_data, f, indent=2)

        return team_data


async def run_scraper():
    os.makedirs("docs", exist_ok=True)
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    start_time = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )

        logger.info("=== Starting Concurrent Basketball Scraping (Men's & Women's) ===")
        tasks = []

        # Men's teams
        for team_cfg in MENS_TEAMS_CONFIG:
            tasks.append(scrape_single_team(context, team_cfg, "men", semaphore))

        # Women's teams
        for team_cfg in WOMENS_TEAMS_CONFIG:
            tasks.append(scrape_single_team(context, team_cfg, "women", semaphore))

        await asyncio.gather(*tasks)
        await browser.close()

    elapsed = time.time() - start_time
    logger.info(f"Done — All 16 team JSONs updated in {elapsed:.1f} seconds!")


def main():
    asyncio.run(run_scraper())


if __name__ == "__main__":
    main()
