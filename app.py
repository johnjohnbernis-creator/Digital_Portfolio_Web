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


def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _rerun():
    # Streamlit newer API: st.rerun(); fallback: st.experimental_rerun()
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_schema():
    """
    Create table if it doesn't exist. If your DB already exists with a different schema,
    comment this out and adapt CRUD below to match your columns.
    """
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT NOT NULL,
                priority INTEGER,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,    -- ISO: YYYY-MM-DD
                due_date TEXT       -- ISO: YYYY-MM-DD
            )
            """
        )
        c.commit()


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


# ---------- CRUD Helpers ----------
def insert_project(rec: Dict[str, Any]) -> int:
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            f"""
            INSERT INTO {TABLE}
            (name, pillar, priority, description, owner, status, start_date, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.get("name"),
                rec.get("pillar"),
                _safe_int(rec.get("priority")),
                rec.get("description"),
                rec.get("owner"),
                rec.get("status"),
                rec.get("start_date") or None,
                rec.get("due_date") or None,
            ),
        )
        c.commit()
        return cur.lastrowid


def update_project(project_id: int, rec: Dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            f"""
            UPDATE {TABLE}
            SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
            WHERE id=?
            """,
            (
                rec.get("name"),
                rec.get("pillar"),
                _safe_int(rec.get("priority")),
                rec.get("description"),
                rec.get("owner"),
                rec.get("status"),
                rec.get("start_date") or None,
                rec.get("due_date") or None,
                project_id,
            ),
        )
        c.commit()


def delete_project(project_id: int) -> None:
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project_id,))
        c.commit()


def fetch_one_by_id(project_id: int) -> Optional[Dict[str, Any]]:
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
    if df.empty:
        return None
    return df.iloc[0].to_dict()


# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# Ensure DB and schema exist (creates DB file if missing)
ensure_schema()

# ---------- Project Editor (Form + Buttons) ----------
st.markdown("---")
st.subheader("Project")

# Keep current project id in session_state
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None

# Select existing project to load or start new
with conn() as c:
    df_names = pd.read_sql_query(
        f"SELECT id, name FROM {TABLE} ORDER BY name COLLATE NOCASE", c
    )

project_options = ["<New Project>"] + [
    f"{int(r['id'])} — {r['name']}" for _, r in df_names.iterrows()
]
sel = st.selectbox("Load existing", project_options, index=0)

if sel == "<New Project>":
    st.session_state.current_project_id = None
else:
    try:
        st.session_state.current_project_id = int(sel.split(" — ")[0])
    except Exception:
        st.session_state.current_project_id = None

loaded = fetch_one_by_id(st.session_state.current_project_id) if st.session_state.current_project_id else {}

# Inputs arranged roughly like your screenshot
with st.form("project_form", clear_on_submit=False):
    lc1, lc2 = st.columns(2)

    # Name / Pillar / Priority (left)
    name = lc1.text_input("Name*", value=str(loaded.get("name", "")))

    # Pillar options from data; include loaded value if it's custom
    pillar_options = sorted(set([""] + distinct_values("pillar")))
    if loaded.get("pillar") and loaded["pillar"] not in pillar_options:
        pillar_options.append(loaded["pillar"])
    pillar_index = pillar_options.index(loaded["pillar"]) if loaded.get("pillar") in pillar_options else 0
    pillar = lc1.selectbox("Pillar*", options=pillar_options, index=pillar_index)

    priority_default = _safe_int(loaded.get("priority"), 3)
    priority = lc1.number_input("Priority", min_value=1, max_value=99, value=priority_default, step=1)

    # Owner / Status / Dates (right)
    owner = lc2.text_input("Owner", value=str(loaded.get("owner", "")))

    status_defaults = ["Idea", "Planned", "In Progress", "Blocked", "Done"]
    for s in distinct_values("status"):
        if s not in status_defaults:
            status_defaults.append(s)
    status_index = status_defaults.index(loaded.get("status")) if loaded.get("status") in status_defaults else 0
    status = lc2.selectbox("Status", options=status_defaults, index=status_index)

    start_date = lc2.text_input("Start (YYYY-MM-DD)", value=str(loaded.get("start_date") or ""))
    due_date = lc2.text_input("Due (YYYY-MM-DD)", value=str(loaded.get("due_date") or ""))

    # Description full width
    description = st.text_area("Description", value=str(loaded.get("description", "")), height=120)

    # --- Button row (as requested) ---
    st.write("")  # small spacer
    bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns([1, 1, 1, 1, 2])
    new_clicked     = bcol1.form_submit_button("New")
    save_clicked    = bcol2.form_submit_button("Save (Insert)")
    update_clicked  = bcol3.form_submit_button("Update")
    delete_clicked  = bcol4.form_submit_button("Delete")
    clear_clicked   = bcol5.form_submit_button("Clear")

    # Pack current form values
    rec = dict(
        name=name.strip(),
        pillar=pillar.strip(),
        priority=priority,
        description=description.strip(),
        owner=owner.strip(),
        status=status.strip(),
        start_date=to_iso(try_date(start_date)) if try_date(start_date) else (start_date.strip() or None),
        due_date=to_iso(try_date(due_date)) if try_date(due_date) else (due_date.strip() or None),
    )

    def missing_required(r: Dict[str, Any]) -> Optional[str]:
        if not r["name"]:
            return "Name is required."
        if not r["pillar"]:
            return "Pillar is required."
        return None

    # --- Button handlers ---
    if new_clicked:
        st.session_state.current_project_id = None
        st.success("New project started. Fill the fields and click 'Save (Insert)'.")
        _rerun()

    if save_clicked:
        err = missing_required(rec)
        if err:
            st.error(err)
            st.stop()
        new_id = insert_project(rec)
        st.session_state.current_project_id = new_id
        st.success(f"Project inserted with id {new_id}.")
        _rerun()

    if update_clicked:
        if not st.session_state.current_project_id:
            st.warning("No project is loaded. Choose one or click 'Save (Insert)' for a new record.")
            st.stop()
        err = missing_required(rec)
        if err:
            st.error(err)
            st.stop()
        update_project(st.session_state.current_project_id, rec)
        st.success(f"Project {st.session_state.current_project_id} updated.")
        _rerun()

    if delete_clicked:
        if not st.session_state.current_project_id:
            st.warning("No project is loaded to delete.")
            st.stop()
        delete_project(st.session_state.current_project_id)
        st.session_state.current_project_id = None
        st.success("Project deleted.")
        _rerun()

    if clear_clicked:
        # Clear fields by resetting loaded id and re-running
        st.session_state.current_project_id = None
        st.success("Cleared fields.")
        _rerun()


# ---------- Global Filters (drive reports) ----------
st.markdown("---")
st.subheader("Filters")

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
    data.sort_values("priority", na_position="last")
    .groupby("pillar", as_index=False, sort=False)
    .head(top_n)
)

st.dataframe(top_df, use_container_width=True)

# ---- Roadmap ----
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
