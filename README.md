# TAP Basketball Season Stats

**University of St. Thomas Athletics — Broadcast Production Tool**

---

## Overview

This repository provides up-to-date season statistics for University of St. Thomas Basketball, formatted for use in live broadcast production. It is designed to give production staff quick, reliable access to player and team stats during game preparation, on-air talent briefings, and live broadcast execution.

---

## Purpose

During a broadcast, speed and accuracy are everything. This tool eliminates the need to manually pull stats from external sources mid-production. All season statistics are maintained in a structured format that can be referenced instantly — whether you're building lower thirds, preparing talent cards, or populating graphics on the fly.

---

## Ross Xpression Integration

The stats in this repository are exported as a `.json` file, which is designed for direct integration with **Ross Xpression** graphics systems.

### How to Use

1. Locate the latest `.json` file in the repository.
2. Import the file into your Ross Xpression data source or link it to the appropriate data-driven template.
3. Map the relevant fields (player name, jersey number, stats, etc.) to your Xpression scene variables.
4. Once linked, graphics will populate automatically from the data file — no manual entry required during the broadcast.

> **Tip:** Always confirm the `.json` file has been updated before going to air. Check the file's last-modified timestamp or the repository's commit history.

---

## Auto-Update Schedule

> ⏰ **Stats are automatically updated every day at 9:00 AM.**

The data pipeline refreshes each morning, pulling the latest season statistics and regenerating the `.json` output file. This ensures that by the time production staff arrive for game-day prep, all numbers reflect the most current available data.

If a game was played the previous evening, updated stats should be available by 9:00 AM the following morning.

---

## Repository Contents

| File | Description |
|------|-------------|
| `*.json` | Season stats data file for Ross Xpression integration |
| `*.py` / scripts | Automation scripts that fetch and format stat data |
| `README.md` | This document |

---

## Contact

For questions related to this tool, contact the **University of St. Thomas Athletic Production team (TAP)**.

---

*University of St. Thomas — Tommie Athletics Production*
