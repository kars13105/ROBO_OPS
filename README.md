# ◈ RoboOps — Robotics Field Operations Command Center

**A complete, interactive Streamlit application for managing robot teleoperators, field recording operations, data quality, mission scheduling, equipment and logistics.**

> **Portfolio / simulation project — not affiliated with Aktoria Robotics.** All starter operators, missions, equipment and recording metrics are **synthetic**. This is not connected to real robot hardware, teleoperation streams, company data or shipment carriers.

## What it does

| Workspace | Working features |
| --- | --- |
| **Command Center** | Last-seven-day KPIs, throughput trend, robot-type breakdown, mission completion, incident and daily-target alerts, activity log |
| **Mission Planner** | Weekly three-strategy scheduler, skill / site / station matching, leave calendar, workload caps, exclusive time slots, preview/commit, interactive Gantt, cancel, mission create/status update |
| **Workforce** | Operator directory, onboarding, readiness status, qualification and daily recording targets, productivity leaderboard, leave/training calendar, daily target shortfall report |
| **Recordings & QA** | Log actual work against a mission and station, upload size, frame drops, annotation coverage, sensor sync, transparent quality score, QA review / approval, trend charts |
| **Fleet & Logistics** | Equipment inventory, new assets, service status, assign/return asset, cross-site dispatch, carrier/tracking IDs, shipment receipt and inventory updates |
| **Incident Desk** | Log issue, owner, category, severity, site, incident resolution, status tracking, trend analysis |
| **Analytics & Exports** | Period filters, site reporting, operator/robot productivity, target fulfillment, individual CSV downloads, full-database CSV ZIP export |
| **Settings** | Database inventory, deployment notes, explicit demo-data reset |

### Stack

- **Frontend:** Python + Streamlit, custom dark glass-like CSS, Plotly charts / timeline.
- **Database:** SQLite through Python's built-in `sqlite3` (persistent; no server credentials).
- **Planning:** Rule-based heuristic adapted from the uploaded weekly production-planning example.
- **Analytics:** Pandas and Plotly.
- **Tests:** pytest with temporary SQLite databases (15 tests).

## Quick start (macOS / Linux)

Requires **Python 3.11 or 3.12** recommended and an internet connection for installing Python packages.

