from __future__ import annotations

# ==========================================================
# Digital Portfolio — FULL VALIDATED APP
# (Feb-22 validated logic + Project Editor + JJMD + Roadmap)
# ==========================================================

import re
from contextlib import contextmanager
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st
import sqlitecloud

# ==========================================================
# Streamlit config (must be first)
# ==========================================================
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("📊 Digital Portfolio")

# ==========================================================
# Constants / Presets (UNCHANGED)
# ==========================================================
TABLE = "projects"

ALL_LABEL = "All"
NEW_LABEL = "<New Project>"

PRESET_PILLARS = [
    "Digital Mindset",
    "Advanced Analytics",
    "Integration & Visualization",
    "Data Availability & Connectivity",
    "Smart Operations",
    "Vision Lab + Smart Operations",
]

PRESET_STATUSES = ["Idea", "Planned", "In Progress", "Completed"]
PLAINWARE_OPTIONS = [ALL_LABEL, "Yes", "No"]

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "pillar": "TEXT NOT NULL",
    "priority": "INTEGER DEFAULT 5",
    "description": "TEXT",
    "owner": "TEXT",
    "status": "TEXT",
    "start_date": "TEXT",
    "due_date": "TEXT",
    "plainsware_project": "TEXT DEFAULT 'No'",
    "plainsware_number": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

# ==========================================================
# Helpers (unchanged behavior)
# ==========================================================
def now_ts():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def safe_int(x, default=5):
    try:
        return int(x)
    except Exception:
        return default


def to_iso(d):
    return d.strftime("%Y-%m-%d") if d else ""


def try_date(v):
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except Exception:
        return None


def safe_index(options, value, default=0):
    return options.index(value) if value in options else default


def validate_plainsware(plainsware_project, plainsware_number):
    if str(plainsware_project).strip().lower() == "yes":
        if not plainsware_number:
            raise ValueError("Planisware Project Number is required.")
        value = str(plainsware_number).strip().upper()
        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Must be JJMD-1234567 format.")
        return value
    return None


# ==========================================================
# SQLiteCloud connection (safe)
# ==========================================================
def _get_sqlitecloud_url():
    url = (st.secrets.get("SQLITECLOUD_URL_PORTFOLIO") or "").strip()
    if not url:
        st.error("Missing SQLITECLOUD_URL_PORTFOLIO")
        st.stop()
    return url


@contextmanager
def conn():
    c = None
    try:
        c = sqlitecloud.connect(_get_sqlitecloud_url())
        db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()
        if db_name:
            c.execute(f'USE DATABASE "{db_name}"')
        yield c
    except Exception as e:
        st.error("Database connection failed")
        st.exception(e)
        st.stop()
    finally:
        if c:
            c.close()


# ==========================================================
# Schema safety (NO DATA LOSS)
# ==========================================================
def ensure_schema():
    with conn() as c:
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, pillar TEXT)"
        )
        cols = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)["name"].tolist()
        for col, ddl in EXPECTED_COLUMNS.items():
            if col not in cols:
                try:
                    c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
                except Exception:
                    st.error(f"Schema error adding column: {col}")
                    st.stop()

ensure_schema()

# ==========================================================
# Load data with filters
# ==========================================================
def fetch_df(filters):
    q = f"SELECT * FROM {TABLE}"
    args, where = [], []

    for col in ["pillar", "status", "owner", "plainsware_project"]:
        if filters.get(col) and filters[col] != ALL_LABEL:
            where.append(f"{col}=?")
            args.append(filters[col])

    if filters.get("priority") and filters["priority"] != ALL_LABEL:
        where.append("priority=?")
        args.append(int(filters["priority"]))

    if filters.get("search"):
        s = f"%{filters['search'].lower()}%"
        where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
        args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)

# ==========================================================
# Filters UI
# ==========================================================
st.sidebar.header("Filters")

pillar_f = st.sidebar.selectbox("Pillar", [ALL_LABEL] + PRESET_PILLARS)
status_f = st.sidebar.selectbox("Status", [ALL_LABEL] + PRESET_STATUSES)
owner_f = st.sidebar.text_input("Owner")
priority_f = st.sidebar.selectbox("Priority", [ALL_LABEL] + [str(i) for i in range(1, 10)])
plainsware_f = st.sidebar.selectbox("Planisware", PLAINWARE_OPTIONS)
search_f = st.sidebar.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f if owner_f else ALL_LABEL,
    priority=priority_f,
    plainsware_project=plainsware_f,
    search=search_f,
)

