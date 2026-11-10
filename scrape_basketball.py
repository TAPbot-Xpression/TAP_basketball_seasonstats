"""
scrape_basketball.py
Unified Summit League Basketball player season stats and roster scraper (Men's & Women's)
plus two flexible "Non-Conf" slots (one Men's, one Women's) for any Sidearm opponent.

Features:
  - High-Performance Concurrent Scraping:
      * Async Playwright with an asyncio Semaphore pool (concurrency = 5).
      * Scrapes all conference teams and both Non-Conf slots in parallel.
  - Non-Conf Slots (non_conf.json / non_conf_women.json):
      * Reads non_conf_config.json (written by the GitHub "Run workflow" form):
            {"men":   {"name": "", "stats_url": "", "roster_url": ""},
             "women": {"name": "", "stats_url": "", "roster_url": ""}}
      * Empty slot  -> writes a placeholder JSON so the site shows "no opponent loaded".
      * Roster link blank -> derives candidate print-roster URLs from the stats link
        and tries each until one returns players.
      * Team name blank -> auto-detected from the stats page (og:site_name / <title> / domain).
      * Auto-detects New Style (Nuxt JSON) vs Old Style (HTML tables) by what the page contains.
      * If a Non-Conf link can't be parsed, a stale opponent is never shown as the new one.
  - Safety: if a scrape returns zero players, existing good data for that team is kept.
  - Position & Academic Class Standardization:
      * 'G' (Guard), 'F' (Forward), 'W' (Winger / Wing, e.g., SDSU).
      * FR, SO, JR, SR, GR, R-FR, R-SO, R-JR, R-SR, plus ordinals (1st, 2nd, 3rd, 4th, 5th - NDSU).
  - Nuxt & Print Roster Parser: __NUXT_DATA__ extraction with table / card-block fallbacks.
  - Team & TM Discard Filtering: removes #TM Team, Team, Totals, Opponents rows.
  - Dual Output (Totals & Per-Game Averages) with calculated per-game fallbacks.
  - Multi-tier roster matching: exact -> jersey -> suffix-agnostic -> last name + number -> fuzzy.
"""

import asyncio
import difflib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 5
MIN_ROSTER_ENTRIES = 8   # roster_lookup holds name + #number keys, so 8 ~= 4+ players
NON_CONF_CONFIG_PATH = "non_conf_config.json"
NON_CONF_SLUGS = {"men": "non_conf", "women": "non_conf_women"}

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


# ── Non-Conf Config Helpers ───────────────────────────────────────────────────

