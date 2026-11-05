"""RoboOps | Robotics Field Operations Command Center

A portfolio-grade, local-first interactive Streamlit app. All data is synthetic.
Run: streamlit run app.py
"""
from __future__ import annotations

import html
import io
import os
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from backend import analytics as an
from backend import db, scheduler

st.set_page_config(page_title="RoboOps | Operations Command Center", page_icon="🦾", layout="wide", initial_sidebar_state="expanded")
ROOT = Path(__file__).resolve().parent
st.markdown(f"<style>{(ROOT/'assets'/'style.css').read_text()}</style>", unsafe_allow_html=True)
db.initialize()
if st.session_state.get("_flash"):
    st.toast(st.session_state.pop("_flash"), icon="✅")

PLOT = {"paper_bgcolor":"rgba(0,0,0,0)","plot_bgcolor":"rgba(0,0,0,0)","font":{"color":"#c7d3e2","family":"DM Sans, sans-serif"},"margin":{"l":10,"r":10,"t":25,"b":18},"height":310,"legend":{"orientation":"h","y":-0.2},"hoverlabel":{"bgcolor":"#20314a"}}
COLORS = ["#56dec9", "#938cfb", "#68a5ef", "#f0b46e", "#ef819c", "#a5d0dd"]
ALL_PAGES = ["◈  Command Center","▦  Mission Planner","♙  Workforce","◉  Recordings & QA", "▣  Fleet & Logistics","⚑  Incident Desk","◫  Analytics & Exports","⚙  Settings"]


def title(name: str, subtitle: str, tag: str = "LIVE DEMO · SYNTHETIC DATA"):
    st.markdown(f"<div class='hero'><div class='eyebrow'>ROBOTICS OPERATIONS / FIELD INTELLIGENCE</div>"
                f"<h1>{html.escape(name)}</h1><p>{html.escape(subtitle)}</p>"
                f"<span class='hero-tag'>● {html.escape(tag)}</span></div>", unsafe_allow_html=True)


def heading(text: str):
    st.markdown(f"<div class='sectionlabel'>{html.escape(text)}</div>",unsafe_allow_html=True)


def dfview(df:pd.DataFrame, cols=None, h=350):
    if df.empty:
        st.info("No matching records. Try a different filter or add a record.")
        return
    if cols:
        df=df[[c for c in cols if c in df.columns]]
    st.dataframe(df, use_container_width=True, hide_index=True, height=min(h, max(110,42+35*len(df))))


def theme(fig, height=320):
    fig.update_layout(**{**PLOT,"height":height}, colorway=COLORS)
    fig.update_xaxes(gridcolor="#26344a",zeroline=False,showline=False)
    fig.update_yaxes(gridcolor="#26344a",zeroline=False,showline=False)
    return fig


def notify(text: str):
    st.session_state["_flash"] = text
    st.rerun()


def failed(exc:Exception):
    st.error(f"Could not save: {str(exc)}")


def site_scope(df:pd.DataFrame, site:str) -> pd.DataFrame:
    return df if site=="All sites" or "site" not in df.columns else df[df.site==site]


def names(df:pd.DataFrame, key="name") -> dict:
    return {f"{r[key]} · #{int(r['id'])}":int(r["id"]) for _,r in df.iterrows()}


def form_selector(label:str, choices:dict, key=None):
    if not choices: return None
    chosen=st.selectbox(label,list(choices),key=key)
    return choices[chosen]


def safe_export(df:pd.DataFrame) -> bytes:
    """Prevent spreadsheet formula injection in exported user-entered text."""
    df=df.copy()
    for c in df.select_dtypes(include="object").columns:
        df[c]=df[c].map(lambda v:"'"+v if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v)
    return df.to_csv(index=False).encode("utf-8-sig")


def zip_export() -> bytes:
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",zipfile.ZIP_DEFLATED) as z:
        for table,df in an.snapshots().items():
            z.writestr(f"roboops_{table}.csv",safe_export(df))
        z.writestr("README.txt","RoboOps SQLite export. All seed records are fictional; user edits may be included.\n")
    return stream.getvalue()


sites=db.query("SELECT * FROM sites ORDER BY id")
site_dict=names(sites)
site_options=["All sites"]+sites.name.tolist()
with st.sidebar:
    st.markdown("<div class='logo'><div class='brand'>◈ ROBO<strong>OPS</strong></div><div class='brand-sub'>FIELD OPERATIONS SYSTEM</div></div>",unsafe_allow_html=True)
    st.caption("WORKSPACE  /  OPERATIONS")
    page=st.radio("Navigate",ALL_PAGES,label_visibility="collapsed")
    st.divider()
    st.caption("LOCATION FILTER")
    site_filter=st.selectbox("Hub",site_options,label_visibility="collapsed")
    st.markdown("<div class='sidecard'><strong>● DEMO ENVIRONMENT</strong><br>Fictional operators, assets and recordings. No robot hardware or live company systems are connected.</div>",unsafe_allow_html=True)
    if st.button("↻ Refresh records",use_container_width=True): st.rerun()
    st.caption(f"ROBOOPS v1.0  ·  {date.today().strftime('%d %b %Y')}")


