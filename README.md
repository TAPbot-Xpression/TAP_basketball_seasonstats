# TAP Basketball Season Stats

**University of St. Thomas Athletics — Broadcast Production Tool**

---

## Overview

This repository provides up-to-date season statistics for Summit League Men's and Women's Basketball, including University of St. Thomas. The data is formatted for live broadcast production. It gives production staff quick, reliable access to player stats during game preparation, talent briefings, and live execution.

Stats are collected for all eight Summit League programs, in both men's and women's divisions:

Kansas City · North Dakota · North Dakota State · Omaha · Oral Roberts · South Dakota · South Dakota State · St. Thomas

---

## Purpose

During a broadcast, speed and accuracy matter most. This tool removes the need to pull stats by hand from eight different athletics websites mid-production. Season statistics are stored in a consistent structure so the same graphics template works for any team.

---

## What's Included

### 1. Team Data Files (`.json`)
One file per team and division, refreshed automatically. Each file is saved in the repository root and in the `docs/` folder.

| Division | File Naming | Example |
|----------|-------------|---------|
| Men's | `<team>.json` | `st_thomas.json` |
| Women's | `<team>_women.json` | `st_thomas_women.json` |

Team names in file names: `kansas_city`, `north_dakota`, `north_dakota_state`, `omaha`, `oral_roberts`, `south_dakota`, `south_dakota_state`, `st_thomas`.

### 2. Stats Dashboard (`index.html`)
A web page for quickly checking numbers during prep or on air.

- **Men's / Women's** division switch
- **Team selector** with team-colored themes
- **Per Game / Season Totals** toggle for the full roster table
- **Jersey number search** that opens a player spotlight card
- **Leader badges** (1st, 2nd, 3rd on the roster) for each stat
- **Sortable columns** and a live player count
- Links to each team's official stats page and raw JSON file

### 3. Scraper (`scrape_basketball.py`)
The automation script that gathers stats and rosters and writes the JSON files.

---

## Data Fields

Every player record contains the following fields. Values are text. A field is left empty (`""`) if the source has no value.

**Player Information**

| Field | Description |
|-------|-------------|
| `name` | Player name (First Last) |
| `number` | Jersey number, without leading zeros (`05` → `5`; `00` → `0`) |
| `position` | `G` Guard · `F` Forward · `W` Winger |
| `year` | `FR` · `SO` · `JR` · `SR` · `GR`, with an `R-` prefix for redshirt (e.g., `R-JR`) |

**Per-Game Averages**

| Field | Broadcast Label |
|-------|-----------------|
| `min_avg` | MIN/G |
| `avg` | PTS/G |
| `reb_avg` | REB/G |
| `ast_avg` | AST/G |
| `to_avg` | TO/G |
| `stl_avg` | STL/G |
| `blk_avg` | BLK/G |

**Season Totals**

| Field | Broadcast Label |
|-------|-----------------|
| `gp` / `gs` | Games Played / Games Started |
| `min` | MIN |
| `pts` | PTS |
| `off_reb` / `def_reb` / `tot_reb` | OFF / DEF / TOT |
| `ast` | AST |
| `to` | TO |
| `stl` | STL |
| `blk` | BLK |

**Shooting Percentages** (same in both views)

| Field | Broadcast Label |
|-------|-----------------|
| `fg_pct` | FG% |
| `three_pt_pct` | 3PT% |
| `ft_pct` | FT% |

Each file also includes `team`, `slug`, `gender`, and `generated_at` (UTC time of the last update).

---

## Ross Xpression Integration

The `.json` files are designed for direct use with **Ross Xpression** data-driven graphics.

### How to Use

1. Locate the `.json` file for the team and division you need.
2. Import the file into your Ross Xpression data source, or link it to the appropriate data-driven template.
3. Map the fields above (player name, jersey number, stats, etc.) to your Xpression scene variables.
4. Once linked, graphics populate from the data file with no manual entry during the broadcast.

### Choosing Per-Game or Season Totals
Both versions of each stat are in every file. Point your template at the per-game fields (e.g., `avg`, `reb_avg`) or the season-total fields (e.g., `pts`, `tot_reb`), depending on the graphic.

> **Tip:** Always confirm the `.json` file has been updated before going to air. Check the `generated_at` value in the file, the file's last-modified timestamp, or the repository's commit history.

---

## Auto-Update Schedule

> ⏰ **Stats are automatically updated every day at 9:00 AM.**

Each morning the pipeline refreshes all 16 team files (8 men's, 8 women's). If a game was played the previous evening, updated stats should be available by 9:00 AM the following morning.

---

## Running the Scraper Manually

Use this if you need a refresh outside the daily schedule.

**One-time setup**

```bash
pip install playwright beautifulsoup4
playwright install chromium
```

**Run**

```bash
python scrape_basketball.py
```

**How it works**

- Pulls cumulative season stats from each team's official athletics site, covering both current and legacy site layouts.
- Pulls position and class year from each team's print-view roster page, then matches players to their stats by name and jersey number.
- Processes teams concurrently to shorten total run time.
- Excludes team and opponent rows (e.g., "TM Team") so only players appear in the output.

---

## Before Going to Air

- Confirm `generated_at` reflects the latest game.
- Spot-check key players against the school's official stats page, using the link in the dashboard.
- If a team shows missing positions, years, or stat values, check that team's official site and re-run the scraper. Contact TAP if the issue continues.

---

## Repository Contents

| File | Description |
|------|-------------|
| `*.json` | Season stats for Ross Xpression integration (men's and women's, all teams) |
| `index.html` | Stats dashboard for quick reference |
| `scrape_basketball.py` | Automation script that fetches and formats stats and rosters |
| `README.md` | This document |

---

## Contact

For questions related to this tool, contact the **University of St. Thomas Athletic Production team (TAP)**.

---

*University of St. Thomas — Tommie Athletics Production*
