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


# ---------- Priority Color Helpers ----------
def priority_color(p):
    try:
        p = int(p)
    except:
        return "grey"

    if p == 1:
        return "red"
    elif p in (2, 3):
        return "orange"
    elif p in (4, 5, 6):
        return "gold"
    else:
        return "green"


def highlight_priority(val):
    return f'color: {priority_color(val)}; font-weight:bold;'


# ----------------------------------------------------------
#                STREAMLIT APP
# ----------------------------------------------------------

st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")
# ----------------------------------------------------------
# ----------------------------------------------------------
# DEBUG BUTTON — SHOW TABLE STRUCTURE
# ----------------------------------------------------------
with st.sidebar:
    if st.button("Show projects table structure"):
        import sqlite3
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        cur.execute("PRAGMA table_info(projects)")
        rows = cur.fetchall()

        st.write("### SQLite table structure:")
        for r in rows:
            st.write(r)# ----------------------------------------------------------
# DEBUG BUTTON — SHOW TABLE STRUCTURE
# ----------------------------------------------------------
with st.sidebar:
    if st.button("Show projects table structure"):
        import sqlite3
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        cur.execute("PRAGMA table_info(projects)")
        rows = cur.fetchall()

        st.write("### SQLite table structure:")
        for r in rows:
            st.write(r)
# ----------------------------------------------------------
#   TEMPORARY DEBUG BUTTON — SHOW TABLE STRUCTURE
# ----------------------------------------------------------
with st.sidebar:
    if st.button("SHOW PROJECTS TABLE STRUCTURE"):
        import sqlite3
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        cur.execute("PRAGMA table_info(projects)")
        rows = cur.fetchall()

        st.write("### SQLite Table Columns:")
        st.code(rows)

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

    # Load list of existing projects
    with conn() as c:
        existing = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

    options = ["<New Project>"] + existing["name"].tolist()
    selected = st.selectbox("Select Project", options)

    # Load selected row
    if selected == "<New Project>":
        project = dict(
            id=None, name="", pillar="", priority=1,
            description="", owner="", status="",
            start_date="", due_date=""
        )
    else:
        pid = existing[existing["name"] == selected].iloc[0]["id"]
        with conn() as c:
            df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id = ?", c, params=[pid])
        project = df.iloc[0].to_dict()

    # Parse dates
    def parse_date(d):
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except:
            return date.today()

    start_val = parse_date(project.get("start_date"))
    due_val = parse_date(project.get("due_date"))

    # ---------- FORM UI ----------
    colA, colB = st.columns([2, 2])

    with colA:
        name = st.text_input("Name*", project["name"])
        pillar = st.selectbox("Pillar*", [""] + distinct_values("pillar"))
        priority = st.number_input("Priority", 1, 10, int(project["priority"] or 1))

        st.markdown(
            f"<span style='color:{priority_color(priority)}; font-size:22px;'>●</span> "
            f"<span style='color:{priority_color(priority)}; font-weight:bold;'>Priority Level</span>",
            unsafe_allow_html=True
        )

        description = st.text_area("Description", project.get("description", ""))

    with colB:
        owner = st.text_input("Owner", project.get("owner", ""))
        status = st.selectbox("Status", [""] + distinct_values("status"))
        start_date = st.date_input("Start Date", value=start_val)
        due_date = st.date_input("Due Date", value=due_val)

    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    # ---------- CRUD BUTTONS ----------
    c1, c2, c3 = st.columns(3)

    # SAVE / UPDATE
    if c1.button("New / Save"):
        with conn() as c:
            if selected == "<New Project>":
                c.execute(
                    f"""INSERT INTO {TABLE}
                    (id, name, pillar, priority, description, owner, status, start_date, due_date)
                    VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, pillar, priority, description, owner, status, start_str, due_str),
                )
                st.success("Project added.")
            else:
                c.execute(
                    f"""UPDATE {TABLE}
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
                    WHERE id=?""",
                    (name, pillar, priority, description, owner, status, start_str, due_str, project["id"]),
                )
                st.success("Project updated.")

    # DELETE
    if c2.button("Delete") and selected != "<New Project>":
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project["id"],))
        st.warning("Project deleted.")

    # CLEAR
    if c3.button("Clear"):
        st.experimental_rerun()

# ----------------------------------------------------------
#                TAB: DASHBOARD
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
        pillar=pillar_f, status=status_f,
        owner=owner_f, priority=priority_f, search=search_f
    )

    data = fetch_df(filters)

    data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
    data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

    rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])

    year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"])
    year_col = "start_year" if year_mode == "Start Year" else "due_year"

    years = ["All"] + sorted(data[year_col].dropna().astype(int).unique().tolist())
    year_f = rc2.selectbox("Year", years)

    top_n = rc3.slider("Top N per Pillar", 1, 10, 5)
    show_all = rc4.checkbox("Show ALL Reports", True)

    if not show_all:
        show_kpi = rc4.checkbox("KPI Cards", True)
        show_chart = rc4.checkbox("Pillar Status Chart", True)
        show_table = rc4.checkbox("Projects Table", True)
    else:
        show_kpi = show_chart = show_table = True

    if year_f != "All":
        data = data[data[year_col] == int(year_f)]

    # KPI CARDS
    if show_kpi:
        st.markdown("---")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Projects", len(data))
        k2.metric("Completed", (data["status"].str.lower() == "done").sum())
        k3.metric("Ongoing", (data["status"].str.lower() != "done").sum())
        k4.metric("Distinct Pillars", data["pillar"].nunique())

    # CHART
    if show_chart:
        st.markdown("---")
        df = data.copy()
        df["state"] = df["status"].apply(lambda x: "Completed" if str(x).lower() == "done" else "Ongoing")
        summary = df.groupby(["pillar", "state"]).size().reset_index(name="count")

        if not summary.empty:
            fig = px.bar(
                summary, x="pillar", y="count",
                color="state", barmode="group",
                title="Projects by Pillar — Completed vs Ongoing"
            )
            st.plotly_chart(fig, use_container_width=True)

    # TOP N
    st.markdown("---")
    st.subheader(f"Top {top_n} Projects per Pillar")

    top_df = (
        data.sort_values("priority")
        .groupby("pillar")
        .head(top_n)
    )

    st.dataframe(
        top_df.style.applymap(highlight_priority, subset=["priority"]),
        use_container_width=True
    )

    # FULL PROJECT TABLE
    if show_table:
        st.markdown("---")
        st.subheader("Projects")

        st.dataframe(
            data.style.applymap(highlight_priority, subset=['priority']),
            use_container_width=True
        )

# ----------------------------------------------------------
#                TAB: ROADMAP
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
            gantt, x_start="Start", x_end="Finish",
            y="name", color="pillar"
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