def command_center():
    title("Operations command center","One view of recording throughput, operator readiness, fleet utilization and outstanding operational risks.")
    op=db.query("SELECT o.*,s.name as site FROM operators o JOIN sites s ON o.site_id=s.id")
    ses=site_scope(an.enriched_sessions(),site_filter)
    ops=site_scope(op,site_filter)
    missions=site_scope(an.enriched_missions(),site_filter)
    assets=site_scope(an.enriched_assets(),site_filter)
    incidents=site_scope(db.query("SELECT i.*,s.name site FROM incidents i JOIN sites s ON s.id=i.site_id"),site_filter)
    today=date.today()
    recent=ses[ses.recorded_on >= (today-timedelta(days=6)).isoformat()]
    last_workday=today-timedelta(days=1)
    while last_workday.weekday()>=5: last_workday-=timedelta(days=1)
    targets=an.daily_targets(ops,ses,last_workday.isoformat())
    missed=int(targets.target_status.eq("Below target").sum()) if not targets.empty else 0
    hours=recent.duration_h.sum() if not recent.empty else 0
    quality=float(recent.quality_score.mean()) if not recent.empty else 0
    passing=100*(~recent.review_status.isin(["Needs Review","Rejected"])).mean() if not recent.empty else 0
    open_inc=int(incidents.status.isin(["Open","In Progress"]).sum()) if not incidents.empty else 0
    cols=st.columns(6)
    metrics=[("Recording hours · 7D",f"{hours:,.1f}h"),("Flag-free recordings",f"{passing:.0f}%"),
             ("Active operators",str(int((ops.status=="Active").sum()))),("Quality average",f"{quality:.1f}/100"),
             ("Open incidents",str(open_inc)),("Below daily target",str(missed))]
    for c,(k,v) in zip(cols,metrics):
        with c: st.metric(k,v)
    st.write("")
    left,right=st.columns([1.65,1],gap="large")
    with left:
        heading("Recording throughput")
        daily=an.daily_rollup(ses)
        if not daily.empty:
            cutoff=(today-timedelta(days=13)).isoformat()
            daily=daily[daily.date>=cutoff]
            fig=px.area(daily,x="date",y="hours",markers=True,labels={"date":"Date","hours":"Recording hours"})
            fig.update_traces(line_color=COLORS[0],fillcolor="rgba(86,222,201,.17)",marker_size=7)
            st.plotly_chart(theme(fig,322),use_container_width=True)
        else: st.info("Record sessions to build a throughput timeline.")
    with right:
        heading("Recordings by robot type")
        if not recent.empty:
            comp=recent.groupby("robot_type",as_index=False).duration_h.sum()
            fig=px.pie(comp,names="robot_type",values="duration_h",hole=.66,color_discrete_sequence=COLORS)
            fig.update_traces(textposition="outside",textinfo="percent+label")
            fig.update_layout(showlegend=False,annotations=[dict(text=f"{hours:.0f}h",x=.5,y=.5,font_size=25,font_color="#edf9ff",showarrow=False)])
            st.plotly_chart(theme(fig,322),use_container_width=True)
        else: st.info("No recordings in the selected range.")
    a,b=st.columns([1.25,1],gap="large")
    with a:
        heading("Mission delivery pipeline")
        if not missions.empty:
            top=missions.sort_values("completion_pct",ascending=True).head(7)
            fig=px.bar(top,x="completion_pct",y="name",orientation="h",color="priority",color_discrete_map={"Critical":"#ee879d","High":"#f3b56f","Medium":"#64d9c5","Low":"#918bfb"},range_x=[0,105],text="completion_pct")
            fig.update_traces(texttemplate="%{text:.0f}%",textposition="outside",cliponaxis=False)
            fig.update_layout(xaxis_title="Completion (%)",yaxis_title="",showlegend=False)
            st.plotly_chart(theme(fig,335),use_container_width=True)
        else: st.info("No active missions.")
    with b:
        heading("Attention queue")
        alerts=[]
        if not recent.empty:
            flagged=int(recent.review_status.isin(["Needs Review","Rejected"]).sum())
            if flagged: alerts.append(("Data quality",f"{flagged} recordings require review","warn"))
        if open_inc: alerts.append(("Operational incidents",f"{open_inc} unresolved incidents","bad"))
        if missed:alerts.append(("Recording targets",f"{missed} operators below target on {last_workday.strftime('%d %b')}","warn"))
        maintenance=int(assets.status.eq("Maintenance").sum()) if not assets.empty else 0
        if maintenance: alerts.append(("Equipment maintenance",f"{maintenance} assets marked for service","warn"))
        late=int(((missions.due_date<today.isoformat()) & (missions.completion_pct<100) & (missions.status=="Active")).sum()) if not missions.empty else 0
        if late:alerts.append(("Overdue missions",f"{late} missions beyond deadline","bad"))
        if not alerts: st.success("No current alerts in the selected hub.")
        for label,msg,tone in alerts:
            st.markdown(f"<div class='cardblock'><div class='kicker'>{html.escape(label)} <span class='chip chip-{tone}'>ATTENTION</span></div><div class='big' style='font-size:1.07rem'>{html.escape(msg)}</div><div class='sub'>Open the relevant workspace to resolve.</div></div>",unsafe_allow_html=True)
    heading("Recent activity")
    activity=db.query("SELECT created_at,action,details FROM activity ORDER BY id DESC LIMIT 8")
    dfview(activity, h=360)


