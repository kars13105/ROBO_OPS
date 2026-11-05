"""Constraint-aware robot-operator field session planning.

Adapted in concept from Kent Contreras's MIT-licensed weekly production planner:
operator qualification, availability, station exclusivity, and a week-based plan.
"""
from __future__ import annotations

from datetime import date, timedelta
import sqlite3

import pandas as pd
from . import db

SLOTS = (("09:00", "11:00"), ("11:00", "13:00"), ("14:00", "16:00"), ("16:00", "18:00"))
PRIORITY = {"Critical":0, "High":1, "Medium":2, "Low":3}
COLUMNS = ["Date","Start","End","Operator","Mission","Robot Type","Site","Station","Hours","mission_id","operator_id","station_id"]


def week_monday(day: date) -> date:
    return day-timedelta(days=day.weekday())


def conflicts(start: str, end: str, existing: list[tuple[str, str]]) -> bool:
    """No time intervals may overlap; touching end/start boundaries are allowed."""
    return any(start < e and end > s for s,e in existing)


def propose(start_date: date, strategy: str = "Deadline first", path=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    monday = week_monday(start_date)
    days = [(monday + timedelta(days=d)).isoformat() for d in range(5)]
    missions = db.query("""SELECT m.*,s.name as site FROM missions m JOIN sites s ON s.id=m.site_id
                       WHERE m.status='Active'""",path=path)
    ops = db.query("SELECT * FROM operators WHERE status='Active'",path=path)
    stations = db.query("SELECT * FROM stations WHERE status='Online'",path=path)
    leave = db.query("SELECT * FROM availability WHERE work_date BETWEEN ? AND ?",(days[0],days[-1]),path=path)
    existing = db.query("SELECT * FROM assignments WHERE work_date BETWEEN ? AND ? AND status<>'Cancelled'",(days[0],days[-1]),path=path)
    delivered = db.query("SELECT mission_id,COALESCE(SUM(duration_h),0) as hours FROM sessions GROUP BY mission_id",path=path)
    hours_done = dict(zip(delivered.mission_id,delivered.hours)) if not delivered.empty else {}
    remaining = {int(m.id):max(0,round(float(m.target_hours)-float(hours_done.get(m.id,0)),2)) for m in missions.itertuples()}
    planned = {int(m.id):0.0 for m in missions.itertuples()}
    busy_op: dict[tuple[str,int],list[tuple[str,str]]] = {}
    busy_station: dict[tuple[str,int],list[tuple[str,str]]] = {}
    load: dict[tuple[str,int],float] = {}
    for a in existing.itertuples():
        busy_op.setdefault((a.work_date,int(a.operator_id)),[]).append((a.start_time,a.end_time))
        busy_station.setdefault((a.work_date,int(a.station_id)),[]).append((a.start_time,a.end_time))
        load[(a.work_date,int(a.operator_id))] = load.get((a.work_date,int(a.operator_id)),0)+(
            int(a.end_time[:2])-int(a.start_time[:2]))
        if a.status == "Scheduled" and int(a.mission_id) in remaining:
            remaining[int(a.mission_id)]=max(0,remaining[int(a.mission_id)]-(int(a.end_time[:2])-int(a.start_time[:2])))
    unavail = {(str(a.work_date),int(a.operator_id)) for a in leave.itertuples() if a.status!="Available"}
    rows=[]
    for day in days:
        for start,end in SLOTS:
            choices = [m for m in missions.itertuples() if remaining[int(m.id)]>=1.0]
            if strategy == "Priority first":
                choices.sort(key=lambda m:(PRIORITY.get(m.priority,2),m.due_date,-remaining[int(m.id)]))
            elif strategy == "Balanced load":
                choices.sort(key=lambda m:(-remaining[int(m.id)],PRIORITY.get(m.priority,2),m.due_date))
            else:
                choices.sort(key=lambda m:(m.due_date,PRIORITY.get(m.priority,2),-remaining[int(m.id)]))
            for mission in choices:
                mid=int(mission.id)
                available_ops = [o for o in ops.itertuples()
                                 if int(o.site_id)==int(mission.site_id) and mission.robot_type in o.skills.split(",")
                                 and (day,int(o.id)) not in unavail
                                 and not conflicts(start,end,busy_op.get((day,int(o.id)),[]))
                                 and load.get((day,int(o.id)),0)+2<=min(8.0,float(o.daily_target))]
                available_stations = [s for s in stations.itertuples()
                                      if int(s.site_id)==int(mission.site_id) and s.robot_type==mission.robot_type
                                      and not conflicts(start,end,busy_station.get((day,int(s.id)),[]))]
                if not available_ops or not available_stations: continue
                if strategy=="Balanced load":
                    available_ops.sort(key=lambda o:(sum(v for (dd,oid),v in load.items() if oid==o.id),o.id))
                else:
                    available_ops.sort(key=lambda o:(load.get((day,o.id),0),o.id))
                op=available_ops[0]
                station=sorted(available_stations,key=lambda s:s.id)[0]
                duration=2.0
                if remaining[mid]<duration: continue  # fixed, two-hour recording windows
                busy_op.setdefault((day,int(op.id)),[]).append((start,end))
                busy_station.setdefault((day,int(station.id)),[]).append((start,end))
                load[(day,int(op.id))]=load.get((day,int(op.id)),0)+duration
                planned[mid]+=duration
                remaining[mid]-=duration
                rows.append({"Date":day,"Start":start,"End":end,"Operator":op.name,
                             "Mission":mission.name,"Robot Type":mission.robot_type,"Site":mission.site,
                             "Station":station.code,"Hours":duration,"mission_id":mid,"operator_id":int(op.id),"station_id":int(station.id)})
    unmet = missions[["id","name","priority","target_hours","due_date"]].copy() if not missions.empty else pd.DataFrame(columns=["id","name","priority","target_hours","due_date"])
    if not unmet.empty:
        unmet["Hours already recorded"] = unmet.id.map(lambda x: round(float(hours_done.get(x,0)),1))
        unmet["Hours proposed"] = unmet.id.map(lambda x: planned.get(int(x),0))
        unmet["Hours unallocated"] = unmet.id.map(lambda x: round(max(0,float(remaining.get(int(x),0))),1))
        unmet = unmet.rename(columns={"id":"ID","name":"Mission","priority":"Priority","target_hours":"Target hours","due_date":"Due date"})
    return pd.DataFrame(rows,columns=COLUMNS),unmet


def commit(plan: pd.DataFrame, path=None) -> int:
    if plan.empty:
        raise ValueError("No assignments to save.")
    with db.connection(path) as con:
        # Transaction protects against double-booking and stale schedule previews.
        con.execute("BEGIN IMMEDIATE")
        for r in plan.itertuples(index=False):
            day=r.Date
            for field,id_ in (("operator_id",r.operator_id),("station_id",r.station_id)):
                booked=con.execute(f"SELECT start_time,end_time FROM assignments WHERE {field}=? AND work_date=? AND status<>'Cancelled'",(int(id_),day)).fetchall()
                if conflicts(r.Start,r.End,[(b[0],b[1]) for b in booked]):
                    raise ValueError(f"Scheduling conflict on {day} {r.Start}; refresh and regenerate the plan.")
            absent=con.execute("SELECT status FROM availability WHERE operator_id=? AND work_date=?",(int(r.operator_id),day)).fetchone()
            if absent and absent[0]!="Available":
                raise ValueError(f"Operator unavailable on {day}. Refresh the proposed schedule.")
            con.execute("INSERT INTO assignments(mission_id,operator_id,station_id,work_date,start_time,end_time,status) VALUES(?,?,?,?,?,?,?)",
                        (int(r.mission_id),int(r.operator_id),int(r.station_id),day,r.Start,r.End,"Scheduled"))
        db.audit("Schedule committed",f"{len(plan)} new slots saved",con)
        return len(plan)
