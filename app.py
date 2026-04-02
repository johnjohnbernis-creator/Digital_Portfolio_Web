from __future__ import annotations

# ==========================================================
# Digital Portfolio — Final Stable Version
# Roadmap ALWAYS visible | Priority sorted | Editor + Report
# ==========================================================

import re
from contextlib import contextmanager
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import streamlit as st
import sqlitecloud

# ==========================================================
# Streamlit config
# ==========================================================
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("📊 Digital Portfolio")

# ==========================================================
# Constants
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
# Helpers
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
# SQLiteCloud connection
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
                c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")

ensure_schema()

# ==========================================================
# Data loading
# ==========================================================
def fetch_all():
    with conn() as c:
        return pd.read_sql_query(f"SELECT * FROM {TABLE}", c)


def fetch_filtered(filters):
    q = f"SELECT * FROM {TABLE}"
    args, where = [], []

    if filters["pillar"] != ALL_LABEL:
        where.append("pillar=?")
        args.append(filters["pillar"])
    if filters["status"] != ALL_LABEL:
        where.append("status=?")
        args.append(filters["status"])
    if filters["priority"] != ALL_LABEL:
        where.append("priority=?")
        args.append(int(filters["priority"]))
    if filters["search"]:
        s = f"%{filters['search'].lower()}%"
        where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
        args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)

# ==========================================================
# Sidebar Filters
# ==========================================================
st.sidebar.header("Filters")

filters = {
    "pillar": st.sidebar.selectbox("Pillar", [ALL_LABEL] + PRESET_PILLARS),
    "status": st.sidebar.selectbox("Status", [ALL_LABEL] + PRESET_STATUSES),
    "priority": st.sidebar.selectbox("Priority", [ALL_LABEL] + [str(i) for i in range(1, 10)]),
    "search": st.sidebar.text_input("Search"),
}

data_all = fetch_all()                     # ✅ Roadmap source (never filtered)
data_filtered = fetch_filtered(filters)    # ✅ Table / KPIs / Report

# ==========================================================
# Project Editor
# ==========================================================
st.subheader("✏️ Project Editor")

with conn() as c:
    plist = pd.read_sql_query(f"SELECT id, name FROM {TABLE}", c)

opts = [NEW_LABEL] + [f"{r.id} — {r.name}" for r in plist.itertuples(index=False)]
sel = st.selectbox("Select Project", opts)

loaded, pid = {}, None
if sel != NEW_LABEL:
    pid = int(sel.split(" — ")[0])
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[pid])
    if not df.empty:
        loaded = df.iloc[0].to_dict()

c1, c2 = st.columns(2)

with c1:
    name = st.text_input("Name*", loaded.get("name", ""))
    pillar = st.selectbox("Pillar*", PRESET_PILLARS, index=PRESET_PILLARS.index(loaded.get("pillar")) if loaded.get("pillar") in PRESET_PILLARS else 0)
    owner = st.text_input("Owner*", loaded.get("owner", ""))
    priority = st.number_input("Priority", 1, 99, safe_int(loaded.get("priority", 5)))
    desc = st.text_area("Description", loaded.get("description", ""))

with c2:
    status = st.selectbox("Status", [""] + PRESET_STATUSES)
    sd = st.date_input("Start Date", try_date(loaded.get("start_date")) or date.today())
    dd = st.date_input("Due Date", try_date(loaded.get("due_date")) or date.today())
    pw = st.selectbox("Planisware Project?", ["No", "Yes"])
    pwn = st.text_input("Planisware #", loaded.get("plainsware_number", "")) if pw == "Yes" else ""

b1, b2, b3 = st.columns(3)

if b1.button("Save New"):
    pwn_db = validate_plainsware(pw, pwn)
    with conn() as c:
        c.execute(
            f"""INSERT INTO {TABLE}
            (name,pillar,priority,description,owner,status,start_date,due_date,plainsware_project,plainsware_number,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name,pillar,priority,desc,owner,status,to_iso(sd),to_iso(dd),pw,pwn_db,now_ts(),now_ts())
        )
    st.success("Project created")
    st.rerun()

if pid and b2.button("Update"):
    pwn_db = validate_plainsware(pw, pwn)
    with conn() as c:
        c.execute(
            f"""UPDATE {TABLE}
            SET name=?,pillar=?,priority=?,description=?,owner=?,status=?,start_date=?,due_date=?,plainsware_project=?,plainsware_number=?,updated_at=?
            WHERE id=?""",
            (name,pillar,priority,desc,owner,status,to_iso(sd),to_iso(dd),pw,pwn_db,now_ts(),pid)
        )
    st.success("Project updated")
    st.rerun()

if pid and b3.button("Delete"):
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (pid,))
    st.warning("Project deleted")
    st.rerun()

# ==========================================================
# KPIs
# ==========================================================
st.subheader("📌 KPIs")

k1, k2, k3 = st.columns(3)
k1.metric("Projects", len(data_filtered))
k2.metric("Completed", (data_filtered["status"] == "Completed").sum())
k3.metric("Avg Priority", round(data_filtered["priority"].mean(), 1) if not data_filtered.empty else 0)

# ==========================================================
# ROADMAP — ALWAYS VISIBLE + PRIORITY SORT ✅
# ==========================================================
st.subheader("🗺️ Roadmap (Priority Sorted)")

rm = data_all.copy()
rm["Start"] = pd.to_datetime(rm["start_date"], errors="coerce")
rm["End"] = pd.to_datetime(rm["due_date"], errors="coerce")
rm = rm.dropna(subset=["Start", "End"])

rm = rm.sort_values(by=["priority", "Start", "name"])

if rm.empty:
    st.info("No projects have valid Start & Due dates for roadmap.")
else:
    fig = px.timeline(
        rm,
        x_start="Start",
        x_end="End",
        y="name",
        color="pillar",
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

# ==========================================================
# REPORT SECTION ✅
# ==========================================================
st.subheader("📑 Report")

report_df = data_filtered.sort_values(by=["priority", "pillar", "name"])
st.dataframe(report_df, use_container_width=True)

st.download_button(
    "⬇️ Download Report (CSV)",
    data=report_df.to_csv(index=False).encode("utf-8"),
    file_name="digital_portfolio_report.csv",
    mime="text/csv",
)