def mission_planner():
    title("Mission planner","Allocate trained operators to compatible robot stations with conflict-aware weekly scheduling.","OPERATOR + STATION CONSTRAINTS ENFORCED")
    tasks=site_scope(an.enriched_missions(),site_filter)
    assignments=site_scope(an.enriched_assignments(),site_filter)
    tabs=st.tabs(["Auto scheduling","Schedule board","Mission management"])
    with tabs[0]:
        c1,c2,c3=st.columns([1.15,1,1.2])
        with c1: wk=st.date_input("Planning week",value=date.today(),key="week_choice")
        with c2: strategy=st.selectbox("Allocation strategy",["Deadline first","Priority first","Balanced load"])
        with c3:
            st.write("")
            if st.button("✦ Generate weekly plan",type="primary",use_container_width=True):
                try:
                    p,u=scheduler.propose(wk,strategy)
                    if site_filter!="All sites": p=site_scope(p,site_filter)
                    st.session_state["plan"] = p
                    st.session_state["unmet"] = u
                    st.session_state["plan_meta"]=(str(scheduler.week_monday(wk)),strategy,site_filter)
                except Exception as exc: failed(exc)
        st.caption("Two-hour recording blocks · Monday–Friday · 09:00–18:00 · 13:00–14:00 break · qualified operators only · daily target respected")
        if "plan" in st.session_state:
            plan=st.session_state["plan"]
            if st.session_state.get("plan_meta") != (str(scheduler.week_monday(wk)),strategy,site_filter):
                st.warning("Settings changed. Regenerate to preview the new plan.")
            elif not plan.empty:
                c1,c2,c3=st.columns(3)
                c1.metric("Proposed assignments",f"{len(plan)}")
                c2.metric("Recording hours allocated",f"{plan.Hours.sum():.0f}h")
                c3.metric("Operators scheduled",f"{plan.operator_id.nunique()}")
                heading("Proposed week")
                plot_timeline(plan,"Operator")
                dfview(plan.drop(columns=["mission_id","operator_id","station_id"]),h=340)
                if st.button("✓ Commit these assignments",type="primary",use_container_width=True):
                    try:
                        n=scheduler.commit(plan)
                        del st.session_state["plan"]
                        notify(f"Committed {n} conflict-checked schedule blocks to the database.")
                    except Exception as exc: failed(exc)
                with st.expander("Mission coverage and remaining workload"):
                    dfview(st.session_state.get("unmet",pd.DataFrame()),h=400)
            else: st.warning("No slots could be planned. Check active missions, operator qualifications and station status.")
        else: st.info("Select a strategy and generate a schedule preview. Nothing will be saved until you commit it.")
    with tabs[1]:
        heading("Booked sessions")
        a,b=st.columns(2)
        with a: from_d=st.date_input("From",value=date.today()-timedelta(days=7),key="sch_from")
        with b: to_d=st.date_input("To",value=date.today()+timedelta(days=14),key="sch_to")
        view=assignments[(assignments.work_date>=str(from_d))&(assignments.work_date<=str(to_d))] if not assignments.empty else assignments
        if not view.empty:
            plot_timeline(view.rename(columns={"work_date":"Date","start_time":"Start","end_time":"End","operator":"Operator","mission":"Mission","site":"Site"}),"Operator")
            dfview(view[["id","work_date","start_time","end_time","operator","station","mission","status","site"]])
            active=view[view.status=="Scheduled"]
            with st.expander("Cancel a booked slot"):
                if not active.empty:
                    ids={f"#{int(r.id)} · {r.work_date} {r.start_time} · {r.operator}":int(r.id) for r in active.itertuples()}
                    selected=form_selector("Booked assignment",ids)
                    if st.button("Cancel selected booking"):
                        try:db.update_field("assignments",selected,"status","Cancelled");notify("Booking cancelled.")
                        except Exception as exc:failed(exc)
        else:st.info("No assignments for the selected period.")
    with tabs[2]:
        heading("Mission portfolio")
        dfview(tasks,cols=["id","name","robot_type","site","priority","target_hours","recorded_hours","completion_pct","due_date","status"],h=360)
        a,b=st.columns(2,gap="large")
        with a:
            heading("Create mission")
            with st.form("new_mission",clear_on_submit=True):
                mname=st.text_input("Mission name",placeholder="e.g., Shelf restocking demonstrations")
                robot=st.selectbox("Robot type",["Arm","Mobile","Humanoid"])
                site_id=form_selector("Deployment hub",site_dict)
                priority=st.selectbox("Priority",["Medium","High","Critical","Low"])
                target=st.number_input("Target recording hours",min_value=2.0,value=40.0,step=2.0)
                due=st.date_input("Due date",value=date.today()+timedelta(days=14))
                desc=st.text_area("Brief",placeholder="Task description and data collection goals")
                submitted=st.form_submit_button("Create mission",type="primary")
            if submitted:
                try: db.add_mission(mname,robot,site_id,priority,target,due,desc);notify("Mission added to planning backlog.")
                except Exception as exc: failed(exc)
        with b:
            heading("Update mission")
            if not tasks.empty:
                selected=form_selector("Mission",names(tasks,"name"),"mission_edit")
                status=st.selectbox("New status",["Active","Paused","Completed","Cancelled"],key="mission_status")
                if st.button("Save mission status",use_container_width=True):
                    try: db.update_field("missions",selected,"status",status);notify("Mission status updated.")
                    except Exception as exc:failed(exc)
                st.caption("Completion rates use actual recorded hours, not scheduled hours.")


