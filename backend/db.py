"""SQLite persistence and realistic, fully synthetic robotics-operations demo records."""
from __future__ import annotations

import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "roboops.db"


def db_location(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("ROBOOPS_DB_PATH", str(DEFAULT_DB))).expanduser().resolve()


@contextmanager
def connection(path: str | Path | None = None):
    loc = db_location(path)
    loc.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(loc), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


DDL = """
CREATE TABLE IF NOT EXISTS sites (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, city TEXT NOT NULL, capacity INTEGER NOT NULL DEFAULT 6
);
CREATE TABLE IF NOT EXISTS operators (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT NOT NULL DEFAULT 'Teleoperation',
 site_id INTEGER NOT NULL REFERENCES sites(id), skills TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Active',
 daily_target REAL NOT NULL DEFAULT 6 CHECK(daily_target > 0), joined_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stations (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, site_id INTEGER NOT NULL REFERENCES sites(id),
 robot_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Online'
);
CREATE TABLE IF NOT EXISTS missions (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, robot_type TEXT NOT NULL,
 site_id INTEGER NOT NULL REFERENCES sites(id), priority TEXT NOT NULL DEFAULT 'Medium',
 target_hours REAL NOT NULL CHECK(target_hours > 0), due_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Active', description TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS availability (
 operator_id INTEGER NOT NULL REFERENCES operators(id), work_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Available', notes TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(operator_id, work_date)
);
CREATE TABLE IF NOT EXISTS assignments (
 id INTEGER PRIMARY KEY, mission_id INTEGER NOT NULL REFERENCES missions(id),
 operator_id INTEGER NOT NULL REFERENCES operators(id), station_id INTEGER NOT NULL REFERENCES stations(id),
 work_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Scheduled', notes TEXT NOT NULL DEFAULT '',
 UNIQUE(operator_id,work_date,start_time), UNIQUE(station_id,work_date,start_time)
);
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY, mission_id INTEGER NOT NULL REFERENCES missions(id),
 operator_id INTEGER NOT NULL REFERENCES operators(id), station_id INTEGER NOT NULL REFERENCES stations(id),
 recorded_on TEXT NOT NULL, duration_h REAL NOT NULL CHECK(duration_h > 0),
 uploaded_gb REAL NOT NULL DEFAULT 0 CHECK(uploaded_gb >= 0),
 quality_score REAL NOT NULL CHECK(quality_score BETWEEN 0 AND 100),
 frame_drop_pct REAL NOT NULL DEFAULT 0 CHECK(frame_drop_pct BETWEEN 0 AND 100),
 annotation_pct REAL NOT NULL DEFAULT 100 CHECK(annotation_pct BETWEEN 0 AND 100),
 sync_ok INTEGER NOT NULL DEFAULT 1, review_status TEXT NOT NULL DEFAULT 'Pending', notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
 model TEXT NOT NULL, site_id INTEGER NOT NULL REFERENCES sites(id),
 assigned_operator_id INTEGER REFERENCES operators(id),
 status TEXT NOT NULL DEFAULT 'Available', last_service TEXT, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shipments (
 id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id),
 origin_site_id INTEGER NOT NULL REFERENCES sites(id),
 destination_site_id INTEGER NOT NULL REFERENCES sites(id),
 carrier TEXT NOT NULL, tracking_no TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Dispatched', eta_date TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
 site_id INTEGER NOT NULL REFERENCES sites(id), asset_id INTEGER REFERENCES assets(id),
 status TEXT NOT NULL DEFAULT 'Open', owner TEXT NOT NULL, reported_at TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', resolution TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(recorded_on);
CREATE INDEX IF NOT EXISTS idx_sessions_mission ON sessions(mission_id);
CREATE INDEX IF NOT EXISTS idx_assignments_date ON assignments(work_date);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
"""


def initialize(path: str | Path | None = None, seed: bool = True):
    with connection(path) as con:
        con.executescript(DDL)
        count = con.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
        if seed and count == 0:
            _seed(con)


def query(sql: str, args: tuple[Any, ...] = (), path: str | Path | None = None) -> pd.DataFrame:
    with connection(path) as con:
        return pd.read_sql_query(sql, con, params=args)


def write(sql: str, args: tuple[Any, ...] = (), path: str | Path | None = None) -> int:
    with connection(path) as con:
        cur = con.execute(sql, args)
        return int(cur.lastrowid or 0)


