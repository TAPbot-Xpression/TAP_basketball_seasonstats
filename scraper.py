import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
TOMMIE_URL = "https://tommiesports.com/sports/mbball/stats/2025-26"
AWAY_CONFIG_FILE = "away_team_config.json"
OUTPUT_JSON = "docs/stats.json"

STAT_KEYS = ["AVG", "FG%", "3PT%", "FT%", "OFF", "DEF", "AST", "TO", "STL", "BLK", "MIN"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── HELPERS ──────────────────────────────────────────────────────────────────

def load_away_config():
    """Load the away team URL from config file (if it exists)."""
    if os.path.exists(AWAY_CONFIG_FILE):
        with open(AWAY_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"url": None, "last_scraped": None}


def save_away_config(config):
    with open(AWAY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def fetch_html(url):
    """Fetch page HTML. Falls back to a Jina.ai reader proxy for JS-heavy pages."""
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


def normalize_header(h):
    """Normalize a table header string to one of our STAT_KEYS (or None)."""
    h = h.strip().upper().replace(" ", "")
    mapping = {
        "AVG": "AVG", "PPG": "AVG", "PTS/G": "AVG",
        "FG%": "FG%", "FGP": "FG%",
        "3PT%": "3PT%", "3P%": "3PT%", "3FG%": "3PT%", "3PP": "3PT%",
        "FT%": "FT%", "FTP": "FT%",
        "OFF": "OFF", "OREB": "OFF", "OFFREB": "OFF",
        "DEF": "DEF", "DREB": "DEF", "DEFREB": "DEF",
        "AST": "AST", "A": "AST",
        "TO": "TO", "TOV": "TO", "TURN": "TO",
        "STL": "STL", "ST": "STL",
        "BLK": "BLK", "BS": "BLK",
        "MIN": "MIN", "MPG": "MIN", "MIN/G": "MIN",
    }
    return mapping.get(h)


def parse_stats_table(html, team_label="team"):
    """
    Parse an athletics stats page HTML and return a list of player dicts.
    Tries multiple common table structures used by Sidearm Sports sites.
    """
    soup = BeautifulSoup(html, "html.parser")
    players = []

    # ── Strategy 1: look for <table> elements ──────────────────────────────
    tables = soup.find_all("table")
    for table in tables:
        headers_row = table.find("tr")
        if not headers_row:
            continue
        raw_headers = [th.get_text(strip=True) for th in headers_row.find_all(["th", "td"])]
        if not raw_headers:
            continue

        # Check if this table has at least 3 of our target stats
        mapped = [normalize_header(h) for h in raw_headers]
        if sum(1 for m in mapped if m in STAT_KEYS) < 3:
            continue

        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            player = {"team": team_label, "scraped_at": datetime.utcnow().isoformat() + "Z"}

            # Try to grab player name from first or second column
            for i, cell in enumerate(cells[:3]):
                if cell and not re.match(r"^[\d\.\-]+$", cell):
                    player["name"] = cell
                    break

            for i, key in enumerate(mapped):
                if key and i < len(cells):
                    player[key] = cells[i]

            if player.get("name") and any(k in player for k in STAT_KEYS):
                players.append(player)

        if players:
            break  # Stop after first successful table

    # ── Strategy 2: Sidearm JSON embedded in page ──────────────────────────
    if not players:
        scripts = soup.find_all("script")
        for script in scripts:
            text = script.string or ""
            if "individual" in text.lower() and "stats" in text.lower():
                # Look for JSON blobs
                matches = re.findall(r'\{[^{}]{200,}\}', text)
                for m in matches:
                    try:
                        data = json.loads(m)
                        if isinstance(data, dict) and "players" in data:
                            for p in data["players"]:
                                player = {"team": team_label, "scraped_at": datetime.utcnow().isoformat() + "Z"}
                                player["name"] = p.get("name", p.get("display_name", "Unknown"))
                                for raw_key, val in p.items():
                                    norm = normalize_header(raw_key)
                                    if norm:
                                        player[norm] = str(val)
                                if any(k in player for k in STAT_KEYS):
                                    players.append(player)
                    except Exception:
                        pass

    return players


def scrape_team(url, label):
    print(f"Scraping {label}: {url}")
    try:
        html = fetch_html(url)
        players = parse_stats_table(html, team_label=label)
        print(f"  → Found {len(players)} player rows")
        return players
    except Exception as e:
        print(f"  ERROR scraping {label}: {e}")
        return []


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("docs", exist_ok=True)

    # Load existing output (to preserve away team data if not re-scraping)
    existing = {"tommie": [], "away": [], "meta": {}}
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON, "r") as f:
            existing = json.load(f)

    # ── Scrape Tommie ──────────────────────────────────────────────────────
    tommie_players = scrape_team(TOMMIE_URL, "St. Thomas Tommies")

    # ── Scrape Away Team (if configured and due) ───────────────────────────
    config = load_away_config()
    away_players = existing.get("away", [])

    if config.get("url"):
        last = config.get("last_scraped")
        hours_since = 999
        if last:
            last_dt = datetime.fromisoformat(last.replace("Z", ""))
            hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600

        if hours_since >= 24:
            away_players = scrape_team(config["url"], config.get("label", "Away Team"))
            config["last_scraped"] = datetime.utcnow().isoformat() + "Z"
            save_away_config(config)
        else:
            print(f"Away team last scraped {hours_since:.1f}h ago — skipping (< 24h threshold)")

    # ── Write JSON ─────────────────────────────────────────────────────────
    output = {
        "meta": {
            "tommie_url": TOMMIE_URL,
            "away_url": config.get("url"),
            "away_label": config.get("label", "Away Team"),
            "last_run": datetime.utcnow().isoformat() + "Z",
            "stat_keys": STAT_KEYS,
        },
        "tommie": tommie_players,
        "away": away_players,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ stats.json written → {OUTPUT_JSON}")
    print(f"   Tommie players: {len(tommie_players)}")
    print(f"   Away players:   {len(away_players)}")


if __name__ == "__main__":
    main()
