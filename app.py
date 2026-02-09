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
# PROJECT TABLE MIGRATION
# ----------------------------------------------------------
def safe_migrate():
    with conn() as c:
        cur = c.cursor()

        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='progress'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN progress INTEGER DEFAULT 0")

        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='progress_status'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN progress_status TEXT DEFAULT ''")

        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='last_update_by'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_by TEXT DEFAULT ''")

        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='last_update_at'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_at TEXT DEFAULT ''")

safe_migrate()


# ----------------------------------------------------------
# PROJECT UPDATE HISTORY TABLE
# ----------------------------------------------------------
def migrate_updates_table():
    with conn() as c:
        cur = c.cursor()
        cur.execute("""
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
        """)

migrate_updates_table()


# ----------------------------------------------------------
# DATA HELPERS
# ----------------------------------------------------------
def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args = []
    where = []

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
            s = f"%{filters['search'].lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY start_date, due_date"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


from typing import List

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
    try: p = int(p)
    except: return "gray"
    if p == 1: return "red"
    if p in (2, 3): return "orange"
    if p in (4, 5, 6): return "gold"
    return "green"

def progress_color(p):
    try: p = int(p)
    except: return "gray"
    if p <= 30: return "red"
    if p <= 70: return "gold"
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
tab_editor, tab_dashboard, tab_roadmap = st.tabs(
    ["🛠 Editor", "📊 Dashboard", "🗺 Roadmap"]
)


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
            "id": None, "name": "", "pillar": "", "priority": 1,
            "description": "", "owner": "", "status": "",
            "start_date": "", "due_date": "",
            "progress": 0, "progress_status": "",
            "last_update_by": "", "last_update_at": ""
        }
    else:
        pid = existing[existing["name"] == selected].iloc[0]["id"]
        with conn() as c:
            df = pd.read_sql_query("SELECT * FROM projects WHERE id=?", c, params=[pid])
        project = df.iloc[0].to_dict()

    # DATE HANDLING
    def parse_date(d):
        try: return datetime.strptime(str(d), "%Y-%m-%d").date()
        except: return date.today()

    start_val = parse_date(project["start_date"])
    due_val = parse_date(project["due_date"])

    # FORM LAYOUT
    colA, colB = st.columns(2)

    with colA:
        name = st.text_input("Name*", project["name"])
        pillar = st.selectbox("Pillar*", [""] + distinct_values("pillar"))
        priority = st.number_input("Priority", 1, 10, int(project["priority"]))
        description = st.text_area("Description", project["description"])

    with colB:
        owner = st.text_input("Owner", project["owner"])
        status = st.selectbox("Status", [""] + distinct_values("status"))
        start_date = st.date_input("Start Date", start_val)
        due_date = st.date_input("Due Date", due_val)
        progress = st.slider("Progress (%)", 0, 100, int(project["progress"]))

        st.text_input("Update Tag (auto)", project["progress_status"], disabled=True)

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
                c.execute("""
                    INSERT INTO projects
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     created_at, updated_at, progress, progress_status, last_update_by, last_update_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name, pillar_clean, priority, description, owner_clean, status_clean,
                    start_str, due_str, now, now, progress, tag, owner_clean, now
                ))
            else:
                c.execute("""
                    UPDATE projects
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?,
                        last_update_by=?, last_update_at=?
                    WHERE id=?
                """, (
                    name, pillar_clean, priority, description, owner_clean, status_clean,
                    start_str, due_str, now, progress, tag, owner_clean, now, project["id"]
                ))

        st.success("Saved.")
        st.rerun()

    # DELETE
    if c2.button("Delete") and project["id"]:
        with conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project["id"],))
        st.warning("Deleted.")
        st.rerun()

    # CLEAR
    if c3.button("Clear"):
        st.rerun()

    # BUTTON ROW 2 — Update / Report & Roadmap / Export
    c4, c5, c6 = st.columns(3)

    # UPDATE
    if c4.button("Update"):
        if not project["id"]:
            st.warning("Select a project.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            auto_tag = f"Updated on {now}"

            with conn() as c:
                c.execute("""
                    UPDATE projects
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?,
                        last_update_by=?, last_update_at=?
                    WHERE id=?
                """, (
                    name, pillar_clean, priority, description, owner_clean, status_clean,
                    start_str, due_str, now, progress, auto_tag, owner_clean, now, project["id"]
                ))

            st.success("Updated.")
            st.rerun()

    # GO TO DASHBOARD
    if c5.button("Report & Roadmap"):
        st.session_state["active_tab"] = "dashboard"
        st.rerun()

    # EXPORT PROJECT CSV
    if c6.button("Export CSV"):
        if not project["id"]:
            st.warning("Select a project.")
        else:
            with conn() as c:
                hist = pd.read_sql_query("""
                    SELECT at, by_user, progress, status, start_date, due_date, note
                    FROM project_updates
                    WHERE project_id=?
                    ORDER BY at DESC
                """, c, params=[project["id"]])

            st.download_button(
                label="Download CSV",
                data=hist.to_csv(index=False),
                file_name=f"{project['name']}_history.csv",
                mime="text/csv"
            )

    # LOG UPDATE PANEL
    if project["id"]:
        st.subheader("Log an Update")

        cA, cB = st.columns([3, 1])
        update_note = cA.text_area("Update Note")
        update_by = cB.text_input("Updated By", project["owner"])

        uA, uB, uC, uD = st.columns(4)
        update_progress = uA.slider("Progress (%)", 0, 100, int(project["progress"]))
        update_status = uB.selectbox("Status (optional)", [""] + distinct_values("status"))
        update_start = uC.date_input("Start (optional)", start_val)
        update_due = uD.date_input("Due (optional)", due_val)

        if st.button("Log Update"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with conn() as c:
                c.execute("""
                    INSERT INTO project_updates
                    (project_id, at, by_user, note, progress, start_date, due_date, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project["id"], now, update_by, update_note,
                    int(update_progress),
                    update_start.strftime("%Y-%m-%d"),
                    update_due.strftime("%Y-%m-%d"),
                    update_status or None
                ))

                auto_tag = f"Updated on {now}"
                c.execute("""
                    UPDATE projects
                    SET progress=?, status=COALESCE(?, status),
                        start_date=COALESCE(?, start_date),
                        due_date=COALESCE(?, due_date),
                        progress_status=?, last_update_by=?, last_update_at=?
                    WHERE id=?
                """, (
                    int(update_progress),
                    update_status or None,
                    update_start.strftime("%Y-%m-%d"),
                    update_due.strftime("%Y-%m-%d"),
                    auto_tag, update_by, now,
                    project["id"]
                ))

            st.success("Logged.")
            st.rerun()

    # UPDATE HISTORY
    if project["id"]:
        with conn() as c:
            hist = pd.read_sql_query("""
                SELECT at, by_user, progress, status, start_date, due_date, note
                FROM project_updates
                WHERE project_id=?
                ORDER BY at DESC
            """, c, params=[project["id"]])

        with st.expander("📜 Update History"):
            if hist.empty:
                st.info("No updates yet.")
            else:
                st.dataframe(hist, use_container_width=True)



# ----------------------------------------------------------
# DASHBOARD TAB
# ----------------------------------------------------------

with tab_dashboard:

    st.subheader("Dashboard")

    # EXPORT EVERYTHING
    st.markdown("### Export Portfolio + Update History")
    if st.button("Download Full CSV"):
        with conn() as c:
            projects = pd.read_sql_query("SELECT * FROM projects", c)
            history = pd.read_sql_query("SELECT * FROM project_updates", c)

        merged = history.merge(projects, left_on="project_id", right_on="id")
        st.download_button(
            "Download",
            merged.to_csv(index=False),
            "portfolio_full_history.csv",
            mime="text/csv"
        )

    # you can continue your dashboard logic (charts, tables...)
    # nothing below is changed from your original structure



# ----------------------------------------------------------
# ROADMAP TAB
# ----------------------------------------------------------

with tab_roadmap:

    st.subheader("Roadmap")

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