def plot_timeline(df:pd.DataFrame,group_col:str="Operator"):
    if df.empty:return
    v=df.copy()
    v["Begin"]=pd.to_datetime(v["Date"].astype(str)+" "+v["Start"].astype(str),errors="coerce")
    v["Finish"]=pd.to_datetime(v["Date"].astype(str)+" "+v["End"].astype(str),errors="coerce")
    v=v.dropna(subset=["Begin","Finish"])
    if v.empty:return
    if len(v)>220:v=v.tail(220)
    try:
        fig=px.timeline(v,x_start="Begin",x_end="Finish",y=group_col,color="Mission",hover_data=["Date","Site"])
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(legend_title_text="",xaxis_title="",yaxis_title="")
        st.plotly_chart(theme(fig,min(580,260+len(v[group_col].unique())*25)),use_container_width=True)
    except Exception:
        st.dataframe(v,use_container_width=True,hide_index=True)


def workforce():
    title("Workforce operations","Manage qualifications, operator availability, shift readiness and productivity against data-collection targets.")
    people=site_scope(db.query("SELECT o.*,s.name site FROM operators o JOIN sites s ON s.id=o.site_id ORDER BY o.name"),site_filter)
    ses=site_scope(an.enriched_sessions(),site_filter)
    active=int((people.status=="Active").sum()) if not people.empty else 0
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Total operators",len(people));c2.metric("Ready for deployment",active)
    c3.metric("On training",int((people.status=="Training").sum()) if not people.empty else 0)
    c4.metric("Total recorded hours",f"{ses.duration_h.sum():.1f}h" if not ses.empty else "0h")
    t1,t2,t3,t4=st.tabs(["Roster & KPIs","Manage operators","Availability calendar","Daily target report"])
    with t1:
        heading("Operator roster")
        dfview(people,cols=["id","name","team","site","skills","status","daily_target","joined_on"],h=360)
        heading("Recording leaderboard")
        perf=an.workforce_kpis(ses)
        if not perf.empty:
            a,b=st.columns([1.5,1],gap="large")
            with a:
                fig=px.bar(perf.head(12).sort_values("hours"),x="hours",y="operator",orientation="h",color="average_quality",color_continuous_scale=[[0,"#6074b6"],[.5,"#6ca5dc"],[1,"#5ae4c1"]],text="hours")
                fig.update_layout(yaxis_title="",xaxis_title="Recorded hours",coloraxis_colorbar_title="QA score")
                st.plotly_chart(theme(fig,410),use_container_width=True)
            with b:dfview(perf.round(1),h=430)
    with t2:
        a,b=st.columns(2,gap="large")
        with a:
            heading("Onboard operator")
            with st.form("add_operator",clear_on_submit=True):
                name=st.text_input("Full name")
                team=st.selectbox("Team",["Teleoperation","Field Data","Quality Assurance"])
                site_id=form_selector("Primary hub",site_dict,"new_op_site")
                skills=st.multiselect("Robot qualification",["Arm","Mobile","Humanoid"],default=["Arm"])
                target=st.number_input("Daily recording target (h)",min_value=.5,max_value=12.0,value=6.0,step=.5)
                submit=st.form_submit_button("Add operator",type="primary")
            if submit:
                try:db.add_operator(name,team,site_id,skills,target);notify("Operator successfully onboarded.")
                except Exception as exc:failed(exc)
        with b:
            heading("Update worker status")
            if not people.empty:
                op_id=form_selector("Operator",names(people),"editop")
                status=st.selectbox("Employment / readiness status",["Active","Training","On Leave","Inactive"])
                if st.button("Save readiness status"):
                    try:db.update_field("operators",op_id,"status",status);notify("Operator status updated.")
                    except Exception as exc:failed(exc)
                st.caption("A worker must be Active and qualified for a robot type before they are scheduled.")
    with t3:
        heading("Shift availability")
        a,b,c=st.columns([1.3,1,1])
        with a: aid=form_selector("Operator",names(people),"av_operator") if not people.empty else None
        with b: avdate=st.date_input("Work date",date.today()+timedelta(days=1))
        with c: avstatus=st.selectbox("Availability",["Available","Leave","Training","Unavailable"])
        avnotes=st.text_input("Reason / notes (optional)")
        if st.button("Save availability",type="primary",disabled=aid is None):
            try:db.mark_availability(aid,avdate,avstatus,avnotes);notify("Availability saved to scheduler constraints.")
            except Exception as exc:failed(exc)
        availability=db.query("SELECT v.work_date,o.name as operator,s.name as site,v.status,v.notes FROM availability v JOIN operators o ON o.id=v.operator_id JOIN sites s ON s.id=o.site_id ORDER BY v.work_date DESC")
        dfview(site_scope(availability,site_filter),h=280)
    with t4:
        heading("Daily target attainment")
        target_date=st.date_input("Reporting date",value=date.today()-timedelta(days=1),key="daily_target_date")
        report=an.daily_targets(people,ses,target_date.isoformat())
        if not report.empty:
            c1,c2,c3=st.columns(3)
            c1.metric("Scheduled workforce",len(report))
            c2.metric("Operators meeting target",int(report.target_status.eq("Met").sum()))
            c3.metric("Unmet recording hours",f"{report.gap_h.sum():.1f}h")
            dfview(report.rename(columns={"operator":"Operator","site":"Hub","target_h":"Target (h)","recorded_h":"Recorded (h)","gap_h":"Shortfall (h)","target_status":"Attainment"}),h=420)
            st.download_button("↓ Export daily target report",safe_export(report),"roboops_daily_targets.csv",mime="text/csv")
        st.caption("Targets compare recorded session hours with each active operator's configured daily target. Leave days are not automatically excluded from this report.")


