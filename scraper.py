import os
import re
import json
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# ── CONFIG ──────────────────────────────────────────────────────────────────
TOMMIE_URL = "https://tommiesports.com/sports/mbball/stats/2025-26"
AWAY_CONFIG_FILE = "away_team_config.json"
OUTPUT_JSON = "docs/stats.json"

STAT_KEYS = 
["AVG", "FG%", "3PT%", "FT%", "OFF", "DEF", "AST", "TO", "STL", "BLK", "MIN"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── CONFIG HELPERS ──────────────────────────────────────────────────────────

def load_away_config():
    """Load the away team URL safely from config file."""
    if os.path.exists(AWAY_CONFIG_FILE):
        try:
            with open(AWAY_CONFIG_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Warning: Could not parse {AWAY_CONFIG_FILE} ({e}). Using defaults.")
    return {"url": None, "label": "Away Team", "last_scraped": None}


def save_away_config(config):
    with open(AWAY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def fetch_html(url):
    """Fetch page HTML. Falls back to Jina.ai proxy if direct fetch fails."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Direct fetch failed ({e}), trying Jina reader proxy...")
        jina_url = f"https://r.jina.ai/{url}"
        resp = requests.get(jina_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text


# ── DATA CLEANING & PARSING HELPERS ─────────────────────────────────────────

def clean_player_name_and_number(raw_text):
    """
    Cleans duplicated player names and separates jersey numbers.
    Sidearm tables often output: 'Hall, Marcus13Hall, Marcus' or '04 Wrecke, Mac'.
    Returns: (jersey_number, cleaned_name)
    """
    text = " ".join(raw_text.split()).strip()
    if not text:
        return "", ""

    # Check for duplicated format: "LastName, FirstName##LastName, FirstName"
    dup_match = re.match(r"^(.+?)\s*(\d{1,3})\s*(.+)$", text)
    if dup_match:
        part1 = dup_match.group(1)
        num   = dup_match.group(2)
        part2 = dup_match.group(3)
        p1_clean = re.sub(r"[^a-zA-Z]", "", part1).lower()
        p2_clean = re.sub(r"[^a-zA-Z]", "", part2).lower()
        if p1_clean == p2_clean or p1_clean in p2_clean or p2_clean in p1_clean:
            return num, part1.strip()

    # Check for leading number: "02 Ruedinger, Preston"
    lead_match = re.match(r"^(\d{1,3})\s+(.+)$", text)
    if lead_match:
        return lead_match.group(1), lead_match.group(2).strip()

    # Check for trailing number: "Ruedinger, Preston 02"
    trail_match = re.match(r"^(.+?)\s+(\d{1,3})$", text)
    if trail_match:
        return trail_match.group(2), trail_match.group(1).strip()

    return "", text


def normalize_header(h):
    """Map raw table headers to standard target STAT_KEYS."""
    raw = h.strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    
    mapping = {
        "AVG": "AVG", "PTS/G": "AVG", "PPG": "AVG", "PTSAVG": "AVG", "PTS": "AVG",
        "FG%": "FG%", "FGP": "FG%", "FGPCT": "FG%", "FGPERCENT": "FG%",
        "3PT%": "3PT%", "3P%": "3PT%", "3FG%": "3PT%", "3PP": "3PT%", "3FGPCT": "3PT%",
        "FT%": "FT%", "FTP": "FT%", "FTPCT": "FT%",
        "OFF": "OFF", "OREB": "OFF", "OFFREB": "OFF", "OFFENSIVE": "OFF",
        "DEF": "DEF", "DREB": "DEF", "DEFREB": "DEF", "DEFENSIVE": "DEF",
        "AST": "AST", "A": "AST", "APG": "AST", "AST/G": "AST",
        "TO": "TO", "TOV": "TO", "TURN": "TO", "TURNOVERS": "TO", "TO/G": "TO",
        "STL": "STL", "ST": "STL", "STLS": "STL", "STL/G": "STL",
        "BLK": "BLK", "BS": "BLK", "BLOCKS": "BLK", "BLK/G": "BLK",
        "MIN": "MIN", "MPG": "MIN", "MIN/G": "MIN", "MINUTES": "MIN"
    }
    return mapping.get(raw)


def is_summary_row(name):
    """Filters out summary/team/header rows."""
    if not name:
        return True
    n = name.strip().lower()
    summary_names = 
["total", "opponents", "team", "tm", "#", "player", "totals"]
    return n in summary_names or n.startswith("total") or n.startswith("opponent")


def parse_stats_table(html, team_type="home", team_name="St. Thomas Tommies"):
    """
    Parses player season statistics from HTML.
    Target stats: AVG, FG%, 3PT%, FT%, OFF, DEF, AST, TO, STL, BLK, MIN
    """
    soup = BeautifulSoup(html, "html.parser")
    players = 
[]

    # ── Strategy 1: HTML Tables ─────────────────────────────────────────────
    tables = soup.find_all("table")
    for table in tables:
        # Find headers
        header_rows = table.find_all("tr")
        if not header_rows:
            continue

        raw_headers = 
[]
        # Check first 2 rows for possible multi-row headers
        for r in header_rows
[:2]:
            ths = r.find_all(
["th", "td"])
            row_texts = 
[th.get_text(strip=True) for th in ths]
            if any(normalize_header(t) for t in row_texts):
                raw_headers = row_texts
                break

        if not raw_headers:
            continue

        mapped_headers = 
[normalize_header(h) for h in raw_headers]
        matched_stat_count = sum(1 for m in mapped_headers if m in STAT_KEYS)
        
        # We need a table that contains at least 3 matching stats
        if matched_stat_count < 3:
            continue

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(
["td", "th"])
            if len(cells) < 3:
                continue

            cell_texts = 
[c.get_text(strip=True) for c in cells]
            
            # Determine player name / number
            raw_name = ""
            for idx in range(min(3, len(cell_texts))):
                txt = cell_texts
[idx]
                if txt and not re.match(r"^
[\d\.\-%]+$", txt):
                    raw_name = txt
                    break

            if not raw_name or is_summary_row(raw_name):
                continue

            jersey, clean_name = clean_player_name_and_number(raw_name)
            if is_summary_row(clean_name):
                continue

            player = {
                "jersey": jersey,
                "name": clean_name,
                "team": team_name,
                "team_type": team_type,
                "stats": {k: "-" for k in STAT_KEYS}
            }

            # Map stats by column alignment
            for i, key in enumerate(mapped_headers):
                if key and i < len(cell_texts):
                    val = cell_texts
[i]
                    if val != "":
                        player
["stats"]
[key] = val

            # Keep only rows where at least one valid stat was parsed
            if any(v != "-" for v in player
["stats"].values()):
                players.append(player)

        if players:
            break

    # ── Strategy 2: Embedded JSON fallback ──────────────────────────────────
    if not players:
        scripts = soup.find_all("script")
        for script in scripts:
            text = script.string or ""
            if "individual" in text.lower() and "stats" in text.lower():
                matches = re.findall(r'\{
[^{}]{200,}\}', text)
                for m in matches:
                    try:
                        data = json.loads(m)
                        if isinstance(data, dict) and "players" in data:
                            for p in data
["players"]:
                                raw_p_name = p.get("name", p.get("display_name", ""))
                                if is_summary_row(raw_p_name):
                                    continue
                                jersey, clean_p_name = clean_player_name_and_number(raw_p_name)
                                jersey = p.get("jersey", p.get("number", jersey))

                                player = {
                                    "jersey": str(jersey),
                                    "name": clean_p_name,
                                    "team": team_name,
                                    "team_type": team_type,
                                    "stats": {k: "-" for k in STAT_KEYS}
                                }

                                for raw_k, val in p.items():
                                    norm = normalize_header(raw_k)
                                    if norm:
                                        player
["stats"]
[norm] = str(val)

                                if any(v != "-" for v in player
["stats"].values()):
                                    players.append(player)
                    except Exception:
                        pass

    return players


def scrape_team(url, team_type="home", team_name="Team"):
    print(f"Scraping 
[{team_type.upper()}] {team_name}: {url}")
    try:
        html = fetch_html(url)
        players = parse_stats_table(html, team_type=team_type, team_name=team_name)
        print(f"  → Found {len(players)} players for {team_name}")
        return players
    except Exception as e:
        print(f"  ERROR scraping {team_name}: {e}")
        return 
[]


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("docs", exist_ok=True)

    # 1. Scrape Home Team (St. Thomas Tommies)
    home_team_name = "St. Thomas Tommies"
    home_players = scrape_team(TOMMIE_URL, team_type="home", team_name=home_team_name)

    # 2. Scrape Away Team (if configured)
    config = load_away_config()
    away_team_name = config.get("label", "Away Team")
    away_players = 
[]

    if config.get("url"):
        last = config.get("last_scraped")
        hours_since = 999
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", ""))
                hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
            except Exception:
                hours_since = 999

        if hours_since >= 24 or last is None:
            away_players = scrape_team(config
["url"], team_type="away", team_name=away_team_name)
            config
["last_scraped"] = datetime.utcnow().isoformat() + "Z"
            save_away_config(config)
        else:
            print(f"Away team last scraped {hours_since:.1f}h ago (< 24h threshold)")

    # 3. Build Clear Structured JSON Output
    output = {
        "metadata": {
            "last_updated_utc": datetime.utcnow().isoformat() + "Z",
            "stat_categories": STAT_KEYS,
        },
        "home_team": {
            "name": home_team_name,
            "url": TOMMIE_URL,
            "player_count": len(home_players),
            "roster": home_players
        },
        "away_team": {
            "name": away_team_name,
            "url": config.get("url"),
            "last_scraped": config.get("last_scraped"),
            "player_count": len(away_players),
            "roster": away_players
        }
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Successfully updated {OUTPUT_JSON}")
    print(f"   Home Team ({home_team_name}): {len(home_players)} players")
    print(f"   Away Team ({away_team_name}): {len(away_players)} players")


if __name__ == "__main__":
    main()
