"""
scrape_basketball.py — TAPbot Summit League Men's Basketball Season Stats
Scrapes player stats and roster info for all Summit League Men's Basketball teams.

Two Sidearm site styles supported:
  - "new"  : NUXT/JS-rendered pages → uses hidden __NUXT_DATA__ JSON blob
  - "old"  : Classic Sidearm HTML table pages → uses BeautifulSoup HTML parser

Output:
  - One JSON file per team  (e.g. north_dakota_state.json)
  - all_teams.json          (combined data for all teams)
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup

# ── Team configuration ────────────────────────────────────────────────────────

TEAMS = [
    {
        "name": "Kansas City",
        "slug": "kansas_city",
        "style": "new",
        "stats_url": "https://kcroos.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://kcroos.com/sports/mens-basketball/roster",
    },
    {
        "name": "North Dakota",
        "slug": "north_dakota",
        "style": "old",
        "stats_url": "https://fightinghawks.com/sports/mens-basketball/stats",
        "roster_url": "https://fightinghawks.com/sports/mens-basketball/roster",
    },
    {
        "name": "North Dakota State",
        "slug": "north_dakota_state",
        "style": "new",
        "stats_url": "https://gobison.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://gobison.com/sports/mens-basketball/roster",
    },
    {
        "name": "Omaha",
        "slug": "omaha",
        "style": "new",
        "stats_url": "https://omahamavs.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://omahamavs.com/sports/mens-basketball/roster",
    },
    {
        "name": "Oral Roberts",
        "slug": "oral_roberts",
        "style": "old",
        "stats_url": "https://oruathletics.com/sports/mens-basketball/stats/2025-26?path=mbball",
        "roster_url": "https://oruathletics.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota",
        "slug": "south_dakota",
        "style": "new",
        "stats_url": "https://goyotes.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://goyotes.com/sports/mens-basketball/roster",
    },
    {
        "name": "South Dakota State",
        "slug": "south_dakota_state",
        "style": "new",
        "stats_url": "https://gojacks.com/sports/mens-basketball/stats/2025-26",
        "roster_url": "https://gojacks.com/sports/mens-basketball/roster",
    },
    {
        "name": "St. Thomas",
        "slug": "st_thomas",
        "style": "new",
        "stats_url": "https://tommiesports.com/sports/mbball/stats/2025-26",
        "roster_url": "https://tommiesports.com/sports/mbball/roster",
    },
]

# ── Shared HTTP session ───────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})

# ── Stat column mapping (basketball) ─────────────────────────────────────────
# Maps display header text → our JSON key
STAT_COLUMNS = {
    "avg":   "avg",
    "ppg":   "avg",
    "fg%":   "fg_pct",
    "3pt%":  "three_pt_pct",
    "3p%":   "three_pt_pct",
    "ft%":   "ft_pct",
    "tot":   "tot_reb",
    "reb":   "tot_reb",
    "rpg":   "tot_reb",
    "ast":   "ast",
    "apg":   "ast",
    "to":    "to",
    "stl":   "stl",
    "blk":   "blk",
    "min":   "min",
    "mpg":   "min",
}

STAT_KEYS = ["avg", "fg_pct", "three_pt_pct", "ft_pct", "tot_reb", "ast", "to", "stl", "blk", "min"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_page(url: str) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    resp = SESSION.get(url, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def clean(text: str) -> str:
    """Strip and collapse whitespace."""
    return re.sub(r"\s+", " ", text or "").strip()


def format_name(raw: str) -> str:
    """
    Convert 'Lastname, Firstname' → 'Firstname Lastname'.
    If already 'Firstname Lastname' style, return as-is.
    """
    raw = clean(raw)
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        return f"{parts[1]} {parts[0]}"
    return raw


def safe_stat(value: str) -> str:
    """Return cleaned stat string or empty string if dash/null."""
    v = clean(value)
    return "" if v in ("-", "--", "N/A", "") else v


# ── NEW-STYLE scraper (NUXT hidden JSON) ──────────────────────────────────────

def extract_nuxt_json(url: str) -> dict | None:
    """
    Pull the hidden __NUXT_DATA__ JSON blob from a new-style Sidearm page.
    Returns the parsed JSON dict/list, or None if not found.
    """
    resp = SESSION.get(url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Pattern 1: <script id="__NUXT_DATA__" ...>JSON</script>
    match = re.search(
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern 2: window.__NUXT__ = {...}
    match = re.search(r'window\.__NUXT__\s*=\s*(\{.*?\});', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern 3: __NUXT_DATA__ as a standalone JSON array
    match = re.search(r'__NUXT_DATA__\s*=\s*(\[.*?\])\s*;', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def flatten_nuxt(data) -> list:
    """
    Walk the NUXT data structure and collect all dicts that look like
    player stat rows (have a 'name' or 'display_name' key plus stat fields).
    """
    players = []
    seen_ids = set()

    def walk(node):
        if isinstance(node, dict):
            keys = {k.lower() for k in node.keys()}
            # Heuristic: a player stat node has a name-like key and at least one stat key
            name_keys = {"name", "display_name", "full_name", "athlete_name"}
            stat_keys  = {"avg", "ppg", "fg_pct", "fg%", "ast", "reb", "blk", "stl", "min", "mpg"}
            if name_keys & keys and stat_keys & keys:
                uid = str(node.get("id") or node.get("athlete_id") or node.get("name") or id(node))
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    players.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return players


def parse_nuxt_player(raw: dict) -> dict:
    """Map a raw NUXT player dict to our standard schema."""
    # Name
    name_raw = (
        raw.get("display_name")
        or raw.get("full_name")
        or raw.get("athlete_name")
        or raw.get("name")
        or ""
    )
    name = format_name(name_raw)

    # Stats — try both snake_case and original key names
    def g(*keys):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return safe_stat(str(v))
        return ""

    return {
        "name":         name,
        "number":       g("jersey", "jersey_number", "number", "uniform_number"),
        "position":     g("position", "pos"),
        "year":         g("year", "class_year", "eligibility", "academic_year"),
        "avg":          g("avg", "ppg", "points_per_game"),
        "fg_pct":       g("fg_pct", "fg%", "field_goal_pct"),
        "three_pt_pct": g("three_pt_pct", "3pt%", "3p%", "three_point_pct"),
        "ft_pct":       g("ft_pct", "ft%", "free_throw_pct"),
        "tot_reb":      g("tot_reb", "reb", "rpg", "rebounds_per_game", "total_rebounds"),
        "ast":          g("ast", "apg", "assists_per_game"),
        "to":           g("to", "turnovers", "turnovers_per_game"),
        "stl":          g("stl", "steals", "steals_per_game"),
        "blk":          g("blk", "blocks", "blocks_per_game"),
        "min":          g("min", "mpg", "minutes_per_game"),
    }


def scrape_new_style(team: dict) -> list[dict]:
    """
    Scrape a new-style (NUXT) Sidearm stats page.
    Falls back to HTML table parsing if NUXT data is unavailable.
    """
    print(f"  [new] Fetching NUXT stats: {team['stats_url']}")
    nuxt = extract_nuxt_json(team["stats_url"])

    players = []

    if nuxt:
        raw_players = flatten_nuxt(nuxt)
        if raw_players:
            print(f"  [new] Found {len(raw_players)} players in NUXT data")
            players = [parse_nuxt_player(p) for p in raw_players]

    if not players:
        print(f"  [new] NUXT parse yielded no players — falling back to HTML table")
        players = scrape_old_style_stats(team["stats_url"])

    # Merge roster info
    roster = scrape_roster(team["roster_url"], style="new")
    players = merge_roster(players, roster)

    return players


# ── OLD-STYLE scraper (HTML table) ───────────────────────────────────────────

def scrape_old_style_stats(stats_url: str) -> list[dict]:
    """
    Parse a classic Sidearm HTML stats table.
    Looks for a <table> whose headers include 'avg' or 'ppg'.
    """
    soup = get_page(stats_url)
    players = []

    # Find all tables and pick the player averages one
    for table in soup.find_all("table"):
        headers_raw = [clean(th.get_text()).lower() for th in table.find_all("th")]
        if not headers_raw:
            continue

        # Must have at least a name column and one stat column
        has_name = any(h in ("name", "player") for h in headers_raw)
        has_stat = any(h in STAT_COLUMNS for h in headers_raw)
        if not (has_name and has_stat):
            continue

        # Build column index map
        col_map = {}
        for i, h in enumerate(headers_raw):
            if h in ("name", "player"):
                col_map["name"] = i
            elif h in STAT_COLUMNS:
                col_map[STAT_COLUMNS[h]] = i

        # Parse rows
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            name_idx = col_map.get("name", 0)
            name_raw = clean(cells[name_idx].get_text()) if name_idx < len(cells) else ""
            if not name_raw or name_raw.lower() in ("totals", "team", "opponents"):
                continue

            player = {
                "name":         format_name(name_raw),
                "number":       "",
                "position":     "",
                "year":         "",
                "avg":          "",
                "fg_pct":       "",
                "three_pt_pct": "",
                "ft_pct":       "",
                "tot_reb":      "",
                "ast":          "",
                "to":           "",
                "stl":          "",
                "blk":          "",
                "min":          "",
            }

            for key, idx in col_map.items():
                if key == "name":
                    continue
                if idx < len(cells):
                    player[key] = safe_stat(cells[idx].get_text())

            players.append(player)

        if players:
            break  # Stop after first matching table

    return players


# ── Roster scraper ────────────────────────────────────────────────────────────

def scrape_roster(roster_url: str, style: str = "old") -> dict[str, dict]:
    """
    Scrape roster page for jersey number, position, and year.
    Returns a dict keyed by normalized player name.
    """
    print(f"  Fetching roster: {roster_url}")
    try:
        soup = get_page(roster_url)
    except Exception as e:
        print(f"  WARNING: Could not fetch roster ({e})")
        return {}

    roster = {}

    # ── Try structured roster cards / rows first ──────────────────────────────
    # Sidearm roster pages often use .s-person-card or similar
    cards = (
        soup.select(".s-person-card, .roster-card, [class*='roster-player'], [class*='person-card']")
    )

    if cards:
        for card in cards:
            name_el = card.select_one(
                ".s-person-card__title, .name, [class*='player-name'], [class*='person-name']"
            )
            if not name_el:
                continue
            name = format_name(clean(name_el.get_text()))

            num_el  = card.select_one("[class*='number'], [class*='jersey'], .s-person-card__number")
            pos_el  = card.select_one("[class*='position'], [class*='pos']")
            year_el = card.select_one("[class*='year'], [class*='class'], [class*='eligibility']")

            roster[name.lower()] = {
                "number":   clean(num_el.get_text())  if num_el  else "",
                "position": clean(pos_el.get_text())  if pos_el  else "",
                "year":     clean(year_el.get_text()) if year_el else "",
            }
        if roster:
            return roster

    # ── Fallback: look for a roster <table> ───────────────────────────────────
    for table in soup.find_all("table"):
        headers_raw = [clean(th.get_text()).lower() for th in table.find_all("th")]
        has_name = any(h in ("name", "player", "full name") for h in headers_raw)
        if not has_name:
            continue

        col_map = {}
        for i, h in enumerate(headers_raw):
            if h in ("name", "player", "full name"):
                col_map["name"] = i
            elif h in ("#", "no", "no.", "jersey", "number"):
                col_map["number"] = i
            elif h in ("pos", "position"):
                col_map["position"] = i
            elif h in ("yr", "year", "class", "eligibility", "cl"):
                col_map["year"] = i

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            name_idx = col_map.get("name", 0)
            name_raw = clean(cells[name_idx].get_text()) if name_idx < len(cells) else ""
            if not name_raw:
                continue
            name = format_name(name_raw)

            def cell(key):
                idx = col_map.get(key)
                return clean(cells[idx].get_text()) if idx is not None and idx < len(cells) else ""

            roster[name.lower()] = {
                "number":   cell("number"),
                "position": cell("position"),
                "year":     cell("year"),
            }

        if roster:
            break

    return roster


def merge_roster(players: list[dict], roster: dict[str, dict]) -> list[dict]:
    """
    Merge roster info (number, position, year) into player stat dicts.
    Matches on normalized lowercase name.
    """
    for player in players:
        key = player["name"].lower()
        info = roster.get(key, {})
        if not player.get("number"):
            player["number"]   = info.get("number", "")
        if not player.get("position"):
            player["position"] = info.get("position", "")
        if not player.get("year"):
            player["year"]     = info.get("year", "")
    return players


# ── Old-style full pipeline ───────────────────────────────────────────────────

def scrape_old_style(team: dict) -> list[dict]:
    """Full pipeline for old-style Sidearm sites."""
    print(f"  [old] Fetching HTML stats: {team['stats_url']}")
    players = scrape_old_style_stats(team["stats_url"])
    roster  = scrape_roster(team["roster_url"], style="old")
    players = merge_roster(players, roster)
    return players


# ── Main orchestrator ─────────────────────────────────────────────────────────

def scrape_team(team: dict) -> dict:
    """Scrape one team and return its data dict."""
    print(f"\n{'='*60}")
    print(f"Scraping: {team['name']} ({team['style']} style)")
    print(f"{'='*60}")

    try:
        if team["style"] == "new":
            players = scrape_new_style(team)
        else:
            players = scrape_old_style(team)
    except Exception as e:
        print(f"  ERROR scraping {team['name']}: {e}")
        players = []

    print(f"  → {len(players)} players collected")

    return {
        "team":    team["name"],
        "slug":    team["slug"],
        "players": players,
    }


def save_json(data: dict | list, filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {filename}")


def main():
    all_teams = []

    for team in TEAMS:
        team_data = scrape_team(team)
        all_teams.append(team_data)

        # Save individual team JSON
        filename = f"{team['slug']}.json"
        save_json(team_data, filename)

        # Be polite to servers
        time.sleep(1.5)

    # Save combined JSON
    save_json(all_teams, "all_teams.json")
    print("\nDone! all_teams.json written.")


if __name__ == "__main__":
    main()
