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


def table_exists(table_name: str) -> bool:
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
            (table_name,),
        )
        return cur.fetchone() is not None


def column_exists(table_name: str, col_name: str) -> bool:
    with conn() as c:
        cur = c.cursor()
        cur.execute(f"PRAGMA table_info('{table_name}')")
        cols = [row[1] for row in cur.fetchall()]  # row[1] is the column name
        return col_name in cols


def safe_migrate():
    """
    Add missing columns safely, but only if the DB file and table already exist.
    This prevents ALTER TABLE errors on a cold start.
    """
    if not os.path.exists(DB_PATH):
        return
    if not table_exists(TABLE):
        return

    with conn() as c:
        cur = c.cursor()

        # Ensure created_at
        if not column_exists(TABLE, "created_at"):
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN created_at TEXT;")

        # Ensure updated_at
        if not column_exists(TABLE, "updated_at"):
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN updated_at TEXT;")

        # Ensure progress
        if not column_exists(TABLE, "progress"):
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN progress INTEGER DEFAULT 0;")

        # Ensure progress_status
        if not column_exists(TABLE, "progress_status"):
            cur.execute(
                f"ALTER TABLE {TABLE} ADD COLUMN progress_status TEXT DEFAULT '';"
            )


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


# ---------- Priority Color ----------
def priority_color(p):
    try:
        p = int(p)
    except Exception:
        return "gray"
    if p == 1:
        return "red"
    if p in (2, 3):
        return "orange"
    if p in (4, 5, 6):
        return "gold"
    return "green"


def highlight_priority(val):
    return f"color: {priority_color(val)}; font-weight:bold;"


# ---------- Progress Color ----------
def progress_color(p):
    try:
        p = int(p)
    except Exception:
        return "gray"
    if p <= 30:
        return "red"
    if p <= 70:
        return "gold"
    return "green"


# ----------------------------------------------------------
#                STREAMLIT APP
# ----------------------------------------------------------

st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# Early checks
if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

# Perform safe migrations now that DB exists
safe_migrate()

if not table_exists(TABLE):
    st.error(f"Required table '{TABLE}' not found in database.")
    st.stop()


# ----------------------------------------------------------
#                      TABS
# ----------------------------------------------------------

tab_editor, tab_dashboard, tab_roadmap = st.tabs(
    ["🛠 Editor", "📊 Dashboard", "🗺 Roadmap"]
)

# ----------------------------------------------------------
#                   TAB: EDITOR
# ----------------------------------------------------------

