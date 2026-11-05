"""
ETL/Planning optimizer for shop-floor scheduling (Weekly Focus).

Reads Excel files from a configured directory and generates weekly planning proposals.
Constraints:
- Operators only work on modules they're trained for (from training.xlsx)
- Operators can be excluded via availability list (passed as parameter for each day).
- 8h workday Mon-Thu, 6h Fri, weekends off
- No overlapping assignments per operator or per workcell (UT)
- 15-minute time granularity
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Tuple, Set
import numpy as np
import pandas as pd

# --- CONFIGURATION ---
DATA_DIR = r"C:\Users\...\planning\data" # Path to the folder containing input Excel files
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output") # Output folder for generated proposals
TIME_STEP_MIN = 15 # Time granularity in minutes
START_TIME = time(8, 0) # Workday start time

# ------------------------------
# IO helpers
# ------------------------------

def _read_excel(name: str, sheet: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required file: {path}")
    return pd.read_excel(path, sheet_name=sheet)

def load_data() -> dict:
    """Load all Excel files and normalize column names."""
    demand = _read_excel("demand.xlsx", "demand")
    stations = _read_excel("stations.xlsx", "stations")
    times = _read_excel("times.xlsx", "times")
    training = _read_excel("training.xlsx", "training")
    products = _read_excel("products.xlsx", "products")
    
    demand = demand.rename(columns={"Any": "Year", "Mes": "Month", "CodiProjecte": "Product", "Unitats": "Quantity"})
    stations = stations.rename(columns={"CodiProjecte": "Product", "CodiModul": "Subsystem", "UT": "Workcell"})
    times = times.rename(columns={"CodiProjecte": "Product", "CodiModul": "Subsystem", "TempsEstandar": "Time"})
    training = training.rename(columns={"CodiProjecte": "Product", "CodiModul": "Subsystem", "Usuari": "Operator", "NomCurt": "OperatorShortName"})
    training["Trained"] = "Y"
    products = products.rename(columns={"CodiProjecte": "Product", "CodiModul": "Subsystem", "ModulCode": "SubsystemShortDesc"})
    
    return {"demand": demand, "times": times, "stations": stations, "training": training, "products": products}

def ensure_output():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------
# Time helpers
# ------------------------------

def dt_combine(d: date, t: time) -> datetime:
    return datetime.combine(d, t)

def round_up_to_step(minutes: int, step: int) -> int:
    return int(np.ceil(minutes / step) * step)

def business_days_in_month(year: int, month: int) -> List[date]:
    d = date(year, month, 1)
    days = []
    while d.month == month:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days

def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

# ------------------------------
# Demand/Tasks
# ------------------------------

def make_weekly_task_pool(demand_df: pd.DataFrame, times_df: pd.DataFrame, target_date: date, demand_multiplier: float = 1.0) -> pd.DataFrame:
    month, year = target_date.month, target_date.year
    biz_days = business_days_in_month(year, month)
    month_demand = demand_df[(demand_df["Year"] == year) & (demand_df["Month"] == month)]
    if month_demand.empty: return pd.DataFrame()

    subs_by_prod = times_df.groupby("Product")["Subsystem"].apply(list).to_dict()
    rows = []
    for _, r in month_demand.iterrows():
        prod, qty = r["Product"], int(np.ceil(r["Quantity"] * float(demand_multiplier)))
        if prod not in subs_by_prod: continue
        daily_target = int(np.ceil(qty / max(1, len(biz_days))))
        for _ in range(daily_target * 5):
            for sub in subs_by_prod[prod]:
                rows.append({"Product": prod, "Subsystem": sub})
    tasks = pd.DataFrame(rows)
    return tasks.merge(times_df[["Product", "Subsystem", "Time"]], on=["Product", "Subsystem"], how="left")

# ------------------------------
# Scheduling core
# ------------------------------

@dataclass
class Assignment:
    operator: str; product: str; subsystem: str; workcell: str; start: datetime; end: datetime; duration_h: float

def can_place(new_start: datetime, new_end: datetime, intervals: List[Tuple[datetime, datetime]]) -> bool:
    return all(new_end <= s or new_start >= e for s, e in intervals)

def place_next_slot(day_start: datetime, max_minutes: int, duration_h: float, step_min: int, occupied: List[Tuple[datetime, datetime]]) -> Tuple[datetime, datetime] | None:
    dur_min = round_up_to_step(int(duration_h * 60), step_min)
    if dur_min == 0: return None
    t = day_start
    end_of_day = day_start + timedelta(minutes=max_minutes)
    while t + timedelta(minutes=dur_min) <= end_of_day:
        cand_start, cand_end = t, t + timedelta(minutes=dur_min)
        if can_place(cand_start, cand_end, occupied): return cand_start, cand_end
        t += timedelta(minutes=step_min)
    return None

def schedule_day_with_remaining(target_date: date, tasks: pd.DataFrame, trainings: pd.DataFrame, stations: pd.DataFrame, available_operators: Set[str]) -> Tuple[List[Assignment], pd.DataFrame]:
    weekday = target_date.weekday()
    base_minutes = 480 if weekday < 4 else (360 if weekday == 4 else 0)
    if weekday >= 5 or base_minutes == 0: return [], tasks

    avail_min_per_op = {op: base_minutes for op in available_operators}
    trained = trainings[trainings["Trained"] == "Y"][["Operator", "Product", "Subsystem"]]
    tasks = tasks.merge(stations[["Product", "Subsystem", "Workcell"]], on=["Product", "Subsystem"], how="left").dropna(subset=["RemainingTime"]).copy().sort_values("RemainingTime", ascending=False)
    
    assignments, occ_by_op, occ_by_wc = [], {op: [] for op in available_operators}, {}
    remaining_rows = []
    
    for _, task in tasks.iterrows():
        prod, sub, wc, remain_h = task["Product"], task["Subsystem"], task["Workcell"], float(task["RemainingTime"])
        
        cand_ops = trained[(trained["Product"] == prod) & (trained["Subsystem"] == sub)]["Operator"].unique()
        cand_ops = [op for op in cand_ops if op in available_operators and avail_min_per_op.get(op, 0) > 0]
        
        if not cand_ops or remain_h <= 0:
            remaining_rows.append({"Product": prod, "Subsystem": sub, "RemainingTime": remain_h}); continue
        
        scheduled_this_task_h = 0.0
        
        # Prioritize operators with more available time
        for op in sorted(cand_ops, key=lambda o: avail_min_per_op.get(o, 0), reverse=True):
            if scheduled_this_task_h >= remain_h: break
            
            op_avail_min = avail_min_per_op.get(op, 0)
            if op_avail_min < TIME_STEP_MIN: continue

            # Determine the chunk of time to schedule for this operator
            task_rem_h = remain_h - scheduled_this_task_h
            op_avail_h = op_avail_min / 60.0
            schedulable_h = min(task_rem_h, op_avail_h)

            day_start = dt_combine(target_date, START_TIME)
            slot = place_next_slot(day_start, base_minutes, schedulable_h, TIME_STEP_MIN, occ_by_op[op])

            if slot:
                cand_start, cand_end = slot
                occ_by_wc.setdefault(wc, [])
                if can_place(cand_start, cand_end, occ_by_wc[wc]):
                    duration_h = (cand_end - cand_start).total_seconds() / 3600.0
                    assignments.append(Assignment(op, prod, sub, wc, cand_start, cand_end, duration_h))
                    
                    occ_by_op[op].append((cand_start, cand_end)); occ_by_op[op].sort()
                    occ_by_wc[wc].append((cand_start, cand_end)); occ_by_wc[wc].sort()
                    
                    used_min = int(duration_h * 60)
                    avail_min_per_op[op] -= used_min
                    scheduled_this_task_h += duration_h

        leftover_h = max(0.0, round(remain_h - scheduled_this_task_h, 2))
        if leftover_h > 0:
            remaining_rows.append({"Product": prod, "Subsystem": sub, "RemainingTime": leftover_h})

    return assignments, pd.DataFrame(remaining_rows)

def _aggregate_remaining(tasks: pd.DataFrame) -> pd.DataFrame:
    col = "RemainingTime" if "RemainingTime" in tasks.columns else "Time"
    return tasks.groupby(["Product", "Subsystem"], as_index=False)[col].sum().rename(columns={col: "RemainingTime"})

# ------------------------------
# Public API
# ------------------------------

def generate_weekly_proposals(target_date: date, available_operators_by_day: Dict[date, Set[str]], n_proposals: int = 3, demand_uncertainty: float = 0.1) -> List[str]:
    ensure_output()
    data = load_data()
    files = []
    monday = week_monday(target_date)

    for i in range(1, n_proposals + 1):
        dem_mult = float(np.random.uniform(1 - demand_uncertainty, 1 + demand_uncertainty))
        base_tasks = make_weekly_task_pool(data["demand"], data["times"], monday, demand_multiplier=dem_mult)
        week_path = os.path.join(OUTPUT_DIR, f"planning_week_{monday.strftime('%Y%m%d')}_proposal{i}.csv")
        
        if base_tasks.empty:
            pd.DataFrame().to_csv(week_path, index=False); files.append(week_path); continue
        
        remaining = _aggregate_remaining(base_tasks)
        all_assignments = []
        for offset in range(5):
            d = monday + timedelta(days=offset)
            avail_ops = available_operators_by_day.get(d, set())
            if not avail_ops or remaining.empty: continue
            
            tasks_with_times = remaining.merge(data["times"], on=["Product", "Subsystem"], how="left")
            daily_assigns, rem_after = schedule_day_with_remaining(d, tasks_with_times, data["training"], data["stations"], avail_ops)
            all_assignments.extend(daily_assigns)
            remaining = rem_after

        rows = [{"Date": a.start.strftime("%Y-%m-%d"), "ProposalId": i, "Operator": a.operator, "Product": a.product,
                 "Subsystem": a.subsystem, "Workcell": a.workcell, "Start": a.start.strftime("%Y-%m-%d %H:%M"),
                 "End": a.end.strftime("%Y-%m-%d %H:%M"), "DurationHours": round(a.duration_h, 2)} for a in all_assignments]
        
        pd.DataFrame(rows).to_csv(week_path, index=False); files.append(week_path)
    return files

def summarize_demand(year: int, month: int) -> pd.DataFrame:
    data = load_data()
    dmd = data["demand"]
    month_df = dmd[(dmd["Year"] == year) & (dmd["Month"] == month)].copy()
    if month_df.empty: return pd.DataFrame()
    
    days = business_days_in_month(year, month)
    iso_weeks = sorted({d.isocalendar().week for d in days})
    out = []
    for _, r in month_df.iterrows():
        monthly = int(r["Quantity"])
        per_week = int(np.ceil(monthly / max(1, len(iso_weeks))))
        for ww in iso_weeks:
            out.append({"Month": month, "Product": r["Product"], "ProductDesc": r.get("DescripcioProjecte", ""),
                        "MonthlyQty": monthly, "Week": ww, "WeeklyQty": per_week})
    return pd.DataFrame(out)

def get_all_operators() -> List[tuple]:
    data = load_data()
    tr = data["training"][["Operator", "OperatorShortName"]].drop_duplicates().fillna("N/A")
    return [(row["Operator"], row["OperatorShortName"]) for _, row in tr.iterrows()]