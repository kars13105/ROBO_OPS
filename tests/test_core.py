from datetime import date,timedelta
import sqlite3
import pytest
from backend import db,analytics,scheduler


@pytest.fixture
def sample(tmp_path):
    path=tmp_path/"demo.db"
    db.initialize(path)
    return path


def test_initialization_is_idempotent(sample):
    before={key:len(v) for key,v in analytics.snapshots(sample).items()}
    db.initialize(sample)
    after={key:len(v) for key,v in analytics.snapshots(sample).items()}
    assert before==after
    assert before["sites"]==3 and before["operators"]==18
    assert before["missions"]>=20 and before["sessions"]>=80


def test_synthetic_records_are_linked(sample):
    sessions=analytics.enriched_sessions(sample)
    assert sessions["site"].nunique()==3
    assert sessions["quality_score"].between(0,100).all()
    assert len(analytics.enriched_assets(sample))==42


def test_quality_scoring_and_flags():
    assert db.quality_formula(0,100,True)==100
    assert db.quality_formula(5,70,False)==63
    assert db.quality_is_flagged(90,3.4,99,True)
    assert db.quality_is_flagged(90,1,83,True)
    assert not db.quality_is_flagged(93,1,97,True)


def test_create_operator_and_mission(sample):
    oid=db.add_operator("Test Operator","Teleoperation",1,["Arm"],6,path=sample)
    mid=db.add_mission("New mission","Arm",1,"Critical",12,date.today()+timedelta(days=5),"A sample mission",path=sample)
    assert oid>18 and mid>21
    assert db.query("SELECT * FROM missions WHERE id=?",(mid,),sample).iloc[0]["name"]=="New mission"


def test_invalid_operator(sample):
    with pytest.raises(ValueError):db.add_operator(" ","Teleoperation",1,[],0,path=sample)


def test_log_session_matching_skill_site_station(sample):
    ops=db.query("SELECT * FROM operators WHERE id=1",path=sample)
    mission=db.query("SELECT * FROM missions WHERE site_id=1 AND robot_type='Arm' LIMIT 1",path=sample).iloc[0]
    station=db.query("SELECT * FROM stations WHERE site_id=1 AND robot_type='Arm' LIMIT 1",path=sample).iloc[0]
    n=len(analytics.enriched_sessions(sample))
    db.log_session(int(mission.id),1,int(station.id),date.today(),3,6,0.5,99,True,path=sample)
    assert len(analytics.enriched_sessions(sample))==n+1
    with pytest.raises(ValueError):
        db.log_session(int(mission.id),2,int(station.id),date.today(),2,3,1,95,True,path=sample)  # wrong site
    with pytest.raises(ValueError):
        db.log_session(int(mission.id),1,int(station.id),date.today(),0,3,1,95,True,path=sample)


def test_availability_changes_plan(sample):
    wk=date.today()+timedelta(days=7)
    p,_=scheduler.propose(wk,path=sample)
    if p.empty:pytest.skip("No slots available")
    day=date.fromisoformat(p.iloc[0]["Date"])
    op=int(p.iloc[0]["operator_id"])
    db.mark_availability(op,day,"Leave","Leave for test",path=sample)
    after,_=scheduler.propose(wk,path=sample)
    assert after[(after.Date==day.isoformat())&(after.operator_id==op)].empty


def test_scheduler_no_resource_overlaps(sample):
    future=date.today()+timedelta(days=7)
    p,_=scheduler.propose(future,path=sample)
    assert not p.empty
    assert not p.duplicated(["Date","Start","operator_id"]).any()
    assert not p.duplicated(["Date","Start","station_id"]).any()
    assert (p.End.str[:2].astype(int)-p.Start.str[:2].astype(int)).eq(2).all()
    assert p.Date.map(lambda x:date.fromisoformat(x).weekday()<5).all()
    assert p.apply(lambda r: r["Start"]!="13:00",axis=1).all()


