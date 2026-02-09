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


def safe_migrate():
    """Add missing columns safely."""
    with conn() as c:
        cur = c.cursor()

        # Add progress column
        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='progress';")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN progress INTEGER DEFAULT 0;")

        # Add progress_status column
        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='progress_status';")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN progress_status TEXT DEFAULT '';")

        # Add last update fields
        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='last_update_by';")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_by TEXT DEFAULT '';")

        cur.execute("SELECT name FROM pragma_table_info('projects') WHERE name='last_update_at';")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN last_update_at TEXT DEFAULT '';")

safe_migrate()


# ---------- Create update history table ----------
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


# ---------- Query Helpers ----------
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


# ---------- Priority / Progress Color ----------
def priority_color(p):
    try:
        p = int(p)
    except:
        return "grey"
    if p == 1: return "red"
    if p in (2, 3): return "orange"
    if p in (4, 5, 6): return "gold"
    return "green"


def progress_color(p):
    try:
        p = int(p)
    except:
        return "gray"
    if p <= 30: return "red"
    if p <= 70: return "gold"
    return "green"


# ----------------------------------------------------------
#                STREAMLIT UI
# ----------------------------------------------------------

st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error("Database not found.")
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

    # ---------- New Project ----------
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
            progress_status="",
            last_update_by="",
            last_update_at=""
        )

    else:
        pid_row = existing[existing["name"] == selected]
        if pid_row.empty:
            st.warning("Project record missing…")
            st.rerun()

        pid = pid_row.iloc[0]["id"]

        with conn() as c:
            df = pd.read_sql_query("SELECT * FROM projects WHERE id=?", c, params=[pid])

        if df.empty:
            st.warning("Project record missing…")
            st.rerun()

        project = df.iloc[0].to_dict()

    # ---------- Parse Dates ----------
    def parse_date(d):
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except:
            return date.today()

    start_val = parse_date(project.get("start_date"))
    due_val = parse_date(project.get("due_date"))

    # ---------- Form Layout ----------
    colA, colB = st.columns([2, 2])

    with colA:
        name = st.text_input("Name*", project["name"])
        pillar = st.selectbox("Pillar*", [""] + distinct_values("pillar"))
        priority = st.number_input("Priority", 1, 10, int(project["priority"] or 1))
        description = st.text_area("Description", project.get("description", ""))

    with colB:
        owner = st.text_input("Owner", project.get("owner", ""))
        status = st.selectbox("Status", [""] + distinct_values("status"))
        start_date = st.date_input("Start Date", value=start_val)
        due_date = st.date_input("Due Date", value=due_val)
        progress = st.slider("Progress (%)", 0, 100, int(project.get("progress", 0)))

        st.text_input(
            "Update Tag (automatic)",
            project.get("progress_status", ""),
            disabled=True
        )

    # Cleaned
    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    pillar_clean = pillar.strip() or None
    status_clean = status.strip() or None
    owner_clean = owner.strip() or None

    # ---------- Buttons ----------
    c1, c2, c3 = st.columns(3)

    # SAVE
    if c1.button("New / Save"):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"Updated on {now}" if project["id"] else f"Created on {now}"

        with conn() as c:
            if selected == "New Project":
                c.execute(
                    """
                    INSERT INTO projects
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     created_at, updated_at, progress, progress_status, last_update_by, last_update_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, pillar_clean, priority, description, owner_clean,
                        status_clean, start_str, due_str,
                        now, now, progress, tag, owner_clean, now
                    )
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
                        name, pillar_clean, priority, description, owner_clean,
                        status_clean, start_str, due_str,
                        now, progress, tag, owner_clean, now,
                        project["id"]
                    )
                )

        st.success("Project saved.")
        st.rerun()

    # DELETE
    if c2.button("Delete") and selected != "New Project":
        with conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project["id"],))
        st.warning("Project deleted.")
        st.rerun()

    # CLEAR
    if c3.button("Clear"):
        st.rerun()


    # ----------------------------------------------------------
    # EXTRA ACTION BUTTONS  (RECREATED FROM YOUR SCREENSHOT)
    # ----------------------------------------------------------
    c4, c5, c6 = st.columns(3)

    # Update button
    if c4.button("Update"):
        if not project.get("id"):
            st.warning("Select a project first.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            auto_tag = f"Updated on {now}"

            with conn() as c:
                c.execute(
                    """
                    UPDATE projects
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?,
                        last_update_by=?, last_update_at=?
                    WHERE id=?
                    """,
                    (
                        name, pillar_clean, priority, description, owner_clean,
                        status_clean, start_str, due_str,
                        now, progress, auto_tag, owner_clean, now,
                        project["id"]
                    )
                )
            st.success("Project updated.")
            st.rerun()

    # Report & Roadmap button
    if c5.button("Report & Roadmap"):
        st.session_state["active_tab"] = "dashboard"
        st.rerun()

    # Export CSV (single project)
    if c6.button("Export CSV"):
        if not project.get("id"):
            st.warning("No project selected.")
        else:
            with conn() as c:
                hist = pd.read_sql_query(
                    """
                    SELECT at, by_user, progress, status, start_date, due_date, note
                    FROM project_updates
                    WHERE project_id=?
                    ORDER BY at DESC
                    """,
                    c,
                    params=[project["id"]]
                )

            st.download_button(
                label="Download Project CSV",
                data=hist.to_csv(index=False),
                file_name=f"{project['name']}_history.csv",
                mime="text/csv"
            )


    # ----------------------------------------------------------
    # LOG UPDATE PANEL
    # ----------------------------------------------------------
    if project.get("id"):
        st.markdown("## Log an Update")

        u1, u2 = st.columns([3, 1])
        update_note = u1.text_area("Update Note", placeholder="Describe what changed…")
        update_by = u2.text_input("Updated By", value=project.get("owner", ""))

        cU1, cU2, cU3, cU4 = st.columns(4)
        update_progress = cU1.slider("Progress (%)", 0, 100, int(project.get("progress", 0)))
        update_status = cU2.selectbox("Status (optional override)", [""] + distinct_values("status"))
        update_start = cU3.date_input("Start Date (optional)", value=start_val)
        update_due = cU4.date_input("Due Date (optional)", value=due_val)

        if st.button("Log Update Entry"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with conn() as c:

                # insert history row
                c.execute(
                    """
                    INSERT INTO project_updates
                    (project_id, at, by_user, note, progress, start_date, due_date, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project["id"], now, update_by, update_note,
                        int(update_progress),
                        update_start.strftime("%Y-%m-%d"),
                        update_due.strftime("%Y-%m-%d"),
                        update_status if update_status else None
                    )
                )

                # sync to project table
                auto_tag = f"Updated on {now}"
                c.execute(
                    """
                    UPDATE projects
                    SET progress=?, 
                        status=COALESCE(?, status),
                        start_date=COALESCE(?, start_date),
                        due_date=COALESCE(?, due_date),
                        progress_status=?,
                        last_update_by=?,
                        last_update_at=?
                    WHERE id=?
                    """,
                    (
                        int(update_progress),
                        update_status if update_status else None,
                        update_start.strftime("%Y-%m-%d"),
                        update_due.strftime("%Y-%m-%d"),
                        auto_tag, update_by, now,
                        project["id"]
                    )
                )

            st.success("Update logged.")
            st.rerun()


    # ----------------------------------------------------------
    # UPDATE HISTORY VIEWER
    # ----------------------------------------------------------
    if project.get("id"):

        with conn() as c:
            hist = pd.read_sql_query(
                """
                SELECT at, by_user, progress, status, start_date, due_date, note
                FROM project_updates
                WHERE project_id=?
                ORDER BY at DESC
                """,
                c,
                params=[project["id"]]
            )

        with st.expander("📜 Update History (click to expand)", expanded=False):
            if hist.empty:
                st.info("No updates logged yet.")
            else:
                st.dataframe(hist, use_container_width=True)



# ----------------------------------------------------------
# TAB: DASHBOARD
# ----------------------------------------------------------
with tab_dashboard:

    st.markdown("## Dashboard")

    # ---------- EXPORT ALL PROJECTS + HISTORY ----------
    st.markdown("### Export Projects + Update History")

    if st.button("Download Full CSV Export"):
        with conn() as c:
            projects = pd.read_sql_query("SELECT * FROM projects", c)
            history = pd.read_sql_query("SELECT * FROM project_updates", c)

        merged = history.merge(
            projects,
            left_on="project_id",
            right_on="id",
            suffixes=("_update", "_project")
        )

        st.download_button(
            label="Download .csv",
            data=merged.to_csv(index=False),
            file_name="portfolio_with_update_history.csv",
            mime="text/csv"
        )

    # (Your Dashboard content stays the same here)



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
