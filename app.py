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


def try_date(s: Optional[str]) -> Optional[date]:
    if not s:
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


def distinct_values(col: str) -> List[str]:
    with conn() as c:
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


# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()
# ---------- Project Editor ----------
st.markdown("---")
st.subheader("Project Editor")
# Load existing project list for editing
with conn() as c:
    df_projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

project_options = ["<New Project>"] + [
    f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()
]

selected_project = st.selectbox("Select Project to Edit", project_options)
# Load selected project record
loaded_project = None
if selected_project != "<New Project>":
    project_id = int(selected_project.split(" — ")[0])
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
    if not df.empty:
        loaded_project = df.iloc[0].to_dict()
# Load distinct values for dropdowns
pillar_list = distinct_values("pillar")
status_list = distinct_values("status")
owner_list = distinct_values("owner")

with st.form("project_form"):
    c1, c2 = st.columns(2)
# ---- ACTION BUTTONS (outside the form) ----
bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns([1, 1, 1, 1, 2])

new_clicked    = bcol1.button("New")
save_clicked   = bcol2.button("Save (Insert)")
update_clicked = bcol3.button("Update")
delete_clicked = bcol4.button("Delete")
clear_clicked  = bcol5.button("Clear")
    # LEFT COLUMN
# Pre-fill fields if editing
name_val = loaded_project["name"] if loaded_project else ""
pillar_val = loaded_project["pillar"] if loaded_project else ""
priority_val = loaded_project["priority"] if loaded_project else 5
owner_val = loaded_project["owner"] if loaded_project else ""
status_val = loaded_project["status"] if loaded_project else ""
start_val = try_date(loaded_project["start_date"]) if loaded_project else date.today()
due_val = try_date(loaded_project["due_date"]) if loaded_project else date.today()
desc_val = loaded_project["description"] if loaded_project else ""

project_name = c1.text_input("Name*", value=name_val)
project_pillar = c1.selectbox("Pillar*", [""] + pillar_list, index=([""]+pillar_list).index(pillar_val) if pillar_val in pillar_list else 0)
project_priority = c1.number_input("Priority", min_value=1, max_value=99, value=priority_val)

project_owner = c2.selectbox("Owner", [""] + owner_list, index=([""]+owner_list).index(owner_val) if owner_val in owner_list else 0)
project_status = c2.selectbox("Status", [""] + status_list, index=([""]+status_list).index(status_val) if status_val in status_list else 0)

start_date = c2.date_input("Start Date", value=start_val)
due_date = c2.date_input("Due Date", value=due_val)

description = st.text_area("Description", value=desc_val, height=120)

col_a, col_b, col_c = st.columns(3)
submitted_new = col_a.form_submit_button("Save New")
submitted_update = col_b.form_submit_button("Update")
submitted_delete = col_c.form_submit_button("Delete")

# ---- CRUD ACTIONS ----

# CREATE
if submitted_new:
    if not project_name or not project_pillar:
        st.error("Name and Pillar are required.")
    else:
        with conn() as c:
            c.execute(f"""
                INSERT INTO {TABLE}
                (name, pillar, priority, description, owner, status, start_date, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_name,
                project_pillar,
                project_priority,
                description,
                project_owner,
                project_status,
                to_iso(start_date),
                to_iso(due_date)
            ))
            c.commit()
        st.success("Project created!")
        st.rerun()

# UPDATE
if submitted_update and loaded_project:
    with conn() as c:
        c.execute(f"""
            UPDATE {TABLE}
            SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
            WHERE id=?
        """, (
            project_name,
            project_pillar,
            project_priority,
            description,
            project_owner,
            project_status,
            to_iso(start_date),
            to_iso(due_date),
            loaded_project["id"]
        ))
        c.commit()
    st.success("Project updated!")
    st.rerun()

# DELETE
if submitted_delete and loaded_project:
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (loaded_project["id"],))
        c.commit()
    st.warning("Project deleted.")
    st.rerun()
# ---- Global Filters ----
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

# ---- Derived Years ----
data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

# ---- Report Controls ----
st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])

year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"])
year_col = "start_year" if year_mode == "Start Year" else "due_year"

years = ["All"] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years)

top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5)

show_all = rc4.checkbox("Show ALL Reports", value=True)

# Individual toggles
if not show_all:
    show_kpi = rc4.checkbox("KPI Cards", True)
    show_pillar_chart = rc4.checkbox("Pillar Status Chart", True)
    show_roadmap = rc4.checkbox("Roadmap", True)
    show_table = rc4.checkbox("Projects Table", True)
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != "All":
    data = data[data[year_col] == int(year_f)]

# ---- KPI Cards ----
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)

    k1.metric("Projects", len(data))
    k2.metric("Completed", (data["status"].str.lower() == "done").sum())
    k3.metric("Ongoing", (data["status"].str.lower() != "done").sum())
    k4.metric("Distinct Pillars", data["pillar"].nunique())

# ---- Pillar Status Chart ----
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    status_df["state"] = status_df["status"].apply(
        lambda x: "Completed" if str(x).lower() == "done" else "Ongoing"
    )

    pillar_summary = (
        status_df.groupby(["pillar", "state"])
        .size()
        .reset_index(name="count")
    )

    if not pillar_summary.empty:
        fig = px.bar(
            pillar_summary,
            x="pillar",
            y="count",
            color="state",
            barmode="group",
            title="Projects by Pillar — Completed vs Ongoing",
        )
        st.plotly_chart(fig, use_container_width=True)

# ---- Top N per Pillar ----
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")

top_df = (
    data.sort_values("priority")
    .groupby("pillar")
    .head(top_n)
)

st.dataframe(top_df, use_container_width=True)

# ---- Roadmap (UNCHANGED LOGIC) ----
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

# ---- Projects Table ----
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    st.dataframe(data, use_container_width=True)