def test_schedule_commit_is_atomic_and_rejects_double_book(sample):
    p,_=scheduler.propose(date.today()+timedelta(days=7),path=sample)
    before=len(analytics.enriched_assignments(sample))
    assert scheduler.commit(p,path=sample)==len(p)
    assert len(analytics.enriched_assignments(sample))==before+len(p)
    with pytest.raises(ValueError,match="Scheduling conflict"):
        scheduler.commit(p,path=sample)
    assert len(analytics.enriched_assignments(sample))==before+len(p)


def test_shipments_move_asset_between_sites(sample):
    a=db.query("SELECT id,site_id FROM assets WHERE status='Available' LIMIT 1",path=sample).iloc[0]
    dest=2 if a.site_id==1 else 1
    sid=db.add_shipment(int(a.id),int(a.site_id),dest,"Carrier","TEST-TRACK",date.today()+timedelta(days=2),path=sample)
    assert db.query("SELECT status FROM assets WHERE id=?",(int(a.id),),sample).iloc[0]["status"]=="In Transit"
    db.complete_shipment(sid,path=sample)
    arrived=db.query("SELECT site_id,status FROM assets WHERE id=?",(int(a.id),),sample).iloc[0]
    assert arrived.site_id==dest and arrived.status=="Available"
    with pytest.raises(ValueError):db.complete_shipment(sid,path=sample)


def test_incidents_and_update_whitelist(sample):
    iid=db.add_incident("Test asset problem","Hardware","High",1,"Lead","Test event",path=sample)
    db.update_field("incidents",iid,"status","Resolved",path=sample)
    assert db.query("SELECT status FROM incidents WHERE id=?",(iid,),sample).iloc[0].status=="Resolved"
    with pytest.raises(ValueError):db.update_field("incidents",iid,"title","Danger",path=sample)


def test_reset_replaces_changes(sample):
    db.add_operator("Temporary","Teleoperation",1,["Arm"],6,path=sample)
    db.reset_demo(sample)
    assert len(db.query("SELECT * FROM operators",path=sample))==18
    assert len(db.query("SELECT * FROM activity",path=sample))==1


def test_scheduler_date_anchor(sample):
    assert scheduler.week_monday(date(2026,11,5))==date(2026,11,2)
    assert scheduler.conflicts("09:00","11:00",[("11:00","13:00")]) is False
    assert scheduler.conflicts("10:00","12:00",[("11:00","13:00")]) is True


def test_asset_allocation_respects_site(sample):
    a=db.query("SELECT id,site_id FROM assets WHERE status='Available' LIMIT 1",path=sample).iloc[0]
    op=db.query("SELECT id FROM operators WHERE site_id=? AND status='Active' LIMIT 1",(int(a.site_id),),sample).iloc[0]
    db.assign_asset(int(a.id),int(op.id),path=sample)
    assigned=db.query("SELECT status,assigned_operator_id FROM assets WHERE id=?",(int(a.id),),sample).iloc[0]
    assert assigned.status=="Assigned" and assigned.assigned_operator_id==int(op.id)
    db.assign_asset(int(a.id),None,path=sample)
    assert db.query("SELECT status FROM assets WHERE id=?",(int(a.id),),sample).iloc[0].status=="Available"
    other_site=2 if int(a.site_id)==1 else 1
    other=db.query("SELECT id FROM operators WHERE site_id=? AND status='Active' LIMIT 1",(other_site,),sample).iloc[0]
    with pytest.raises(ValueError):db.assign_asset(int(a.id),int(other.id),path=sample)


def test_daily_target_report(sample):
    op=db.query("SELECT o.*,s.name site FROM operators o JOIN sites s ON s.id=o.site_id",path=sample)
    sessions=analytics.enriched_sessions(sample)
    report=analytics.daily_targets(op,sessions,date.today().isoformat())
    assert len(report)==len(op[op.status=="Active"])
    assert (report.gap_h>=0).all()
    assert report.target_status.isin(["Met","Below target"]).all()
