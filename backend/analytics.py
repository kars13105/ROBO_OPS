"""Read-only dashboard metrics and charts input, always sourced from SQLite."""
import pandas as pd
from . import db


def snapshots(path=None):
    tables={}
    for t in ("sites","operators","stations","missions","availability","assignments","sessions","assets","shipments","incidents","activity"):
        tables[t]=db.query(f"SELECT * FROM {t}",path=path)
    return tables


def enriched_sessions(path=None):
    return db.query("""SELECT x.id, x.recorded_on, x.duration_h, x.uploaded_gb, x.quality_score,
       x.frame_drop_pct, x.annotation_pct, x.sync_ok, x.review_status, x.notes,
       o.name as operator, o.id as operator_id, m.name as mission, m.id as mission_id,
       m.robot_type, z.name as site, st.code as station
       FROM sessions x JOIN operators o ON o.id=x.operator_id
       JOIN missions m ON m.id=x.mission_id
       JOIN sites z ON z.id=m.site_id JOIN stations st ON st.id=x.station_id
       ORDER BY x.recorded_on DESC,x.id DESC""",path=path)


def enriched_missions(path=None):
    return db.query("""SELECT m.*, s.name AS site,COALESCE(x.recorded,0) AS recorded_hours,
       ROUND(100.0 * MIN(COALESCE(x.recorded,0),m.target_hours) / m.target_hours,1) as completion_pct
       FROM missions m JOIN sites s ON s.id=m.site_id
       LEFT JOIN (SELECT mission_id,SUM(duration_h) recorded FROM sessions GROUP BY mission_id)x ON x.mission_id=m.id
       ORDER BY CASE m.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,m.due_date""",path=path)


def enriched_assets(path=None):
    return db.query("""SELECT a.*,s.name AS site,o.name AS assigned_to FROM assets a
       JOIN sites s ON s.id=a.site_id LEFT JOIN operators o ON o.id=a.assigned_operator_id
       ORDER BY a.tag""",path=path)


def enriched_assignments(path=None):
    return db.query("""SELECT a.id,a.work_date,a.start_time,a.end_time,a.status,
       m.name as mission,m.id as mission_id,o.name as operator,o.id as operator_id,
       s.code as station,si.name as site,m.robot_type
       FROM assignments a JOIN missions m ON m.id=a.mission_id
       JOIN operators o ON o.id=a.operator_id JOIN stations s ON s.id=a.station_id
       JOIN sites si ON si.id=m.site_id ORDER BY a.work_date,a.start_time""",path=path)


def daily_rollup(sessions:pd.DataFrame) -> pd.DataFrame:
    if sessions.empty: return pd.DataFrame(columns=["date","hours","gb","average_quality","recordings"])
    return (sessions.groupby("recorded_on",as_index=False)
            .agg(hours=("duration_h","sum"),gb=("uploaded_gb","sum"),average_quality=("quality_score","mean"),recordings=("id","count"))
            .rename(columns={"recorded_on":"date"}).sort_values("date"))


def workforce_kpis(sessions:pd.DataFrame) -> pd.DataFrame:
    if sessions.empty: return pd.DataFrame(columns=["operator","sessions","hours","average_quality","volume_gb"])
    return (sessions.groupby("operator",as_index=False)
            .agg(sessions=("id","count"),hours=("duration_h","sum"),average_quality=("quality_score","mean"),volume_gb=("uploaded_gb","sum"))
            .sort_values("hours",ascending=False))


def daily_targets(operators:pd.DataFrame, sessions:pd.DataFrame, work_day:str) -> pd.DataFrame:
    """Compare per-operator output with daily target (synthetic, date-specific)."""
    cols=["operator_id","operator","site","target_h","recorded_h","gap_h","target_status"]
    active=operators[operators.status=="Active"] if not operators.empty else operators
    if active.empty:return pd.DataFrame(columns=cols)
    day_sessions=sessions[sessions.recorded_on==work_day] if not sessions.empty else sessions
    sums=day_sessions.groupby("operator_id").duration_h.sum().to_dict() if not day_sessions.empty else {}
    data=[]
    for o in active.itertuples():
        target=float(o.daily_target)
        recorded=round(float(sums.get(int(o.id),0)),1)
        data.append({"operator_id":int(o.id),"operator":o.name,"site":o.site,"target_h":target,
                     "recorded_h":recorded,"gap_h":round(max(0,target-recorded),1),
                     "target_status":"Met" if recorded>=target else "Below target"})
    return pd.DataFrame(data,columns=cols).sort_values(["gap_h","operator"],ascending=[False,True])
