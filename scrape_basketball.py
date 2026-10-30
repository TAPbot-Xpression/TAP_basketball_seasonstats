"""
scrape_basketball.py
Scrapes Summit League Men's Basketball player season stats and rosters.
Supports both:
  - Old Sidearm HTML tables (e.g. North Dakota, Oral Roberts) using `data-label` cell parsing & multi-tier header support.
  - New Sidearm Nuxt JSON / NextGen structures (e.g. Kansas City, NDSU, Omaha, South Dakota, SDSU, St. Thomas).

Key requirements handled:
- Pulls player Name ("First Last"), Number, Position (G or F), and Year (FR, SO, JR, SR, GR, R-*).
- Pulls stats: AVG (Scoring PPG), FG%, 3PT%, FT%, TOT (Rebounds), AST, TO, STL, BLK.
- Ignores MIN (Minutes), weight, height, hometown, coaches/staff, headers/footers, and Game-by-Game tables.
- Outputs individual team JSON files (<slug>.json) and docs/all_teams.json.
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

DISCARD_TOKENS = {
    "ft%", "blk", "ast", "tot", "avg", "pts", "off", "def", "min", "stl",
    "to", "fg%", "3pt%", "3p%", "gp", "gs", "pct", "reb", "player", "no.",
    "total", "totals", "team", "opponent", "opponents", "view bio", "bio",
    "team tm team", "tm", "overall", "conference", "image", "full name", "name",
    "scoring", "averages", "minutes", "fg", "3pt", "ft", "rebounds", "player name",
    "title", "yr.", "bio link", "statistic", "high", "opponent(s)"
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
    """
    Cleans raw player name strings:
    - Removes 'View Bio', 'Image', stray quotes, emails
    - Resolves duplicated names like 'Greyson 03 Uelmen, Greyson Uelmen' or 'Branch, Karmello Branch'
    - Transforms 'Branch, Karmello' -> 'Karmello Branch'
    - Eliminates embedded jersey numbers, hashes, and extra spaces
    """
    if not raw_name:
        return ""

    text = raw_name.replace("View Bio", "").replace("Image", "").strip()
    text = re.sub(r"['\"]+", "", text).strip()
    if "@" in text or not text:
        return ""

    # Check for concatenated duplicate like 'Hudgens, Trent02Hudgens, Trent' or 'Evans, CjEvans, Cj'
    match_dup = re.search(r"^(.*?)(?:\d{1,2})?\1$", text)
    if match_dup and len(match_dup.group(1)) > 3:
        text = match_dup.group(1)

    # Check for pattern like 'Greyson 03 Uelmen, Greyson Uelmen'
    if "," in text:
        parts = [p.strip() for p in text.split(",", 1)]
        first_part = parts[0]
        second_part = parts[1] if len(parts) > 1 else ""

        # Remove digits / jersey numbers from both parts
        first_part = re.sub(r"#?\b\d{1,2}\b", "", first_part).strip()
        second_part = re.sub(r"#?\b\d{1,2}\b", "", second_part).strip()

        # If second part contains full name ('Greyson Uelmen') or first part is Last name
        if first_part.lower() in second_part.lower() and len(second_part.split()) > 1:
            text = second_part
        elif second_part and first_part:
            text = f"{second_part} {first_part}"
        else:
            text = second_part or first_part

    # Remove residual numbers / hashes
    text = re.sub(r"#?\b\d{1,2}\b", "", text)
    text = " ".join(text.split()).strip()

    # Remove duplicated words (e.g. 'Greyson Uelmen Greyson Uelmen')
    words = text.split()
    if len(words) >= 4 and words[:len(words)//2] == words[len(words)//2:]:
        text = " ".join(words[:len(words)//2])

    return text


def clean_number(raw_num: Any) -> str:
    """Extracts jersey number cleanly (e.g. '00', '03', '11', '0')."""
    if raw_num is None:
        return ""
    text = str(raw_num).strip().replace("#", "")
    m = re.match(r"^(\d{1,2})$", text)
    return m.group(1) if m else ""


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
    Standardizes academic class standings:
    FR, SO, JR, SR, GR/5TH, or Redshirts (R-FR, R-SO, R-JR, R-SR).
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


def is_valid_player_name(name: str) -> bool:
    """Validates that candidate is an actual basketball player and not a header, score, or staff title."""
    if not name or len(name.strip()) < 2:
        return False

    low = name.strip().lower()
    if low in DISCARD_TOKENS:
        return False

    # Discard numeric, decimal (.567, 1.000), or date values
    if re.match(r"^(\.\d+|\d+(\.\d+)?|\d{1,2}/\d{1,2}/\d{2,4})$", low):
        return False

    # Discard game logs ('at TCU', 'vs Omaha', '62-91')
    if re.search(r"\b(vs|at|\d+-\d+)\b", low):
        return False

    # Discard summary/opponent tokens
    if any(tok in low for tok in ["team tm", "opponents", "opponent", "total", "totals", "attendance", "roster bio"]):
        return False

    # Discard coaching / support staff keywords
    if any(staff in low for staff in STAFF_KEYWORDS):
        return False

    # Discard locations / hometown strings (e.g. "Minn. / Mankato East", "Wis. / Homestead")
    if "/" in low and any(st in low for st in ["minn", "wis", "iowa", "neb", "calif", "tex"]):
        return False

    return True


def scrape_roster(roster_url: str) -> Dict[str, Dict[str, str]]:
    """
    Scrapes team roster for validated Position (G/F) and Academic Year.
    Excludes coaches and support staff.
    """
    html = fetch_url(roster_url)
    roster_lookup: Dict[str, Dict[str, str]] = {}
    if not html:
        return roster_lookup

    soup = BeautifulSoup(html, "html.parser")

    # Decompose staff and coach containers
    for staff in soup.find_all(class_=re.compile(r"staff|coaches|coach", re.I)):
        staff.decompose()
    for staff_header in soup.find_all(["h2", "h3", "h4"], text=re.compile(r"coaching staff|coaches", re.I)):
        parent = staff_header.find_parent(["section", "div"])
        if parent:
            parent.decompose()

    # Strategy 1: Sidearm roster player cards
    player_items = soup.find_all(class_=re.compile(r"roster-player|roster__item|sidearm-roster-player|s-person-details", re.I))

    for p in player_items:
        name_el = p.find(class_=re.compile(r"name|player-name", re.I))
        raw_name = name_el.get_text(separator=" ", strip=True) if name_el else ""
        c_name = clean_name(raw_name)

        if not is_valid_player_name(c_name):
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

    # Strategy 2: Sidearm Table format (old-style rosters)
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
                    if not pos and normalize_position(col):
                        pos = normalize_position(col)
                    if not yr and normalize_year(col):
                        yr = normalize_year(col)
                    c_clean = clean_name(col)
                    if not name_cand and is_valid_player_name(c_clean) and not normalize_position(col) and not normalize_year(col):
                        name_cand = c_clean

                if name_cand and is_valid_player_name(name_cand):
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


def parse_old_style_html_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parses old-style Sidearm statistical tables (such as North Dakota and Oral Roberts).
    Handles multi-tiered <thead> structures and extracts stats using cell `data-label` attributes.
    """
    players = []

    for table in soup.find_all("table"):
        parent_text = " ".join([p.get_text() for p in table.parents if p.name in ["div", "section"]])[:400].lower()
        if any(bad in parent_text for bad in ["game-by-game", "schedule", "highs", "category leaders", "leaders"]):
            continue

        # Old-style Sidearm tables have tbody with tr rows containing data-label attributes
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")
        if not rows:
            continue

        # Look for multi-row header structure to verify this is the cumulative player table
        thead = table.find("thead")
        if thead:
            thead_text = thead.get_text().upper()
            if not ("PLAYER" in thead_text or "NAME" in thead_text) or not ("PTS" in thead_text or "AVG" in thead_text or "SCORING" in thead_text):
                continue
            if any(k in thead_text for k in ["OPPONENT", "DATE", "RESULT", "SCORE"]):
                continue

        table_players = []

        for row in rows:
            # Skip subheader rows inside tbody
            if row.find("th") and not row.find("td"):
                continue

            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            # Build data-label map for this specific row
            label_map: Dict[str, str] = {}
            for cell in cells:
                d_label = cell.get("data-label", "").strip().upper()
                text = cell.get_text(strip=True)
                if d_label:
                    label_map[d_label] = text

            # 1. Extract Player Name
            raw_name = ""
            name_cell = row.find("td", {"data-label": re.compile(r"Name|Player", re.I)}) or row.find("a", href=re.compile(r"roster/[^/]+/\d+", re.I))
            if name_cell:
                raw_name = name_cell.get_text(separator=" ", strip=True)
            elif "NAME" in label_map:
                raw_name = label_map["NAME"]
            elif "PLAYER" in label_map:
                raw_name = label_map["PLAYER"]
            else:
                # Second column is typically player name in standard table
                raw_name = cells[1].get_text(separator=" ", strip=True)

            c_name = clean_name(raw_name)
            if not is_valid_player_name(c_name):
                continue

            # 2. Extract Jersey Number
            raw_num = ""
            jersey_span = row.find(class_=re.compile(r"jersey|number", re.I))
            if jersey_span:
                raw_num = jersey_span.get_text(strip=True)
            elif cells[0].get_text(strip=True).isdigit() or cells[0].get_text(strip=True) in ("00", "0"):
                raw_num = cells[0].get_text(strip=True)
            elif "#" in raw_name:
                num_m = re.search(r"#(\d{1,2})", raw_name)
                if num_m:
                    raw_num = num_m.group(1)

            c_num = clean_number(raw_num)

            # 3. Extract Stats via data-label tags
            # Scoring AVG / PPG (Distinguish from MIN/G and REB/G)
            scoring_avg = label_map.get("PTS/G") or label_map.get("PPG") or label_map.get("AVG") or ""
            fg_pct = label_map.get("FG%") or label_map.get("FG PCT") or ""
            three_pt_pct = label_map.get("3PT%") or label_map.get("3FG PCT") or label_map.get("3P%") or ""
            ft_pct = label_map.get("FT%") or label_map.get("FT PCT") or ""
            tot_reb = label_map.get("REB") or label_map.get("TOT") or label_map.get("TOTAL") or ""
            ast = label_map.get("AST") or ""
            to = label_map.get("TO") or ""
            stl = label_map.get("STL") or ""
            blk = label_map.get("BLK") or ""

            # If data-labels weren't on all cells, map standard index positions
            if not any([scoring_avg, fg_pct, ft_pct, tot_reb]):
                cell_texts = [c.get_text(strip=True) for c in cells]
                # Filter out pure text row headers
                if len(cell_texts) >= 18:
                    # Old Sidearm cumulative stats standard offsets:
                    # [#, Player, GP, GS, MIN, MIN_AVG, PTS, PTS_AVG, FGM, FGA, FG%, 3PT, 3PTA, 3PT%, FTM, FTA, FT%, OFF, DEF, TOT, REB_AVG, PF, AST, TO, STL, BLK]
                    try:
                        fg_pct = cell_texts[10] if "." in cell_texts[10] else ""
                        three_pt_pct = cell_texts[13] if "." in cell_texts[13] else ""
                        ft_pct = cell_texts[16] if "." in cell_texts[16] else ""
                        scoring_avg = cell_texts[7]
                        tot_reb = cell_texts[19]
                        ast = cell_texts[22]
                        to = cell_texts[23]
                        stl = cell_texts[24]
                        blk = cell_texts[25]
                    except IndexError:
                        pass

            def clean_stat(v: str) -> str:
                if not v or v.lower() in DISCARD_TOKENS or "view bio" in v.lower():
                    return ""
                return v

            table_players.append({
                "name": c_name,
                "number": c_num,
                "avg": clean_stat(scoring_avg),
                "fg_pct": clean_stat(fg_pct),
                "three_pt_pct": clean_stat(three_pt_pct),
                "ft_pct": clean_stat(ft_pct),
                "tot_reb": clean_stat(tot_reb),
                "ast": clean_stat(ast),
                "to": clean_stat(to),
                "stl": clean_stat(stl),
                "blk": clean_stat(blk)
            })

        if table_players:
            players = table_players
            break

    return players