def audit(action: str, details: str, con: sqlite3.Connection):
    con.execute("INSERT INTO activity(created_at,action,details) VALUES (?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), action, details))


def add_operator(name: str, team: str, site_id: int, skills: list[str], target: float, path=None) -> int:
    if not name.strip() or not skills or target <= 0:
        raise ValueError("Enter a name, at least one robot skill, and a positive daily target.")
    with connection(path) as con:
        c = con.execute("INSERT INTO operators(name,team,site_id,skills,status,daily_target,joined_on) VALUES(?,?,?,?,?,?,?)",
                        (name.strip(), team, site_id, ",".join(skills), "Active", target, date.today().isoformat()))
        audit("Operator created", f"{name.strip()} joined {team}", con)
        return c.lastrowid


def add_mission(name: str, robot_type: str, site_id: int, priority: str, target_hours: float, due_date: date, description: str, path=None):
    if not name.strip() or target_hours <= 0:
        raise ValueError("Mission name and positive recording target are required.")
    with connection(path) as con:
        c = con.execute("INSERT INTO missions(name,robot_type,site_id,priority,target_hours,due_date,status,description) VALUES(?,?,?,?,?,?,?,?)",
                        (name.strip(), robot_type, site_id, priority, target_hours, due_date.isoformat(), "Active", description.strip()))
        audit("Mission created", name.strip(), con)
        return c.lastrowid


def mark_availability(operator_id: int, work_date: date, status: str, notes: str = "", path=None):
    if status not in {"Available", "Leave", "Training", "Unavailable"}:
        raise ValueError("Invalid availability status.")
    with connection(path) as con:
        con.execute("INSERT INTO availability(operator_id,work_date,status,notes) VALUES(?,?,?,?) "
                    "ON CONFLICT(operator_id,work_date) DO UPDATE SET status=excluded.status,notes=excluded.notes",
                    (operator_id, work_date.isoformat(), status, notes))
        audit("Availability updated", f"Operator {operator_id}: {status} on {work_date}", con)


def log_session(mission_id: int, operator_id: int, station_id: int, recorded_on: date,
                duration_h: float, uploaded_gb: float, frame_drop_pct: float, annotation_pct: float,
                sync_ok: bool, notes: str = "", path=None):
    if duration_h <= 0 or uploaded_gb < 0 or not 0 <= frame_drop_pct <= 100 or not 0 <= annotation_pct <= 100:
        raise ValueError("Session metrics are outside the allowed ranges.")
    with connection(path) as con:
        mr = con.execute("SELECT robot_type,site_id FROM missions WHERE id=?", (mission_id,)).fetchone()
        op = con.execute("SELECT skills,site_id FROM operators WHERE id=?", (operator_id,)).fetchone()
        st = con.execute("SELECT robot_type,site_id FROM stations WHERE id=?", (station_id,)).fetchone()
        if not mr or not op or not st:
            raise ValueError("Invalid mission, operator or station selection.")
        if mr["robot_type"] != st["robot_type"] or mr["robot_type"] not in op["skills"].split(",") or mr["site_id"] != op["site_id"] or mr["site_id"] != st["site_id"]:
            raise ValueError("Mission, operator and station must share a site and compatible robot type.")
        score = quality_formula(frame_drop_pct, annotation_pct, sync_ok)
        review = "Needs Review" if quality_is_flagged(score, frame_drop_pct, annotation_pct, sync_ok) else "Pending"
        c = con.execute("INSERT INTO sessions(mission_id,operator_id,station_id,recorded_on,duration_h,uploaded_gb,quality_score,frame_drop_pct,annotation_pct,sync_ok,review_status,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (mission_id,operator_id,station_id,recorded_on.isoformat(),duration_h,uploaded_gb,score,frame_drop_pct,annotation_pct,int(sync_ok),review,notes))
        audit("Session logged", f"Session {c.lastrowid}: {duration_h:.1f} hours, score {score}", con)
        return c.lastrowid


def quality_formula(frame_drop_pct: float, annotation_pct: float, sync_ok: bool) -> float:
    """Transparent demo-only heuristic, not a production video-quality model."""
    return round(max(0, min(100, 100 - 3 * frame_drop_pct - 0.4 * (100 - annotation_pct) - (10 if not sync_ok else 0))), 1)


def quality_is_flagged(score: float, drop: float, annotation: float, sync: bool) -> bool:
    return score < 80 or drop > 3 or annotation < 85 or not sync


ALLOWED_UPDATES = {
    "operators": {"status", "daily_target", "team", "site_id"},
    "missions": {"status", "priority", "due_date", "target_hours"},
    "stations": {"status"},
    "assets": {"status", "site_id", "assigned_operator_id", "last_service", "notes"},
    "incidents": {"status", "owner", "resolution", "severity"},
    "sessions": {"review_status", "notes"},
    "shipments": {"status"},
    "assignments": {"status"},
}


def update_field(table: str, row_id: int, field: str, value: Any, path=None):
    if field not in ALLOWED_UPDATES.get(table, set()):
        raise ValueError("This field cannot be edited.")
    with connection(path) as con:
        c = con.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (value, row_id))
        if c.rowcount != 1:
            raise ValueError("Record not found.")
        audit("Record updated", f"{table} #{row_id}: {field} → {value}", con)


def add_asset(tag: str, category: str, model: str, site_id: int, status: str = "Available", path=None):
    if not tag.strip() or not model.strip():
        raise ValueError("Asset tag and model are required.")
    with connection(path) as con:
        c = con.execute("INSERT INTO assets(tag,category,model,site_id,status,last_service) VALUES(?,?,?,?,?,?)",
                        (tag.strip().upper(), category, model.strip(), site_id, status, date.today().isoformat()))
        audit("Asset registered", tag.strip().upper(), con)
        return c.lastrowid



def assign_asset(asset_id: int, operator_id: int | None, path=None):
    """Attach or release equipment, preserving site and in-transit constraints."""
    with connection(path) as con:
        asset=con.execute("SELECT site_id,status,tag FROM assets WHERE id=?",(asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Asset not found.")
        if asset["status"] in {"In Transit", "Maintenance", "Out of Service"}:
            raise ValueError("Shipments and unavailable assets cannot be assigned or released here.")
        if operator_id is not None:
            op=con.execute("SELECT site_id,status FROM operators WHERE id=?",(operator_id,)).fetchone()
            if op is None or op["site_id"]!=asset["site_id"] or op["status"]!="Active":
                raise ValueError("Select an active operator assigned to this asset's hub.")
        con.execute("UPDATE assets SET assigned_operator_id=?,status=? WHERE id=?",
                    (operator_id,"Assigned" if operator_id is not None else "Available",asset_id))
        audit("Asset allocation",f"{asset['tag']} assigned to {operator_id or 'fleet inventory'}",con)


def add_shipment(asset_id: int, origin_id: int, dest_id: int, carrier: str, tracking_no: str, eta_date: date, path=None):
    if origin_id == dest_id:
        raise ValueError("Origin and destination must be different.")
    if not carrier.strip() or not tracking_no.strip():
        raise ValueError("Carrier and tracking ID are required.")
    with connection(path) as con:
        asset = con.execute("SELECT site_id,status FROM assets WHERE id=?", (asset_id,)).fetchone()
        if asset is None or asset["site_id"] != origin_id or asset["status"] == "In Transit":
            raise ValueError("Asset must be located at the selected origin and not already in transit.")
        c = con.execute("INSERT INTO shipments(asset_id,origin_site_id,destination_site_id,carrier,tracking_no,status,eta_date,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (asset_id,origin_id,dest_id,carrier.strip(),tracking_no.strip(),"Dispatched",eta_date.isoformat(),datetime.now().isoformat(timespec="seconds")))
        con.execute("UPDATE assets SET status='In Transit',assigned_operator_id=NULL WHERE id=?",(asset_id,))
        audit("Shipment dispatched", f"Asset {asset_id}: {origin_id} → {dest_id}", con)
        return c.lastrowid


def complete_shipment(shipment_id: int, path=None):
    with connection(path) as con:
        sh = con.execute("SELECT asset_id,destination_site_id,status FROM shipments WHERE id=?", (shipment_id,)).fetchone()
        if sh is None or sh["status"] != "Dispatched":
            raise ValueError("Only dispatched shipments can be delivered.")
        con.execute("UPDATE shipments SET status='Delivered' WHERE id=?",(shipment_id,))
        con.execute("UPDATE assets SET site_id=?,status='Available',assigned_operator_id=NULL WHERE id=?",(sh["destination_site_id"],sh["asset_id"]))
        audit("Shipment delivered", f"Shipment {shipment_id} delivered", con)


def add_incident(title: str, category: str, severity: str, site_id: int, owner: str,
                 description: str = "", asset_id: int | None = None, path=None):
    if not title.strip() or not owner.strip():
        raise ValueError("Incident title and owner are required.")
    with connection(path) as con:
        c = con.execute("INSERT INTO incidents(title,category,severity,site_id,asset_id,status,owner,reported_at,description) VALUES(?,?,?,?,?,?,?,?,?)",
                        (title.strip(),category,severity,site_id,asset_id,"Open",owner.strip(),datetime.now().isoformat(timespec="seconds"),description))
        audit("Incident reported", title.strip(), con)
        return c.lastrowid


def reset_demo(path=None):
    with connection(path) as con:
        for table in ("activity","shipments","incidents","sessions","assignments","availability","assets","missions","stations","operators","sites"):
            con.execute(f"DELETE FROM {table}")
        _seed(con)


def _seed(con: sqlite3.Connection):
    rng = random.Random(29)
    today = date.today()
    sites = [(1,"Noida Operations Hub","Noida",10), (2,"Bengaluru Lab","Bengaluru",8), (3,"Pune Field Station","Pune",6)]
    con.executemany("INSERT INTO sites(id,name,city,capacity) VALUES (?,?,?,?)", sites)
    first = ["Aarav Mehta","Ananya Rao","Vihaan Shah","Meera Nair","Kabir Sethi","Ishita Kapoor","Arjun Iyer","Riya Sen","Dev Malhotra","Sana Sheikh","Neel Das","Tara Menon","Rohan Jain","Priya Bose","Aditya Kulkarni","Zoya Khan","Karan Bhat","Nisha Verma"]
    skills = ["Arm", "Mobile", "Humanoid"]
    for i,n in enumerate(first,1):
        site_id = 1 + (i-1)%3
        choices = [skills[(i-1)%3], skills[i%3]] if i%4 else skills
        con.execute("INSERT INTO operators(id,name,team,site_id,skills,status,daily_target,joined_on) VALUES(?,?,?,?,?,?,?,?)",
                    (i,n,"Teleoperation" if i%3 else "Field Data",site_id,",".join(choices),"Active" if i not in (9,15) else "Training",6.0,(today-timedelta(days=75+i*3)).isoformat()))
    station_id=1
    for site in sites:
        for j in range(6):
            con.execute("INSERT INTO stations(id,code,site_id,robot_type,status) VALUES(?,?,?,?,?)",
                        (station_id,f"{['NOD','BLR','PUN'][site[0]-1]}-{j+1:02d}",site[0],skills[j%3],"Maintenance" if station_id in (6,14) else "Online"))
            station_id += 1
    titles = ["Precision pick-and-place", "Kitchen object sorting", "Shelf restocking", "Door handle manipulation", "Warehouse tote transfer", "Assembly screw pickup", "Cloth folding trials", "Cart navigation", "Bin-picking collection", "Home assistance gestures", "Packaging line grasp", "Tool handover workflow", "Staircase mobility", "Fragile item handling", "Drawer opening sequence", "Indoor navigation trials", "Teleop calibration", "Structured clutter cleanup", "Workspace object relocation", "Multi-object stacking", "Station endurance recording"]
    for i,t in enumerate(titles,1):
        site_id = 1 + (i-1)%3
        robot_type = skills[((i-1)//3+(i-1)%3)%3]
        con.execute("INSERT INTO missions(id,name,robot_type,site_id,priority,target_hours,due_date,status,description) VALUES (?,?,?,?,?,?,?,?,?)",
                    (i,t,robot_type,site_id,["High","Medium","Low","Critical"][i%4],float(rng.randrange(24,75,6)),
                     (today+timedelta(days=rng.randint(4,26))).isoformat(),"Active" if i not in (17,18) else "Paused", "Collect high-quality demonstrations for training and validation."))
    asset_categories = ["Camera Kit","Controller","Robot Battery","Edge Computer","Sensor Rig"]
    for i in range(1,43):
        site_id=1+(i-1)%3
        cat=asset_categories[(i-1)%len(asset_categories)]
        status = ["Available","Assigned","Available","Maintenance","Available","Available"][i%6]
        con.execute("INSERT INTO assets(id,tag,category,model,site_id,assigned_operator_id,status,last_service,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                    (i,f"RB-{i:04d}",cat,f"{['Vantage X2','Atlas V4','RoboCell P1','Orion Edge','SensePro'][i%5]}",site_id,
                     None if status!="Assigned" else (1+(i-1)%18),status,(today-timedelta(days=rng.randint(6,70))).isoformat(),"Synthetic demonstration asset"))
    # Legacy scheduling concept adapted to robotics: 2-hour reserved sessions, station / operator exclusive.
    aid = 1
    for age in range(13,-1,-1):
        d = today-timedelta(days=age)
        if d.weekday() >= 5: continue
        for op_id in range(1,19):
            if op_id in (9,15): continue
            site_id=1+(op_id-1)%3
            op_skills = [skills[(op_id-1)%3],skills[op_id%3]] if op_id%4 else skills
            robot_type=op_skills[0]
            candidate=con.execute("SELECT id FROM stations WHERE site_id=? AND robot_type=? AND status='Online' ORDER BY id LIMIT 1", (site_id,robot_type)).fetchone()
            task=con.execute("SELECT id FROM missions WHERE site_id=? AND robot_type=? AND status='Active' ORDER BY id LIMIT 1", (site_id,robot_type)).fetchone()
            if not candidate or not task: continue
            # A single prefilled shift per person, with mutually exclusive station and operator.
            if rng.random()<.64:
                st_time = ["09:00","11:00","14:00","16:00"][(op_id+age)%4]
                occupied=con.execute("SELECT 1 FROM assignments WHERE station_id=? AND work_date=? AND start_time=?",(candidate["id"],d.isoformat(),st_time)).fetchone()
                if occupied: continue
                end_hour=int(st_time[:2])+2
                con.execute("INSERT INTO assignments(id,mission_id,operator_id,station_id,work_date,start_time,end_time,status) VALUES(?,?,?,?,?,?,?,?)",
                            (aid,task["id"],op_id,candidate["id"],d.isoformat(),st_time,f"{end_hour:02d}:00","Completed"))
                aid+=1
    # Historical sessions are independent recordings, not strictly 1:1 with booked blocks.
    for age in range(20,-1,-1):
        d=today-timedelta(days=age)
        if d.weekday()>=5: continue
        for site_id in (1,2,3):
            for robot_type in skills:
                m=con.execute("SELECT id FROM missions WHERE site_id=? AND robot_type=? ORDER BY id LIMIT 1",(site_id,robot_type)).fetchone()
                s=con.execute("SELECT id FROM stations WHERE site_id=? AND robot_type=? ORDER BY id LIMIT 1",(site_id,robot_type)).fetchone()
                op=con.execute("SELECT id FROM operators WHERE site_id=? AND (skills=? OR skills LIKE ? OR skills LIKE ? OR skills LIKE ?) AND status='Active' ORDER BY id LIMIT 1", (site_id,robot_type,robot_type+',%', '%,'+robot_type, '%,'+robot_type+',%')).fetchone()
                if not (m and s and op) or rng.random() < .18: continue
                duration=round(rng.uniform(1.2,4.6),1)
                drop=round(max(0,rng.gauss(1.9,1.55)),1)
                annotation=round(min(100,max(58,rng.gauss(91,7))),1)
                sync=rng.random()>.09
                score=quality_formula(drop,annotation,sync)
                review="Needs Review" if quality_is_flagged(score,drop,annotation,sync) else rng.choice(["Pending","Approved","Approved"])
                con.execute("INSERT INTO sessions(mission_id,operator_id,station_id,recorded_on,duration_h,uploaded_gb,quality_score,frame_drop_pct,annotation_pct,sync_ok,review_status,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (m["id"],op["id"],s["id"],d.isoformat(),duration,round(duration*rng.uniform(1.4,3.9),1),score,drop,annotation,int(sync),review,"Synthetic sample session"))
    for i in range(1,9):
        site_id=1+(i-1)%3
        con.execute("INSERT INTO incidents(title,category,severity,site_id,asset_id,status,owner,reported_at,description,resolution) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (["Camera disconnect","Robot controller lag","Missing upload metadata","Battery calibration drift","Station network outage","Mount bracket damage","Frame-drop spike","Late equipment return"][i-1],
                     ["Hardware","Software","Data Quality","Hardware","Connectivity","Hardware","Data Quality","Logistics"][i-1],
                     ["High","Medium","Low","Critical"][i%4],site_id,i*2,
                     ["Open","In Progress","Resolved"][i%3],first[i-1],(datetime.now()-timedelta(days=i)).isoformat(timespec="seconds"),"Synthetic incident for operations testing.","Replaced / reconfigured" if i%3==2 else ""))
    for i in range(1,8):
        aid=i*5
        from_site=1+(aid-1)%3
        to_site=1+(from_site)%3
        status="Delivered" if i%3==0 else "Dispatched"
        con.execute("INSERT INTO shipments(asset_id,origin_site_id,destination_site_id,carrier,tracking_no,status,eta_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (aid,from_site,to_site,"BlueDart" if i%2 else "Delhivery",f"DEMO-TRK-{i:05d}",status,(today+timedelta(days=i%4)).isoformat(),(datetime.now()-timedelta(days=4)).isoformat(timespec="seconds")))
        if status=="Dispatched":
            con.execute("UPDATE assets SET status='In Transit',assigned_operator_id=NULL WHERE id=?",(aid,))
        else:
            con.execute("UPDATE assets SET site_id=?,status='Available',assigned_operator_id=NULL WHERE id=?",(to_site,aid))
    audit("Demo initialized", "Synthetic robotics operations dataset seeded", con)