def recordings():
    title("Recordings & quality assurance","Capture operator recording sessions, validate collection metrics and clear the review queue.","QUALITY SCORE = TRANSPARENT DEMO HEURISTIC")
    ses=site_scope(an.enriched_sessions(),site_filter)
    flagged=ses[ses.review_status.isin(["Needs Review","Rejected"])] if not ses.empty else ses
    a,b,c,d=st.columns(4)
    a.metric("Recording sessions",len(ses))
    b.metric("Uploaded data",f"{ses.uploaded_gb.sum():,.0f} GB" if not ses.empty else "0 GB")
    c.metric("Avg. quality",f"{ses.quality_score.mean():.1f}" if not ses.empty else "—")
    d.metric("Requires attention",len(flagged))
    tab1,tab2,tab3=st.tabs(["Quality monitor","Log recording","Review queue"])
    with tab1:
        left,right=st.columns([1.3,1],gap="large")
        with left:
            heading("Daily recording quality")
            if not ses.empty:
                roll=an.daily_rollup(ses)
                fig=px.line(roll,x="date",y="average_quality",markers=True)
                fig.add_hline(y=80,line_dash="dot",line_color="#ef96a4",annotation_text="Score alert threshold")
                fig.update_traces(line_color=COLORS[0],line_width=3)
                fig.update_layout(yaxis_range=[40,105],xaxis_title="Date",yaxis_title="Mean QA score")
                st.plotly_chart(theme(fig),use_container_width=True)
            else:st.info("No data for chart.")
        with right:
            heading("Quality disposition")
            if not ses.empty:
                agg=ses.review_status.value_counts().rename_axis("Review").reset_index(name="Sessions")
                fig=px.pie(agg,values="Sessions",names="Review",hole=.59,color_discrete_sequence=COLORS)
                st.plotly_chart(theme(fig),use_container_width=True)
        heading("Session ledger")
        filter_quality=st.multiselect("Review status filter",["Pending","Approved","Needs Review","Rejected"],default=["Pending","Approved","Needs Review","Rejected"])
        view=ses[ses.review_status.isin(filter_quality)] if not ses.empty else ses
        dfview(view,cols=["id","recorded_on","operator","mission","robot_type","site","duration_h","uploaded_gb","quality_score","frame_drop_pct","annotation_pct","review_status"],h=370)
        st.download_button("↓ Export filtered sessions (CSV)",safe_export(view),"roboops_sessions.csv",mime="text/csv")
    with tab2:
        heading("Record completed teleoperation session")
        ms=site_scope(an.enriched_missions(),site_filter)
        ms=ms[ms.status=="Active"] if not ms.empty else ms
        ops=db.query("SELECT * FROM operators WHERE status='Active'")
        stations=db.query("SELECT * FROM stations WHERE status='Online'")
        if ms.empty:st.info("Create an active mission first.")
        else:
            mission_id=form_selector("Mission",names(ms,"name"),"logmission")
            chosen=ms[ms.id==mission_id].iloc[0]
            eligible=ops[(ops.site_id==chosen.site_id)&(ops.skills.map(lambda k:chosen.robot_type in str(k).split(",")))]
            station_eligible=stations[(stations.site_id==chosen.site_id)&(stations.robot_type==chosen.robot_type)]
            if eligible.empty or station_eligible.empty:st.warning("No compatible active operator or online station. Update readiness in the relevant workspace.")
            else:
                with st.form("log_session_form",clear_on_submit=False):
                    a,b,c=st.columns(3)
                    with a:op_id=form_selector("Qualified operator",names(eligible))
                    with b:station_id=form_selector("Robot station",names(station_eligible,"code"))
                    with c:recorded=st.date_input("Recorded on",date.today(),max_value=date.today())
                    d,e=st.columns(2)
                    with d:duration=st.number_input("Session duration (hours)",min_value=.25,max_value=12.0,step=.25,value=2.0)
                    with e:upload=st.number_input("Upload volume (GB)",min_value=0.0,max_value=500.0,step=.5,value=4.5)
                    d,e,f=st.columns(3)
                    with d:drop=st.number_input("Frame drop (%)",min_value=0.0,max_value=100.0,step=.1,value=1.2)
                    with e:annotation=st.number_input("Annotation completeness (%)",min_value=0.0,max_value=100.0,step=1.0,value=96.0)
                    with f:sync=st.checkbox("Sensor sync passed",value=True)
                    notes=st.text_area("Operator notes",placeholder="Observations, failed runs, calibration issues...")
                    score=db.quality_formula(drop,annotation,sync)
                    st.info(f"Estimated QA score: {score}/100 · {'Needs Review' if db.quality_is_flagged(score,drop,annotation,sync) else 'Pending QA'}")
                    submit=st.form_submit_button("Save recording",type="primary",use_container_width=True)
                if submit:
                    try:db.log_session(mission_id,op_id,station_id,recorded,duration,upload,drop,annotation,sync,notes);notify("Recording saved. QA status calculated automatically.")
                    except Exception as exc:failed(exc)
        st.caption("The demonstration QA score is calculated from frame drops, annotation completeness and synchronization. It does not analyze uploaded video files.")
    with tab3:
        heading("Quality review inbox")
        pending=ses[ses.review_status.isin(["Needs Review","Pending"])] if not ses.empty else ses
        dfview(pending,cols=["id","recorded_on","operator","mission","quality_score","frame_drop_pct","annotation_pct","sync_ok","review_status"],h=310)
        if not pending.empty:
            choices={f"Session #{int(r.id)} · {r.operator} · {r.quality_score:.1f}/100":int(r.id) for r in pending.itertuples()}
            sid=form_selector("Select session for disposition",choices,"qa_sid")
            disposition=st.selectbox("Review outcome",["Approved","Needs Review","Rejected"])
            if st.button("Save QA review",type="primary"):
                try:db.update_field("sessions",sid,"review_status",disposition);notify("Recording review updated.")
                except Exception as exc:failed(exc)


