# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------

import os
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = "portfolio.db"
TABLE = "projects"


# ---------- Utilities ----------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def try_date(s: Optional[str]) -> Optionalif not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args, where = [], []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != "All":
                where.append(f"{col} = ?")
                args.append(filters[col])

        if filters.get("priority") and filters["priority"] != "All":
            where.append("CAST(priority AS TEXT) = ?")
            args.append(str(filters["priority"]))

        if filters.get("search"):
            s = f"%{filters['search'].lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(start_date,''), COALESCE(due_date,'')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def distinct_values(col: str) -> Listwith conn() as c:
        df = pd.read_sql_query(
            f"""
            SELECT DISTINCT {col}
            FROM {TABLE}
            WHERE {col} IS NOT NULL AND TRIM({col}) <> ''
            ORDER BY {col}
            """,
            c,
        )
    return df[col].dropna().astype(str).tolist()


# ----------------------------------------------------------
#                STREAMLIT APP
# ----------------------------------------------------------

st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

# ----------------------------------------------------------
#                PROJECT EDITOR (CRUD FORM)
# ----------------------------------------------------------
st.markdown("## Project Editor")

# Load existing project list
with conn() as c:
    existing = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

options = ["<New Project>"] + existing["name"].tolist()
selected = st.selectbox("Select Project", options)

# Load selected row
if selected == "<New Project>":
    project = dict(
        id=None,
        name="",
        pillar="",
        priority=1,
        description="",
        owner="",
        status="",
        start_date="",
        due_date="",
    )
else:
    row = existing[existing["name"] == selected].iloc[0]
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id = ?", c, params=[row["id"]])
    project = df.iloc[0].to_dict()

# ---- Form Layout ----
left, right = st.columns([2, 2])

with left:
    name = st.text_input("Name*", value=project["name"])
    pillar = st.selectbox("Pillar*", [""] + distinct_values("pillar"), index=0)
    priority = st.number_input("Priority", 1, 10, value=int(project["priority"] or 1))
    description = st.text_area("Description", project.get("description", ""))

with right:
    owner = st.text_input("Owner", project.get("owner", ""))
    status = st.selectbox("Status", [""] + distinct_values("status"))
    start_date = st.text_input("Start (YYYY-MM-DD)", project.get("start_date", ""))
    due_date = st.text_input("Due (YYYY-MM-DD)", project.get("due_date", ""))

# ---- Editor Buttons ----
b1, b2, b3, b4 = st.columns(4)

# SAVE / UPDATE
if b1.button("New / Save"):
    with conn() as c:
        if selected == "<New Project>":
            c.execute(
                f"""INSERT INTO {TABLE}
                (name, pillar, priority, description, owner, status, start_date, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, pillar, priority, description, owner, status, start_date, due_date),
            )
            st.success("Project added.")
        else:
            c.execute(
                f"""UPDATE {TABLE}
                SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                start_date=?, due_date=?
                WHERE id=?""",
                (name, pillar, priority, description, owner, status,
                 start_date, due_date, project["id"]),
            )
            st.success("Project updated.")

# DELETE
if b2.button("Delete") and selected != "<New Project>":
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project["id"],))
    st.warning("Project deleted.")

# CLEAR
if b3.button("Clear"):
    st.experimental_rerun()


# ----------------------------------------------------------
#                GLOBAL FILTERS
# ----------------------------------------------------------

st.markdown("---")
colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = ["All"] + distinct_values("pillar")
statuses = ["All"] + distinct_values("status")
owners = ["All"] + distinct_values("owner")
priority_vals = distinct_values("priority")
priority_opts = ["All"] + sorted(set(priority_vals)) if priority_vals else ["All"]

pillar_f = colF1.selectbox("Pillar", pillars)
status_f = colF2.selectbox("Status", statuses)
owner_f = colF3.selectbox("Owner", owners)
priority_f = colF4.selectbox("Priority", priority_opts)
search_f = colF6.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    search=search_f,
)

data = fetch_df(filters)

# Derived Years
data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

# ----------------------------------------------------------
#                REPORT CONTROLS
# ----------------------------------------------------------

st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])

year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"])
year_col = "start_year" if year_mode == "Start Year" else "due_year"

years = ["All"] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years)

top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5)
show_all = rc4.checkbox("Show ALL Reports", value=True)

if not show_all:
    show_kpi = rc4.checkbox("KPI Cards", True)
    show_pillar_chart = rc4.checkbox("Pillar Status Chart", True)
    show_roadmap = rc4.checkbox("Roadmap", True)
    show_table = rc4.checkbox("Projects Table", True)
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != "All":
    data = data[data[year_col] == int(year_f)]

# ----------------------------------------------------------
#                REPORTS
# ----------------------------------------------------------

# KPI CARDS
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Projects", len(data))
    k2.metric("Completed", (data["status"].str.lower() == "done").sum())
    k3.metric("Ongoing", (data["status"].str.lower() != "done").sum())
    k4.metric("Distinct Pillars", data["pillar"].nunique())

# PILLAR STATUS CHART
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    status_df["state"] = status_df["status"].apply(
        lambda x: "Completed" if str(x).lower() == "done" else "Ongoing"
    )

    summary = (
        status_df.groupby(["pillar", "state"])
        .size()
        .reset_index(name="count")
    )

    if not summary.empty:
        fig = px.bar(
            summary,
            x="pillar",
            y="count",
            color="state",
            barmode="group",
            title="Projects by Pillar — Completed vs Ongoing",
        )
        st.plotly_chart(fig, use_container_width=True)

# TOP N PER PILLAR
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")

top_df = (
    data.sort_values("priority")
    .groupby("pillar")
    .head(top_n)
)

st.dataframe(top_df, use_container_width=True)

# ROADMAP
if show_roadmap:
    st.markdown("---")
    st.subheader("Roadmap")

    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt["start_date"], errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt["due_date"], errors="coerce")
    gantt = gantt.dropna(subset=["Start", "Finish"])

    if not gantt.empty:
        fig = px.timeline(
            gantt,
            x_start="Start",
            x_end="Finish",
            y="name",
            color="pillar",
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

# PROJECT TABLE
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    st.dataframe(data, use_container_width=True)