def load_non_conf_config() -> Dict[str, Dict[str, str]]:
    """Reads non_conf_config.json. Missing/invalid file means both slots are empty."""
    cfg = {g: {"name": "", "stats_url": "", "roster_url": ""} for g in ("men", "women")}
    try:
        with open(NON_CONF_CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        for g in ("men", "women"):
            entry = raw.get(g) if isinstance(raw, dict) else None
            if isinstance(entry, dict):
                for k in ("name", "stats_url", "roster_url"):
                    cfg[g][k] = str(entry.get(k, "") or "").strip()
    except FileNotFoundError:
        logger.info(f"{NON_CONF_CONFIG_PATH} not found - Non-Conf slots are empty")
    except Exception as e:
        logger.error(f"Could not read {NON_CONF_CONFIG_PATH}: {e}")
    return cfg


def derive_roster_candidates(stats_url: str) -> List[str]:
    """
    Builds likely Sidearm print-roster URLs from a stats URL, e.g.
      https://x.com/sports/mens-basketball/stats/2026-27
        -> /roster/print/2026-27, /roster/2026-27?print=true, /roster/print,
           /roster?print=true, /roster/2026-27, /roster
    """
    base = stats_url.strip().split("#")[0].split("?")[0].rstrip("/")
    m = re.match(r"^(.*?)/stats(?:/(\d{4}-\d{2}))?$", base)
    if not m:
        return []
    root, season = m.group(1), m.group(2)

    cands: List[str] = []
    if season:
        cands += [f"{root}/roster/print/{season}", f"{root}/roster/{season}?print=true"]
    cands += [f"{root}/roster/print", f"{root}/roster?print=true"]
    if season:
        cands.append(f"{root}/roster/{season}")
    cands.append(f"{root}/roster")

    seen, unique = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def detect_team_name(html: Optional[str], url: str) -> str:
    """Best-effort school name from og:site_name, <title>, or the domain."""
    host = urlparse(url).netloc.lower().replace("www.", "")

    def tidy(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        cleaned = re.sub(r"\s*(Official\s+)?(Athletics?|Athletic\s+Site|Website|Site)\b.*$", "", text, flags=re.I).strip()
        return cleaned or text

    if html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            og = soup.find("meta", attrs={"property": "og:site_name"})
            if og and og.get("content", "").strip():
                return tidy(og["content"])
            if soup.title and soup.title.string:
                parts = re.split(r"\s+[|\-–—]\s+", soup.title.string.strip())
                good = [p for p in parts
                        if p.strip() and not re.search(r"stat|basketball|roster|schedule|\d{4}", p, re.I)]
                if good:
                    return tidy(good[-1])
        except Exception:
            pass
    return host or "Non-Conf Opponent"


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

        return await page.content()
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
    """Normalizes basketball positions to G (Guard), F (Forward), or W (Winger / Wing)."""
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
    # Freshman
    "FR": "FR", "FRESHMAN": "FR", "FY": "FR", "FIRST": "FR", "FIRSTYEAR": "FR",
    "1ST": "FR", "1STYEAR": "FR", "1": "FR",

    # Sophomore
    "SO": "SO", "SOPHOMORE": "SO", "SECOND": "SO", "SECONDYEAR": "SO",
    "2ND": "SO", "2NDYEAR": "SO", "2": "SO",

    # Junior
    "JR": "JR", "JUNIOR": "JR", "THIRD": "JR", "THIRDYEAR": "JR",
    "3RD": "JR", "3RDYEAR": "JR", "3": "JR",

    # Senior
    "SR": "SR", "SENIOR": "SR", "FOURTH": "SR", "FOURTHYEAR": "SR",
    "4TH": "SR", "4THYEAR": "SR", "4": "SR",

    # Graduate / 5th year
    "GR": "GR", "GRAD": "GR", "GRADUATE": "GR", "GRADUATESTUDENT": "GR",
    "GRADSTUDENT": "GR", "GS": "GR", "FIFTH": "GR", "FIFTHYEAR": "GR",
    "5TH": "GR", "5THYEAR": "GR", "5": "GR",
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

    if y in _CLASS_MAP:
        return _CLASS_MAP[y]

    # Redshirt prefixes (R-1st, RS-2nd, Redshirt Junior, etc.)
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
    """Extracts roster metadata (Position, Year, Jersey, Name) from __NUXT_DATA__ payloads."""
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
    Parses Sidearm roster pages (Nuxt JSON, responsive HTML tables, or stacked card blocks).
    Extracts player Name, Jersey Number, Position (G/F/W), and Academic Year.
    """
    # 1. Modern Nuxt extraction first
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
    """Parses Sidearm Nuxt JSON payloads (__NUXT_DATA__) for stats on modern (New Style) layouts."""
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
    Parses Old Style Sidearm HTML stats pages into both Totals and Per-Game Averages.
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


# ── Output Helpers ────────────────────────────────────────────────────────────

def write_team_json(slug: str, team_data: Dict[str, Any]) -> None:
    for dest in [f"{slug}.json", os.path.join("docs", f"{slug}.json")]:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(team_data, f, indent=2)


def read_existing_json(slug: str) -> Dict[str, Any]:
    try:
        with open(os.path.join("docs", f"{slug}.json"), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_empty_non_conf(gender: str) -> None:
    """Placeholder for a Non-Conf slot with no link, so the site shows 'no opponent loaded'."""
    slug = NON_CONF_SLUGS[gender]
    write_team_json(slug, {
        "team": "Non-Conf",
        "display_name": "Non-Conf",
        "slug": slug,
        "gender": gender,
        "is_non_conf": True,
        "status": "empty",
        "message": "No Non-Conf opponent loaded. Add a stats link in GitHub Actions > Run workflow.",
        "source_stats_url": "",
        "source_roster_url": "",
        "generated_at": now_iso(),
        "players": [],
    })
    logger.info(f"Non-Conf ({gender}) slot is empty - wrote placeholder {slug}.json")


# ── Execution Logic ───────────────────────────────────────────────────────────

async def fetch_roster(
    context: BrowserContext,
    candidates: List[str],
    label: str
) -> Tuple[Dict[str, Dict[str, str]], str]:
    """Tries each roster URL in order; returns the first good roster (or the best one found)."""
    best_lookup: Dict[str, Dict[str, str]] = {}
    best_url = ""

    for url in candidates:
        html = await fetch_page_html(context, url)
        if not html:
            continue
        lookup = parse_print_roster(html)
        if len(lookup) > len(best_lookup):
            best_lookup, best_url = lookup, url
        if len(lookup) >= MIN_ROSTER_ENTRIES:
            return lookup, url
        logger.info(f"  [{label}] Roster URL gave {len(lookup)} entries, trying next option: {url}")

    return best_lookup, best_url


async def scrape_single_team(
    context: BrowserContext,
    team_cfg: Dict[str, Any],
    gender: str,
    semaphore: asyncio.Semaphore
) -> Dict[str, Any]:
    """Scrapes one team (conference or Non-Conf) within the semaphore limit."""
    async with semaphore:
        slug = team_cfg["slug"]
        is_non_conf = bool(team_cfg.get("is_non_conf"))
        label = f"{'Non-Conf ' if is_non_conf else ''}{team_cfg['name'] or team_cfg['stats_url']}"
        gender_label = "Women's" if gender == "women" else "Men's"
        logger.info(f"Processing {label} ({gender_label})...")

        # Fetch stats page and roster (trying candidate URLs) in parallel
        stats_html, (roster_lookup, roster_used) = await asyncio.gather(
            fetch_page_html(context, team_cfg["stats_url"]),
            fetch_roster(context, team_cfg["roster_candidates"], label),
        )

        team_name = team_cfg["name"] or detect_team_name(stats_html, team_cfg["stats_url"])
        logger.info(f"  [{label}] Loaded {len(roster_lookup)} roster entries")

        # Parse stats - New Style (Nuxt JSON) first, then Old Style (HTML tables)
        stats_players: List[Dict[str, Any]] = []
        style = "none"
        if stats_html:
            stats_players = parse_nuxt_data_stats(stats_html)
            if stats_players:
                style = "New Style (Nuxt data)"
            else:
                soup = BeautifulSoup(stats_html, "html.parser")
                stats_players = parse_old_style_html_table(soup)
                if stats_players:
                    style = "Old Style (HTML tables)"

        logger.info(f"  [{label}] Parsed {len(stats_players)} player stat lines - detected: {style}")

        # Merge stats with roster info
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

        team_data: Dict[str, Any] = {
            "team": team_name,
            "slug": slug,
            "gender": gender,
            "generated_at": now_iso(),
            "players": merged_players,
        }
        if is_non_conf:
            team_data.update({
                "display_name": "Non-Conf",
                "is_non_conf": True,
                "status": "ok" if merged_players else "no_data",
                "source_stats_url": team_cfg["stats_url"],
                "source_roster_url": roster_used,
                "site_style": style,
            })
            if not merged_players:
                team_data["message"] = (
                    "Could not read player stats from this link. Make sure it is the team's "
                    "basketball stats page (a Sidearm site)."
                )

        # Never overwrite good data with an empty scrape
        if not merged_players:
            existing = read_existing_json(slug)
            same_source = (not is_non_conf) or existing.get("source_stats_url") == team_cfg["stats_url"]
            if existing.get("players") and same_source:
                logger.warning(f"  [{label}] No players parsed - keeping existing {slug}.json")
                return existing
            logger.warning(f"  [{label}] No players parsed for {slug}.json")

        write_team_json(slug, team_data)
        return team_data


def build_non_conf_tasks(
    context: BrowserContext,
    semaphore: asyncio.Semaphore
) -> List[Any]:
    """Creates scrape tasks for filled Non-Conf slots and writes placeholders for empty ones."""
    config = load_non_conf_config()
    tasks = []

    for gender in ("men", "women"):
        slot = config[gender]
        stats_url = slot["stats_url"]

        if not stats_url:
            write_empty_non_conf(gender)
            continue

        candidates: List[str] = []
        if slot["roster_url"]:
            candidates.append(slot["roster_url"])
        candidates += [c for c in derive_roster_candidates(stats_url) if c not in candidates]

        team_cfg = {
            "name": slot["name"],        # blank -> auto-detected from the stats page
            "slug": NON_CONF_SLUGS[gender],
            "stats_url": stats_url,
            "roster_candidates": candidates,
            "is_non_conf": True,
        }
        tasks.append(scrape_single_team(context, team_cfg, gender, semaphore))

    return tasks


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

        logger.info("=== Starting Concurrent Basketball Scraping (Conference + Non-Conf) ===")
        tasks = []

        for gender, teams in (("men", MENS_TEAMS_CONFIG), ("women", WOMENS_TEAMS_CONFIG)):
            for team_cfg in teams:
                cfg = dict(team_cfg)
                cfg["roster_candidates"] = [team_cfg["roster_url"]]
                cfg["is_non_conf"] = False
                tasks.append(scrape_single_team(context, cfg, gender, semaphore))

        tasks.extend(build_non_conf_tasks(context, semaphore))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        for err in failures:
            logger.error(f"A team scrape failed: {err!r}")

        await browser.close()

    elapsed = time.time() - start_time
    ok = len(results) - len(failures)
    logger.info(f"Done — {ok} of {len(results)} team scrapes completed in {elapsed:.1f} seconds!")


def main():
    asyncio.run(run_scraper())


if __name__ == "__main__":
    main()