with tab_editor:

    st.markdown("## Project Editor")

    with conn() as c:
        existing = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

    options = ["New Project"] + existing["name"].tolist()
    selected = st.selectbox("Select Project", options)

    # ---------- New Project Case ----------
    if selected == "New Project":
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
            progress=0,
            progress_status=""
        )

    else:
        # ---------- SAFE PROJECT LOADING ----------
        pid_row = existing[existing["name"] == selected]

        if pid_row.empty:
            st.warning("The selected project no longer exists. Refreshing…")
            st.rerun()

        pid = pid_row.iloc[0]["id"]

        with conn() as c:
            df = pd.read_sql_query("SELECT * FROM projects WHERE id=?", c, params=[pid])

        if df.empty:
            st.warning("Project record missing. Refreshing…")
            st.rerun()

        project = df.iloc[0].to_dict()

    # ---------- Parse Dates ----------
    def parse_date(d, fallback_today=True):
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except Exception:
            return date.today() if fallback_today else None

    start_val = parse_date(project.get("start_date"))
    due_val = parse_date(project.get("due_date"))

    colA, colB = st.columns([2, 2])

    # ---------- LEFT SIDE ----------
    with colA:
        name = st.text_input("Name*", project["name"])
        pillars_list = [""] + (distinct_values("pillar") or [])
        pillar = st.selectbox("Pillar*", pillars_list)
        priority = st.number_input("Priority", 1, 10, int(project["priority"] or 1))
        description = st.text_area("Description", project.get("description", ""))

    # ---------- RIGHT SIDE ----------
    with colB:
        owner = st.text_input("Owner", project.get("owner", ""))
        statuses_list = [""] + (distinct_values("status") or [])
        status = st.selectbox("Status", statuses_list)
        start_date = st.date_input("Start Date", value=start_val)
        due_date = st.date_input("Due Date", value=due_val)
        progress = st.slider("Progress (%)", 0, 100, int(project.get("progress", 0)))

        st.text_input(
            "Update Tag (automatic)",
            project.get("progress_status", ""),
            disabled=True
        )

    # ---------- Clean Inputs ----------
    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    pillar_clean = pillar.strip() or None
    status_clean = status.strip() or None
    owner_clean = owner.strip() or None

    c1, c2, c3 = st.columns(3)

    # ---------- SAVE ----------
    if c1.button("New / Save"):

        if not name.strip():
            st.error("Name is required.")
            st.stop()

        if not pillar_clean:
            st.error("Pillar is required.")
            st.stop()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"Updated on {now}" if project["id"] else f"Created on {now}"

        with conn() as c:
            if selected == "New Project":
                c.execute(
                    f"""
                    INSERT INTO {TABLE}
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     created_at, updated_at, progress, progress_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, pillar_clean, priority, description, owner_clean,
                        status_clean, start_str, due_str,
                        now, now, progress, tag
                    )
                )
                st.success("Project added.")
            else:
                c.execute(
                    f"""
                    UPDATE {TABLE}
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?
                    WHERE id=?
                    """,
                    (
                        name, pillar_clean, priority, description, owner_clean,
                        status_clean, start_str, due_str,
                        now, progress, tag, project["id"]
                    )
                )
                st.success("Project updated.")

        # Refresh to reflect new tag and values in the UI
        st.rerun()

    # ---------- DELETE ----------
    if c2.button("Delete") and selected != "New Project":
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project["id"],))
        st.warning("Project deleted.")
        st.rerun()

    # ---------- CLEAR ----------
    if c3.button("Clear"):
        st.rerun()


# ----------------------------------------------------------
# TAB: DASHBOARD
# ----------------------------------------------------------

with tab_dashboard:
    st.markdown("## Dashboard")

    # -----------------------------------------------
    # TOP FILTER BAR
    # -----------------------------------------------
    colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

    pillars = ["All"] + (distinct_values("pillar") or [])
    statuses = ["All"] + (distinct_values("status") or [])
    owners = ["All"] + (distinct_values("owner") or [])
    priority_vals = distinct_values("priority") or []
    priority_opts = ["All"] + sorted(set(priority_vals)) if priority_vals else ["All"]

    pillar_f = colF1.selectbox("Pillar", pillars)
    status_f = colF2.selectbox("Status", statuses)
    owner_f = colF3.selectbox("Owner", owners)
    priority_f = colF4.selectbox("Priority", priority_opts)
    search_f = colF6.text_input("Search")
    show_all = colF5.checkbox("Show ALL Reports", value=True)

    filters = dict(
        pillar=pillar_f,
        status=status_f,
        owner=owner_f,
        priority=priority_f,
        search=search_f
    )

    data = fetch_df(filters)

    # -----------------------------------------------
    # YEAR FILTER BLOCK
    # -----------------------------------------------
    st.markdown("### ")

    colY1, colY2, colY3, _ = st.columns([1, 1, 2, 2])

    year_mode = colY1.radio("Year Type", ["Start Year", "Due Year"])
    year_col = "start_date" if year_mode == "Start Year" else "due_date"

    data["year"] = pd.to_datetime(data[year_col], errors="coerce").dt.year
    years = ["All"] + sorted(data["year"].dropna().astype(int).unique().tolist())
    year_f = colY2.selectbox("Year", years)

    if year_f != "All":
        data = data[data["year"] == int(year_f)]

    top_n = colY3.slider("Top N per Pillar", 1, 10, 5)

    st.markdown("---")

    # -----------------------------------------------
    # METRIC COUNTERS
    # -----------------------------------------------

    data["is_completed"] = (data["status"] == "Completed") & (data["progress"] == 100)
    data["is_ongoing"] = ~data["is_completed"]

    colM1, colM2, colM3, colM4 = st.columns(4)

    colM1.metric("Projects", len(data))
    colM2.metric("Completed", int(data["is_completed"].sum()))
    colM3.metric("Ongoing", int(data["is_ongoing"].sum()))
    colM4.metric("Distinct Pillars", data["pillar"].nunique())

    st.markdown("---")

    # -----------------------------------------------
    # BAR CHART - Completed vs Ongoing by Pillar
    # -----------------------------------------------

    by_pillar = (
        data.groupby(["pillar", "is_completed"])
        .size()
        .reset_index(name="count")
    )

    by_pillar["Status"] = by_pillar["is_completed"].map(
        {True: "Completed", False: "Ongoing"}
    )

    if not by_pillar.empty:
        fig1 = px.bar(
            by_pillar,
            x="pillar",
            y="count",
            color="Status",
            barmode="group",
            title="Projects by Pillar — Completed vs Ongoing"
        )
        st.plotly_chart(fig1, use_container_width=True)

    # -----------------------------------------------
    # TOP N PROJECTS PER PILLAR (by priority)
    # -----------------------------------------------

    st.markdown("### Top Projects per Pillar")

    tmp = data.copy()
    tmp["priority_num"] = pd.to_numeric(tmp["priority"], errors="coerce")
    tmp = tmp.sort_values(["pillar", "priority_num", "priority"], na_position="last")
    top_df = tmp.groupby("pillar").head(top_n)

    st.dataframe(
        top_df[["name", "pillar", "priority", "status", "progress"]],
        use_container_width=True
    )

    st.markdown("---")

    # -----------------------------------------------
    # DETAILED PROJECT TABLE WITH PROGRESS BARS
    # -----------------------------------------------

    def render_progress_bar(p):
        color = progress_color(p)
        pct = int(p) if pd.notnull(p) else 0
        return f"""
        <div style="width:100%;background:#eee;border-radius:8px;">
            <div style="width:{pct}%;background:{color};
                padding:6px;border-radius:8px;text-align:center;color:white;">
                {pct}%
            </div>
        </div>
        """

    data["Progress Bar"] = data["progress"].apply(render_progress_bar)

    st.markdown("### All Projects")

    st.write(
        data[
            [
                "name", "pillar", "priority", "owner", "status",
                "progress", "progress_status", "Progress Bar"
            ]
        ].to_html(escape=False),
        unsafe_allow_html=True
    )

# ----------------------------------------------------------
# TAB: ROADMAP
# ----------------------------------------------------------

with tab_roadmap:
    st.markdown("## Roadmap")

    data = fetch_df({})

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
            hover_data=["progress", "progress_status"]
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
