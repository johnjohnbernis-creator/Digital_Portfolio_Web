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

        # 1. Add progress column
        cur.execute(
            "SELECT name FROM pragma_table_info('projects') WHERE name='progress';"
        )
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects ADD COLUMN progress INTEGER DEFAULT 0;")

        # 2. Add progress_status column
        cur.execute(
            "SELECT name FROM pragma_table_info('projects') WHERE name='progress_status';"
        )
        if not cur.fetchone():
            cur.execute(
                "ALTER TABLE projects ADD COLUMN progress_status TEXT DEFAULT '';"
            )


safe_migrate()


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
    except:
        return "grey"
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
    except:
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
        # Find project row safely
        pid_row = existing[existing["name"] == selected]

        # If project not found → UI and DB out of sync
        if pid_row.empty:
            st.warning("The selected project no longer exists. Refreshing…")
            st.experimental_rerun()

        pid = pid_row.iloc[0]["id"]

        # Fetch project safely
        with conn() as c:
            df = pd.read_sql_query("SELECT * FROM projects WHERE id=?", c, params=[pid])

        if df.empty:
            st.warning("Project record missing in database. Refreshing…")
            st.experimental_rerun()

        project = df.iloc[0].to_dict()
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except:
            return date.today()

    start_val = parse_date(project.get("start_date"))
    due_val = parse_date(project.get("due_date"))

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

    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    # Convert blank → None
    pillar_clean = pillar.strip() or None
    status_clean = status.strip() or None
    owner_clean = owner.strip() or None

    c1, c2, c3 = st.columns(3)

    # ---- SAVE ----
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
                    """
                    INSERT INTO projects
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     created_at, updated_at, progress, progress_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, pillar_clean, priority, description, owner_clean, status_clean,
                     start_str, due_str, now, now, progress, tag),
                )
                st.success("Project added.")

            else:
                c.execute(
                    """
                    UPDATE projects
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                        start_date=?, due_date=?, updated_at=?, progress=?, progress_status=?
                    WHERE id=?
                    """,
                    (name, pillar_clean, priority, description, owner_clean, status_clean,
                     start_str, due_str, now, progress, tag, project["id"]),
                )
                st.success("Project updated.")

    if c2.button("Delete") and selected != "New Project":
        with conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project["id"],))
        st.warning("Project deleted.")

    if c3.button("Clear"):
        st.experimental_rerun()


# ----------------------------------------------------------
# TAB: DASHBOARD
# ----------------------------------------------------------

with tab_dashboard:
    st.markdown("## Dashboard")

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
        pillar=pillar_f, status=status_f, owner=owner_f,
        priority=priority_f, search=search_f
    )

    data = fetch_df(filters)

    st.markdown("---")
    st.subheader("Projects Overview")

    def render_progress_bar(p):
        color = progress_color(p)
        return f"""
        <div style="width:100%;background:#eee;border-radius:8px;">
            <div style="width:{p}%;background:{color};
                padding:6px;border-radius:8px;text-align:center;color:white;">
                {p}%
            </div>
        </div>
        """

    data["Progress Bar"] = data["progress"].apply(render_progress_bar)

    st.write(
        data[[
            "name", "pillar", "priority", "owner", "status",
            "progress", "progress_status", "Progress Bar"
        ]].to_html(escape=False), unsafe_allow_html=True
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