data = fetch_df(filters)

# ==========================================================
# Year Filter
# ==========================================================
st.subheader("🗓️ Year Filter")
mode = st.radio("Year Type", ["Start Year", "Due Year"], horizontal=True)

if not data.empty:
    data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
    data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year
    year_col = "start_year" if mode == "Start Year" else "due_year"
    years = [ALL_LABEL] + sorted(data[year_col].dropna().unique().tolist())
    year_f = st.selectbox("Year", years)
    if year_f != ALL_LABEL:
        data = data[data[year_col] == year_f]

# ==========================================================
# Project Editor (VALIDATED BEHAVIOR)
# ==========================================================
st.subheader("✏️ Project Editor")

with conn() as c:
    proj_list = pd.read_sql_query(f"SELECT id, name FROM {TABLE}", c)

project_opts = [NEW_LABEL] + [f"{r.id} — {r.name}" for r in proj_list.itertuples(index=False)]
selected = st.selectbox("Select Project", project_opts)

loaded = {}
pid = None

if selected != NEW_LABEL:
    pid = int(selected.split(" — ")[0])
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[pid])
    if not df.empty:
        loaded = df.iloc[0].to_dict()

col1, col2 = st.columns(2)

with col1:
    name = st.text_input("Name*", loaded.get("name", ""))
    pillar = st.selectbox("Pillar*", PRESET_PILLARS, index=safe_index(PRESET_PILLARS, loaded.get("pillar", "")))
    owner = st.text_input("Owner*", loaded.get("owner", ""))
    priority = st.number_input("Priority", 1, 99, safe_int(loaded.get("priority", 5)))
    desc = st.text_area("Description", loaded.get("description", ""))

with col2:
    status = st.selectbox("Status", [""] + PRESET_STATUSES, index=safe_index([""] + PRESET_STATUSES, loaded.get("status", "")))
    start_date = st.date_input("Start Date", try_date(loaded.get("start_date")) or date.today())
    due_date = st.date_input("Due Date", try_date(loaded.get("due_date")) or date.today())
    plainsware_project = st.selectbox("Planisware Project?", ["No", "Yes"], index=1 if loaded.get("plainsware_project") == "Yes" else 0)
    plainsware_number = st.text_input("Planisware #", loaded.get("plainsware_number", "")) if plainsware_project == "Yes" else ""

b1, b2, b3 = st.columns(3)

if b1.button("Save New"):
    pw = validate_plainsware(plainsware_project, plainsware_number)
    with conn() as c:
        c.execute(
            f"""INSERT INTO {TABLE}
            (name,pillar,priority,description,owner,status,start_date,due_date,plainsware_project,plainsware_number,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name,pillar,priority,desc,owner,status,to_iso(start_date),to_iso(due_date),plainsware_project,pw,now_ts(),now_ts())
        )
    st.success("Project saved")
    st.rerun()

if pid and b2.button("Update"):
    pw = validate_plainsware(plainsware_project, plainsware_number)
    with conn() as c:
        c.execute(
            f"""UPDATE {TABLE}
            SET name=?,pillar=?,priority=?,description=?,owner=?,status=?,start_date=?,due_date=?,plainsware_project=?,plainsware_number=?,updated_at=?
            WHERE id=?""",
            (name,pillar,priority,desc,owner,status,to_iso(start_date),to_iso(due_date),plainsware_project,pw,now_ts(),pid)
        )
    st.success("Project updated")
    st.rerun()

if pid and b3.button("Delete"):
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (pid,))
    st.warning("Project deleted")
    st.rerun()

# ==========================================================
# KPIs + Roadmap
# ==========================================================
st.subheader("📌 KPIs")

k1, k2 = st.columns(2)
k1.metric("Total Projects", len(data))
k2.metric("Completed", (data["status"] == "Completed").sum())

st.subheader("🗺️ Roadmap")

if not data.empty:
    rd = data.dropna(subset=["start_date", "due_date"]).copy()
    rd["Start"] = pd.to_datetime(rd["start_date"])
    rd["End"] = pd.to_datetime(rd["due_date"])

    if not rd.empty:
        fig = px.timeline(rd, x_start="Start", x_end="End", y="name", color="pillar")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No valid dates for roadmap")

st.subheader("📋 Projects")
st.dataframe(data, use_container_width=True)
