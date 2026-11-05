"""
Streamlit dashboard for Weekly production planning.

Features:
- UI organized into "Planning" and "Demand" tabs.
- Day-by-day operator availability selectors for the chosen week.
- Button to run weekly ETL (generate proposals).
- Read-only weekly schedule view and a large-format Gantt chart.
- Summary table of all subsystems produced in the proposed plan.
- Demand tab with a weekly demand table and an interactive chart.
"""
from __future__ import annotations
import os
import re
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Use etl.py for backend logic
import etl as etl

# --- CONFIGURATION ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# ------------------------------
# Caching
# ------------------------------
@st.cache_data
def load_etl_data():
    """Cached function to load all source data from Excel files."""
    try:
        return etl.load_data()
    except FileNotFoundError as e:
        st.error(f"Failed to load source data: {e}. Please ensure Excel files are in {etl.DATA_DIR}")
        return None

# ------------------------------
# Helpers
# ------------------------------
def read_csv_safe(path: str) -> pd.DataFrame:
    """Safely reads a CSV, returning an empty DataFrame if it doesn't exist or is empty."""
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

# ------------------------------
# Main UI
# ------------------------------
def main():
    st.set_page_config(page_title="Weekly Production Planning", layout="wide")
    st.title("Weekly Production Planning")

    all_data = load_etl_data()
    if not all_data or 'products' not in all_data:
        st.error("Essential data ('products.xlsx') is missing. Please update etl.py and ensure all source files are present.")
        return

    subsystem_info = all_data["products"][["Product", "Subsystem", "SubsystemShortDesc"]].drop_duplicates()
    operator_info = all_data["training"][["Operator", "OperatorShortName"]].drop_duplicates()

    # --- Sidebar ---
    with st.sidebar:
        st.header("Configuration")
        
        the_date = st.date_input("Select a date to determine the week", value=datetime.today(), format="YYYY-MM-DD")
        monday = etl.week_monday(the_date)
        
        st.divider()
        st.header("Operator Availability for Week")
        
        available_operators_by_day = {}
        try:
            all_ops = etl.get_all_operators()
            op_map = {f"{short_name} ({code})": code for code, short_name in all_ops}
            
            for i in range(5):
                day = monday + timedelta(days=i)
                day_name = day.strftime("%A")
                with st.expander(f"{day_name} ({day.strftime('%Y-%m-%d')})"):
                    available_op_display = st.multiselect(
                        f"Available operators for {day_name}",
                        options=list(op_map.keys()),
                        default=list(op_map.keys()),
                        key=f"operator_select_{day}"
                    )
                    available_operators_by_day[day] = {op_map[disp] for disp in available_op_display}
        except Exception as e:
            st.error(f"Could not load operators: {e}")

        st.divider()
        st.header("Filters")
        year = st.selectbox("Year", [2025, 2026], index=monday.year - 2025)
        month = st.selectbox("Month", list(range(1, 13)), index=monday.month - 1)

        st.divider()
        st.subheader("ETL")
        if st.button("Generate Weekly Proposals"):
            with st.spinner("Running Weekly ETL..."):
                etl.generate_weekly_proposals(the_date, available_operators_by_day, n_proposals=3)
            st.success("Weekly proposals generated."); st.rerun()

    # --- Main Content Tabs ---
    planning_tab, demand_tab = st.tabs(["Planning", "Demand"])

    # --- Demand Tab ---
    with demand_tab:
        st.header("Demand Analysis")
        demand_summary = etl.summarize_demand(year, month)
        if not demand_summary.empty:
            st.subheader("Monthly-Weekly Demand")
            st.dataframe(demand_summary, use_container_width=True, hide_index=True)

            st.subheader("Weekly Demand Chart")
            weeks = sorted(demand_summary['Week'].unique())
            selected_week = st.select_slider("Select Week", options=weeks, value=weeks[0])

            week_demand_df = demand_summary[demand_summary['Week'] == selected_week]
            
            # MODIFIED: Removed the dashed line trace
            fig_demand = px.bar(
                week_demand_df,
                x='Product',
                y='WeeklyQty',
                title=f"Weekly Target for Week {selected_week}"
            )
            fig_demand.update_layout(xaxis_title="Product", yaxis_title="Target Quantity")
            st.plotly_chart(fig_demand, use_container_width=True)
        else:
            st.info("No demand data found for the selected Year and Month.")

    # --- Planning Tab ---
    with planning_tab:
        st.header("Operational Planning")
        
        proposal_prefix = f"planning_week_{monday.strftime('%Y%m%d')}_proposal"
        
        try:
            weekly_files = [f for f in os.listdir(OUTPUT_DIR) if f.startswith(proposal_prefix)]
            if not weekly_files:
                st.info("No proposals found. Configure availability and run the ETL."); return
        except FileNotFoundError:
            st.info("Output directory not found. Run the ETL to create it."); return

        prop_ids = sorted({int(re.search(r'_proposal(\d+)\.csv', p).group(1)) for p in weekly_files})
        st.subheader("Choose Proposal")
        prop_choice = st.radio(" ", [f"Proposal {i}" for i in prop_ids], horizontal=True, label_visibility="collapsed")
        chosen_prop_id = int(prop_choice.split()[-1])

        weekly_path = os.path.join(OUTPUT_DIR, f"{proposal_prefix}{chosen_prop_id}.csv")
        weekly_df_raw = read_csv_safe(weekly_path)

        if not weekly_df_raw.empty:
            weekly_df_display = pd.merge(weekly_df_raw, operator_info, on="Operator", how="left")
            weekly_df_display = pd.merge(weekly_df_display, subsystem_info, on=["Product", "Subsystem"], how="left")
            display_cols = ["Date", "OperatorShortName", "Product", "SubsystemShortDesc", "Workcell", "Start", "End"]
            
            st.subheader(f"Weekly Plan: Week of {monday.strftime('%Y-%m-%d')}")
            st.dataframe(weekly_df_display[[c for c in display_cols if c in weekly_df_display.columns]], use_container_width=True, hide_index=True)

            st.subheader("Weekly Gantt Chart")
            g_weekly = pd.merge(weekly_df_raw, operator_info, on="Operator", how="left")
            g_weekly = pd.merge(g_weekly, subsystem_info, on=["Product", "Subsystem"], how="left")
            g_weekly["Legend"] = g_weekly["Subsystem"].astype(str) + " - " + g_weekly["SubsystemShortDesc"].fillna("") + " - " + g_weekly["Workcell"].astype(str)
            g_weekly["Start"] = pd.to_datetime(g_weekly["Start"])
            
            def cum_hours(dt): 
                wd = int(dt.weekday()); base = sum([8.0, 8.0, 8.0, 8.0, 6.0][:wd])
                within = (dt - dt.replace(hour=8, minute=0, second=0, microsecond=0)).total_seconds() / 3600.0
                return base + within
            
            g_weekly["StartH"] = g_weekly["Start"].apply(cum_hours)
            g_weekly["DurH"] = g_weekly["DurationHours"]

            x_range_weekly = st.slider("Select hour range for weekly view", 0, 38, (0, 38))
            fig_weekly = px.bar(g_weekly, y="OperatorShortName", x="DurH", base="StartH", color="Legend", orientation='h', text="Legend")
            fig_weekly.update_yaxes(autorange="reversed", title_text="Operator")
            fig_weekly.update_xaxes(range=x_range_weekly, title_text="Week hours (Mon start)")
            
            # MODIFIED: Increase height and font size
            fig_weekly.update_layout(
                height=800,
                font=dict(size=14)
            )
            
            st.plotly_chart(fig_weekly, use_container_width=True)

            st.subheader("Weekly Production Summary")
            production_summary = weekly_df_display.groupby(['Product', 'Subsystem', 'SubsystemShortDesc']).size().reset_index(name='Total Produced')
            st.dataframe(production_summary, use_container_width=True, hide_index=True)
        else:
            st.info("The selected proposal contains no scheduled tasks for this week.")

if __name__ == "__main__":
    main()