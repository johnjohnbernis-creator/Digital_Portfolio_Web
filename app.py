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


# ----------------------------------------------------------
# DATABASE CONNECTION
# ----------------------------------------------------------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# ----------------------------------------------------------
# BASE TABLE CREATION
# ----------------------------------------------------------
def create_projects_table_if_needed():
    """
    Create the 'projects' table if it doesn't exist, with all columns referenced by the app.
    """
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT,
                priority INTEGER DEFAULT 1,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT,
                created_at TEXT,
                updated_at TEXT,
                progress INTEGER DEFAULT 0,
                progress_status TEXT DEFAULT '',
                last_update_by TEXT DEFAULT '',
                last_update_at TEXT DEFAULT ''
            )
            """
        )

create_projects_table_if_needed()


# ----------------------------------------------------------
# PROJECT TABLE MIGRATION
# ----------------------------------------------------------
def safe_migrate():
    """
    Adds missing columns safely if they don't exist. Call after base table creation.
    """
    with conn() as c:
        cur = c.cursor()

        # Helper to detect column existence
        def has_col(col: str) -> bool:
            cur.execute("PRAGMA table_info(projects)")
            cols = [r[1] for r in cur.fetchall()]
            return col in cols

        # Add columns if missing
        if not has_col("progress"):
            cur.execute("ALTER TABLE projects ADD COLUMN progress INTEGER DEFAULT 0")

        if not has_col("progress_status"):
            cur.execute("ALTER TABLE projects ADD COLUMN progress_status TEXT DEFAULT ''")

        if not has_col("last_update_by"):
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_by TEXT DEFAULT ''")

        if not has_col("last_update_at"):
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_at TEXT DEFAULT ''")

        # Often useful fields if older DBs are missing them
        if not has_col("created_at"):
            cur.execute("ALTER TABLE projects ADD COLUMN created_at TEXT")
        if not has_col("updated_at"):
            cur.execute("ALTER TABLE projects ADD COLUMN updated_at TEXT")

safe_migrate()


# ----------------------------------------------------------
# PROJECT UPDATE HISTORY TABLE
# ----------------------------------------------------------
def migrate_updates_table():
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS project_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                by_user TEXT DEFAULT '',
                note TEXT DEFAULT '',
                progress INTEGER,
                start_date TEXT,
                due_date TEXT,
                status TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
            """
        )

migrate_updates_table()


# ----------------------------------------------------------
# DATA HELPERS
# ----------------------------------------------------------
def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args: List[Any] = []
    where: List[str] = []

    if filters:
        for col in ["pillar", "status", "owner"]:
            val = filters.get(col)
            if val and val != "All":
                where.append(f"{col} = ?")
                args.append(val)

        if filters.get("priority") and filters["priority"] != "All":
            where.append("CAST(priority AS TEXT) = ?")
            args.append(str(filters["priority"]))

        if filters.get("search"):
            s = f"%{str(filters['search']).lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY start_date, due_date"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def distinct_values(col: str) -> List[str]:
    """Return unique non-empty values from a column."""
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


# ----------------------------------------------------------
# COLOR HELPERS
# ----------------------------------------------------------
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
# STREAMLIT INIT
# ----------------------------------------------------------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "editor"


# ----------------------------------------------------------
# TABS
# ----------------------------------------------------------
tab_editor, tab_dashboard, tab_roadmap = st.tabs(["🛠 Editor", "📊 Dashboard", "🗺 Roadmap"])


# ----------------------------------------------------------
# EDITOR TAB
# ----------------------------------------------------------
with tab_editor:
    st.subheader("Project Editor")

    with conn() as c:
        existing = pd.read_sql_query("SELECT id, name FROM projects ORDER BY name", c)

    options = ["New Project"] + existing["name"].tolist()
    selected = st.selectbox("Select Project", options)

    # LOAD OR INITIALIZE
    if selected == "New Project":
        project = {
            "id": None,
            "name": "",
            "pillar": "",
            "priority": 1,
            "description": "",
            "owner": "",
            "status": "",
            "start_date": "",
            "due_date": "",
            "progress": 0,
            "progress_status": "",
            "last_update_by": "",
            "last_update_at": "",
        }
    else:
        pid = int(existing.loc[existing["name"] == selected, "id"].iloc[0])
        with conn() as c:
            df = pd.read_sql_query("SELECT * FROM projects WHERE id=?", c, params=[pid])
        project = df.iloc[0].to_dict()

    # DATE HANDLING
    def parse_date(d):
        try:
            # accept 'YYYY-MM-DD'; if empty/null, fallback to today
            d = str(d).strip()
            if not d:
                return date.today()
            return datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            return date.today()

    start_val = parse_date(project.get("start_date", ""))
    due_val = parse_date(project.get("due_date", ""))

    # FORM LAYOUT
    colA, colB = st.columns(2)

    with colA:
        name = st.text_input("Name*", project["name"])
        pillar = st.selectbox("Pillar*", [""] + distinct_values("pillar"))
        priority = st.number_input("Priority", 1, 10, int(project.get("priority", 1)))
        description = st.text_area("Description", project.get("description", ""))

    with colB:
        owner = st.text_input("Owner", project.get("owner", ""))
        status = st.selectbox("Status", [""] + distinct_values("status"))
        start_date = st.date_input("Start Date", start_val)
        due_date = st.date_input("Due Date", due_val)
        progress = st.slider("Progress (%)", 0, 100, int(project.get("progress", 0)))

        st.text_input("Update Tag (auto)", project.get("progress_status", ""), disabled=True)

    # CLEAN
    pillar_clean = pillar or None
    status_clean = status or None
    owner_clean = owner or None
    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    # BUTTON ROW 1 — Save / Delete / Clear
    c1, c2, c3 = st.columns(3)

    # SAVE
    if c1.button("New / Save"):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"Updated on {now}" if project["id"] else f"Created on {now}"

        with conn() as c:
            if project["id"] is None:
                c.execute(
                    """
                    INSERT INTO projects
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     created_at, updated_at, progress, progress_status, last_update_by, last_update_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        pillar_clean,
                        int(priority),
                        description,
                        owner_clean,
                        status_clean,
                        start_str,
                        due_str,
                        now,
                        now,
                        int(progress),
                        tag,
                        owner_clean,
                        now,
                    ),
                )
            else:
                c.execute(
                    """
                    UPDATE projects
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?,
                        last_update_by=?, last_update_at=?
                    WHERE id=?
                    """,
                    (
                        name,
                        pillar_clean,
                        int(priority),
                        description,
                        owner_clean,
                        status_clean,
                        start_str,
                        due_str,
                        now,
                        int(progress),
                        tag,
                        owner_clean,
                        now,
                        int(project["id"]),
                    ),
                )

        st.success("Saved.")
        st.rerun()

    # DELETE
    if c2.button("Delete") and project["id"]:
        with conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (int(project["id"]),))
            c.execute("DELETE FROM project_updates WHERE project_id=?", (int(project["id"]),))
        st.warning("Deleted.")
        st.rerun()

    # CLEAR
    if c3.button("Clear"):
        st.rerun()

    # BUTTON ROW 2 — Update / Report & Roadmap / Export
    c4, c5, c6 = st.columns(3)

    # UPDATE
    if c4.button("Update"):