```bash
unzip RoboOps_Robotics_Operations.zip
cd RoboOps_Robotics_Operations
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open **http://localhost:8501** in your browser. The application creates a demo SQLite database automatically on first launch.

For Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Or use `python -m streamlit run app.py`. If you run from another folder, first `cd` into the project root.

## Recommended demo walkthrough

1. In **Command Center**, examine the fleet, recording metrics, mission throughput and flagged alerts.
2. Go to **Workforce → Availability calendar** and mark one operator on leave for a future workday.
3. In **Mission Planner**, choose a future week and generate a schedule using *Deadline first*. Inspect the Gantt chart and save the proposed assignments.
4. Change allocation strategy to *Balanced load* and compare the resulting assignments. The scheduler respects existing reservations.
5. Go to **Recordings & QA** and log a session using a compatible robot type and hub; intentionally set a high frame-drop percentage to trigger a QA warning.
6. In **QA → Review queue**, inspect and approve or reject the recording.
7. In **Fleet & Logistics**, assign a camera kit to an eligible operator; dispatch a different asset to another site and confirm delivery.
8. Create a critical incident, update its resolution, then **export a CSV/ZIP report** from Analytics.

Every saved change is persisted locally and is reflected in dashboards after a rerun.

## Repository structure

```text
RoboOps_Robotics_Operations/
├── app.py                   # All eight polished interactive workspaces
├── backend/
│   ├── db.py                # SQLite schema, seed, CRUD and validation
│   ├── scheduler.py         # Heuristic, constraints, preview and commit
│   └── analytics.py         # Reporting and KPI calculations
├── assets/style.css         # Dark UI design system
├── .streamlit/config.toml   # Streamlit theme
├── data/                    # Created automatically at first run
├── tests/test_core.py       # Automated backend tests
├── legacy/                  # Attribution copies of original source modules
├── requirements.txt
├── requirements-dev.txt
├── LICENSE.txt
├── NOTICE.md
└── README.md
```

### Scheduling rules

- Weekly Monday–Friday calendar; 2-hour recording slots at 09:00, 11:00, 14:00 and 16:00. 13:00–14:00 is reserved.
- An operator must be **Active**, qualified for the mission's robot type, at the correct hub, and **Available** on that date.
- The station must be **Online** and match the mission's site and robot type.
- No overlapping assignment is accepted for the same operator or station.
- Scheduled hours respect the operator's configured daily recording target (up to an eight-hour working day).
- Recording hours already logged count toward mission fulfillment; unsent scheduled hours count toward planning demand.
- Existing bookings are checked again at commit time to prevent duplicates / stale-preview overlaps.
- Proposals support **Deadline first**, **Priority first** and **Balanced load** strategies. This is a practical heuristic, **not an optimal mathematical solver**.

### Quality-check rules

Each manually entered recording gets a demo score:

`quality_score = clamp(100 - 3 × frame_drop_percent - 0.4 × (100 - annotation_percent) - (10 if sync_failed else 0), 0, 100)`

The record is flagged for review if any of these is true:

- Score below 80
- Frame drop percentage above 3%
- Annotation completeness below 85%
- Sensor synchronization failed

**Important:** Quality metrics are entered by a user; the app does **not** currently inspect raw videos, evaluate actual robotics demonstrations or train ML models.

### Storage, privacy and authentication

- Data lives in `data/roboops.db` after first launch. It will not be included by default when pushing this repository due to `.gitignore`.
- Set `ROBOOPS_DB_PATH=/your/path/database.db` to override the SQLite file location.
- The bundled application is intended for **local portfolio use**. It has no login, role-based authorization, API integration or multi-user server coordination. **Do not expose it to the public internet or use real staff/customer data without adding appropriate security.**
- When sharing screenshots, call it a **synthetic demonstration**.

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

Core tests cover dataset initialization, SQLite CRUD, compatibility checks, quality thresholds, availability, double-booking prevention and atomic schedule commits, shipments, asset allocation, incident records, reset, target reporting and date/slot logic.

## Credit and open-source license

This project is a substantial robotics-oriented reworking inspired by the uploaded **Weekly Production Planning Dashboard**, authored by **Kent Contreras (2025)**: [kecon17/production-planning-dashboard](https://github.com/kecon17/production-planning-dashboard). The original project uses Excel-based production demand, operator training and work-cell scheduling. RoboOps replaces these workflows with robotics-specific missions, local SQL data, QA, asset tracking, incident management, dashboards and a redesigned UI. Its operator/week/station scheduling concepts are adapted from the source.

The original author’s copyright and **MIT license** are retained in `LICENSE.txt`; the original `etl.py` and `dashboard.py` are preserved under `legacy/` for provenance and are not imported by the new app. See `NOTICE.md`. Preserve those notices if you redistribute this repository.

## Limitations / next steps

Potential production enhancements: SSO and role permissions, REST APIs, actual robot integration, event-driven alerts (email/Slack), video ingest and automated CV-based QA, audit immutability, background job handling, optimization with OR-Tools, database migrations, cloud Postgres and deployment monitoring.

---

**Suggested resume description (only after you have run and verified the app yourself):**

> Developed **RoboOps**, a Streamlit + SQLite dashboard for synthetic robotics field operations, integrating constraint-aware operator scheduling, recording quality checks, fleet logistics, incident workflows and interactive KPIs.

When describing the project, acknowledge that it was **adapted from an MIT-licensed planning tool**, and distinguish your modifications from the original.
# ROBO_OPS
# ROBO_OPS