def fleet():
    title("Fleet & logistics","Maintain an accurate view of field kits, fleet maintenance, transfers and delivery confirmation.")
    assets=site_scope(an.enriched_assets(),site_filter)
    shipping=db.query("""SELECT sh.id,a.tag,s1.name origin,s2.name destination,sh.carrier,sh.tracking_no,sh.status,sh.eta_date,sh.created_at
      FROM shipments sh JOIN assets a ON a.id=sh.asset_id
      JOIN sites s1 ON s1.id=sh.origin_site_id JOIN sites s2 ON s2.id=sh.destination_site_id ORDER BY sh.id DESC""")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Fleet assets",len(assets))
    c2.metric("Available",int(assets.status.eq("Available").sum()) if not assets.empty else 0)
    c3.metric("Maintenance",int(assets.status.eq("Maintenance").sum()) if not assets.empty else 0)
    c4.metric("In transit",int(shipping.status.eq("Dispatched").sum()) if not shipping.empty else 0)
    t1,t2,t3=st.tabs(["Asset register","Maintenance & assignment","Shipments"])
    with t1:
        heading("Equipment inventory")
        cat=st.multiselect("Equipment category",sorted(assets.category.unique().tolist()) if not assets.empty else [],default=[])
        dfview(assets[assets.category.isin(cat)] if cat else assets,cols=["id","tag","category","model","site","assigned_to","status","last_service"],h=370)
        with st.expander("+ Register new equipment"):
            with st.form("new_asset",clear_on_submit=True):
                tag=st.text_input("Unique asset tag",placeholder="RB-0099")
                category=st.selectbox("Type",["Camera Kit","Controller","Robot Battery","Edge Computer","Sensor Rig","Other"])
                model=st.text_input("Model",placeholder="Device make / model")
                location=form_selector("Current hub",site_dict,"asset_site")
                submitted=st.form_submit_button("Register equipment",type="primary")
            if submitted:
                try:db.add_asset(tag,category,model,location);notify("Equipment added to fleet register.")
                except Exception as exc:failed(exc)
    with t2:
        heading("Asset servicing and assignment")
        if not assets.empty:
            a,b=st.columns([1.4,1],gap="large")
            with a:
                selected=form_selector("Select asset",names(assets,"tag"),"asset_selected")
                state=st.selectbox("Operational status",["Available","Maintenance","Out of Service"])
                if st.button("Update status",type="primary"):
                    try:db.update_field("assets",selected,"status",state);notify("Asset status saved.")
                    except Exception as exc:failed(exc)
            with b:
                maintenance=assets[assets.status.isin(["Maintenance","Out of Service"])]
                st.metric("Service backlog",len(maintenance))
                st.caption("Use 'Available' once inspected, repaired and ready for field deployment.")
            dfview(assets[assets.status.isin(["Maintenance","Out of Service"])],cols=["tag","category","model","site","status","last_service"],h=260)
            heading("Assign or return field kit")
            allocable=assets[assets.status.isin(["Available","Assigned"])]
            if not allocable.empty:
                chosen_asset=form_selector("Equipment",names(allocable,"tag"),"allocation_asset")
                selected_asset=allocable[allocable.id==chosen_asset].iloc[0]
                workers=db.query("SELECT id,name,site_id FROM operators WHERE status='Active'")
                workers=workers[workers.site_id==int(selected_asset.site_id)]
                choices={"Return to hub inventory":None}
                choices.update({k:v for k,v in names(workers).items()})
                assigned=form_selector("Assign to",choices,"allocation_worker")
                if st.button("Save equipment allocation"):
                    try:db.assign_asset(chosen_asset,assigned);notify("Equipment allocation updated.")
                    except Exception as exc:failed(exc)
            else:st.info("No available or assigned equipment in this hub.")
    with t3:
        heading("Shipment tracking")
        dfview(shipping,cols=["id","tag","origin","destination","carrier","tracking_no","status","eta_date"],h=310)
        left,right=st.columns(2,gap="large")
        with left:
            heading("Dispatch equipment")
            can_ship=an.enriched_assets()
            can_ship=can_ship[can_ship.status!="In Transit"]
            if not can_ship.empty:
                with st.form("send_asset"):
                    asset_id=form_selector("Asset",names(can_ship,"tag"),"ship_asset")
                    asset=can_ship[can_ship.id==asset_id].iloc[0]
                    st.caption(f"Current origin: {asset.site}")
                    dest_options={k:v for k,v in site_dict.items() if v!=int(asset.site_id)}
                    dest_id=form_selector("Destination",dest_options,"ship_dest")
                    carrier=st.selectbox("Carrier",["BlueDart","Delhivery","DTDC","Internal Fleet","Other"])
                    track=st.text_input("Tracking ID",placeholder="Waybill number")
                    eta=st.date_input("Expected delivery",date.today()+timedelta(days=3))
                    submit=st.form_submit_button("Dispatch shipment",type="primary")
                if submit:
                    try:db.add_shipment(asset_id,int(asset.site_id),dest_id,carrier,track,eta);notify("Shipment dispatched; asset marked In Transit.")
                    except Exception as exc:failed(exc)
        with right:
            heading("Receive equipment")
            in_transit=shipping[shipping.status=="Dispatched"]
            if not in_transit.empty:
                ids={f"#{int(r.id)} · {r.tag} → {r.destination}":int(r.id) for r in in_transit.itertuples()}
                sid=form_selector("Awaiting delivery",ids,"receive_shipment")
                st.caption("Marking delivered moves the asset to its destination hub and makes it available.")
                if st.button("✓ Confirm receipt",type="primary"):
                    try:db.complete_shipment(sid);notify("Delivered. Asset inventory updated at destination.")
                    except Exception as exc:failed(exc)
            else:st.success("All shipments delivered.")