def parse_nuxt_data_stats(html: str) -> List[Dict[str, Any]]:
    """
    Parses new Sidearm Nuxt JSON data payloads.
    Targets pointsPerGame (Scoring AVG / PPG) and cumulative stats.
    """
    players = []
    patterns = [
        r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        r"__NUXT_DATA__\s*=\s*(\[.*?\]);",
        r"window\.__NUXT__\s*=\s*(.*?);\s*</script>"
    ]

    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        try:
            raw_json = m.group(1)
            data = json.loads(raw_json)
            if not isinstance(data, list):
                continue

            def resolve(val: Any) -> Any:
                if isinstance(val, int) and 0 <= val < len(data):
                    target = data[val]
                    if isinstance(target, (str, int, float)):
                        return str(target)
                return str(val) if val is not None else ""

            for item in data:
                if not isinstance(item, dict):
                    continue

                # Ignore game-by-game logs and footers
                if "opponent" in item or "winOrLoss" in item or "boxscoreUrl" in item:
                    continue
                if item.get("isAFooterStat") is True:
                    continue

                raw_name = item.get("playerName") or item.get("nameFromStats") or item.get("name")
                if raw_name is None:
                    continue

                name_str = resolve(raw_name)
                c_name = clean_name(name_str)
                if not is_valid_player_name(c_name):
                    continue

                raw_num = item.get("playerUniform") or item.get("jersey") or item.get("number")
                c_num = clean_number(resolve(raw_num))

                # Scoring average (PPG)
                ppg = resolve(item.get("pointsPerGame") or item.get("pts_avg") or item.get("ppg"))
                fg_pct = resolve(item.get("fieldGoalsPercentage") or item.get("fg_pct") or item.get("fgPct"))
                three_pct = resolve(item.get("threePointFieldGoalsPercentage") or item.get("three_pt_pct") or item.get("threePtPct"))
                ft_pct = resolve(item.get("freeThrowsPercentage") or item.get("ft_pct") or item.get("ftPct"))
                tot_reb = resolve(item.get("rebounds") or item.get("totalRebounds") or item.get("tot_reb"))
                ast = resolve(item.get("assists") or item.get("ast"))
                to = resolve(item.get("turnovers") or item.get("to"))
                stl = resolve(item.get("steals") or item.get("stl"))
                blk = resolve(item.get("blocks") or item.get("blk"))

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
                    "blk": blk
                })
        except Exception:
            continue

        if players:
            break

    return players