def incidents():
    title("Incident resolution desk","Log field disruptions, prioritize risk, assign ownership and close issues with an auditable resolution.")
    entries=site_scope(db.query("""SELECT i.*,s.name site,a.tag asset_tag FROM incidents i
       JOIN sites s ON s.id=i.site_id LEFT JOIN assets a ON a.id=i.asset_id ORDER BY i.id DESC"""),site_filter)
    a,b,c,d=st.columns(4)
    a.metric("Open",int(entries.status.eq("Open").sum()) if not entries.empty else 0)
    b.metric("In progress",int(entries.status.eq("In Progress").sum()) if not entries.empty else 0)
    c.metric("Resolved",int(entries.status.eq("Resolved").sum()) if not entries.empty else 0)
    d.metric("Critical unresolved",int(((entries.severity=="Critical") & (entries.status!="Resolved")).sum()) if not entries.empty else 0)
    t1,t2=st.tabs(["Active incident log","Report / resolve"])
    with t1:
        state=st.multiselect("Status",["Open","In Progress","Resolved"],default=["Open","In Progress"])
        listing=entries[entries.status.isin(state)] if not entries.empty else entries
        dfview(listing,cols=["id","title","category","severity","site","asset_tag","owner","status","reported_at","description","resolution"],h=435)
        heading("Issue categories")
        if not entries.empty:
            counts=entries.groupby(["category","status"],as_index=False).size()
            fig=px.bar(counts,x="category",y="size",color="status",barmode="group",color_discrete_sequence=COLORS)
            fig.update_layout(xaxis_title="",yaxis_title="Incident count")
            st.plotly_chart(theme(fig),use_container_width=True)
    with t2:
        left,right=st.columns(2,gap="large")
        with left:
            heading("Report incident")
            with st.form("incident_form",clear_on_submit=True):
                name=st.text_input("Incident title")
                category=st.selectbox("Category",["Hardware","Software","Data Quality","Connectivity","Logistics","Safety","Other"])
                severity=st.selectbox("Severity",["Medium","Low","High","Critical"])
                site_id=form_selector("Location",site_dict,"incident_site")
                owner=st.text_input("Assigned owner")
                detail=st.text_area("Incident notes")
                submitted=st.form_submit_button("Report incident",type="primary")
            if submitted:
                try:db.add_incident(name,category,severity,site_id,owner,detail);notify("Incident reported and added to queue.")
                except Exception as exc:failed(exc)
        with right:
            heading("Update incident")
            unresolved=entries[entries.status!="Resolved"] if not entries.empty else entries
            if not unresolved.empty:
                ids={f"#{int(r.id)} · {r.title}":int(r.id) for r in unresolved.itertuples()}
                iid=form_selector("Select incident",ids,"incident_selected")
                state=st.selectbox("New state",["In Progress","Resolved","Open"])
                resolution=st.text_area("Resolution / next action",placeholder="Root cause, action taken, escalation...")
                if st.button("Save incident update",type="primary"):
                    try:
                        db.update_field("incidents",iid,"status",state)
                        if resolution.strip():db.update_field("incidents",iid,"resolution",resolution)
                        notify("Incident updated.")
                    except Exception as exc:failed(exc)
            else:st.success("No unresolved incidents.")