def scrape_team(team_cfg: Dict[str, str]) -> Dict[str, Any]:
    """Scrapes season cumulative stats & roster for a single Summit League team."""
    team_name = team_cfg["name"]
    slug = team_cfg["slug"]
    logger.info(f"Processing {team_name}...")

    # 1. Fetch Roster
    roster_lookup = scrape_roster(team_cfg["roster_url"])
    logger.info(f"  Loaded {len(roster_lookup)} roster entries for {team_name}")

    # 2. Fetch Stats page (Supports Old HTML table & New Nuxt JSON)
    stats_html = fetch_url(team_cfg["stats_url"])
    stats_players: List[Dict[str, Any]] = []

    if stats_html:
        soup = BeautifulSoup(stats_html, "html.parser")
        stats_players = parse_old_style_html_table(soup)
        if not stats_players:
            stats_players = parse_nuxt_data_stats(stats_html)

    logger.info(f"  Parsed {len(stats_players)} cumulative player stat lines for {team_name}")

    # 3. Merge stats with roster info
    merged_players = []
    seen_names = set()

    for sp in stats_players:
        name = sp.get("name", "")
        if not name or name.lower() in seen_names or not is_valid_player_name(name):
            continue

        seen_names.add(name.lower())

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
            "blk": sp.get("blk", "")
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

    logger.info("Successfully updated Summit League basketball stats!")


if __name__ == "__main__":
    main()