def analytics():
    title("Analytics & reporting","Explore productivity by operator, site and robot type. Export the full operational dataset for further analysis.")
    ses=site_scope(an.enriched_sessions(),site_filter)
    mission=site_scope(an.enriched_missions(),site_filter)
    a,b=st.columns(2)
    with a:start=st.date_input("Reporting period · start",date.today()-timedelta(days=30),key="analytics_start")
    with b:end=st.date_input("Reporting period · end",date.today(),key="analytics_end")
    view=ses[(ses.recorded_on>=start.isoformat())&(ses.recorded_on<=end.isoformat())] if not ses.empty else ses
    x,y,z=st.columns(3)
    x.metric("Total recording time",f"{view.duration_h.sum():,.1f}h" if not view.empty else "0h")
    y.metric("Data volume",f"{view.uploaded_gb.sum():,.1f} GB" if not view.empty else "0 GB")
    z.metric("Non-flagged recordings",f"{100*view.review_status.isin(['Approved','Pending']).mean():.1f}%" if not view.empty else "—")
    a,b=st.columns(2,gap="large")
    with a:
        heading("Hours by field hub")
        if not view.empty:
            h=view.groupby("site",as_index=False).duration_h.sum()
            fig=px.bar(h,x="site",y="duration_h",color="site",color_discrete_sequence=COLORS,text="duration_h")
            fig.update_layout(showlegend=False,xaxis_title="",yaxis_title="Recorded hours")
            st.plotly_chart(theme(fig),use_container_width=True)
    with b:
        heading("Robot type contribution")
        if not view.empty:
            h=view.groupby("robot_type",as_index=False).uploaded_gb.sum()
            fig=px.bar(h,x="robot_type",y="uploaded_gb",color="robot_type",color_discrete_sequence=COLORS,text_auto=".0f")
            fig.update_layout(showlegend=False,xaxis_title="",yaxis_title="Uploaded data (GB)")
            st.plotly_chart(theme(fig),use_container_width=True)
    heading("Operator performance table")
    dfview(an.workforce_kpis(view).round(1),h=330)
    heading("Mission fulfillment")
    dfview(mission,cols=["name","site","priority","target_hours","recorded_hours","completion_pct","due_date","status"],h=300)
    heading("Export center")
    a,b=st.columns(2)
    with a:
        st.download_button("↓ Download filtered sessions CSV",data=safe_export(view),file_name="roboops_sessions_report.csv",mime="text/csv",use_container_width=True)
    with b:
        st.download_button("↓ Download complete SQLite tables (ZIP)",data=zip_export(),file_name="roboops_operations_export.zip",mime="application/zip",use_container_width=True)
    st.caption("CSV/ZIP exports contain the current locally stored data. They do not upload anything to an external server.")


def settings():
    title("Workspace settings","Understand the demo environment, inspect records and reset data when you want a clean walkthrough.")
    a,b=st.columns([1,1.25],gap="large")
    with a:
        heading("Environment")
        st.write("**Mode:** Local-first, fictional demonstration dataset")
        st.write("**Database:** SQLite (persistent between local app restarts)")
        st.write("**Robot feed:** No hardware connection or video stream")
        st.write("**Scheduling:** Rule-based two-hour slot allocations")
        st.write("**Quality scoring:** Transparent heuristic, not AI-based vision analysis")
        st.write("**Code provenance:** Adapted from an MIT-licensed production planning dashboard, with attribution preserved")
        st.write("**Storage location:**",str(db.db_location()))
    with b:
        heading("Database health")
        tbl=an.snapshots()
        rows=pd.DataFrame([{"Table":key,"Records":len(val)} for key,val in tbl.items()])
        dfview(rows,h=450)
    st.divider()
    heading("Reset demo records")
    st.warning("This replaces all current records, including changes you made locally, with a new synthetic dataset. Export before resetting if you want to keep your work.")
    confirm=st.checkbox("I understand that reset deletes the current local records",key="reset_check")
    if st.button("Reset to sample data",disabled=not confirm):
        try:
            db.reset_demo()
            st.session_state.pop("plan",None)
            notify("Demo database reset to the seed dataset.")
        except Exception as exc:failed(exc)


ROUTES={ALL_PAGES[0]:command_center,ALL_PAGES[1]:mission_planner,ALL_PAGES[2]:workforce,
        ALL_PAGES[3]:recordings,ALL_PAGES[4]:fleet,ALL_PAGES[5]:incidents,
        ALL_PAGES[6]:analytics,ALL_PAGES[7]:settings}
ROUTES[page]()
st.markdown("<div style='margin-top:32px;padding-top:15px;border-top:1px solid #25344c;color:#627e96;font-size:.76rem;text-align:right'>ROBOOPS  •  LOCAL-FIRST FIELD INTELLIGENCE  •  FICTIONAL DATA</div>",unsafe_allow_html=True)
