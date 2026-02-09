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


@st.cache_data(show_spinner=False)
def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args: List[Any] = []
    where: List[str] = []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != "All":
                where.append(f"{col} = ?")
                args.append(filters[col])

        if filters.get("priority") and filters["priority"] != "All":
            where.append("CAST(priority AS TEXT) = ?")
            args.append(str(filters["priority"]))

        if filters.get("search"):
            s = f"%{str(filters['search']).lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(start_date,''), COALESCE(due_date,'')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


@st.cache_data(show_spinner=False)
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
    except Exception:
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


# ----------------------------------------------------------
#                STREAMLIT APP
# ----------------------------------------------------------

st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

# ---- Debug: Show Table Structure ----
with st.sidebar:
    if st.button("Show Projects Table Structure"):
        with conn() as c:
            cur = c.cursor()
            cur.execute(f"PRAGMA table_info({TABLE})")
            st.write("### SQLite Table Columns:")
            st.code(cur.fetchall())


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
        project: Dict[str, Any] = dict(
            id=None,
            name="",
            pillar="",
            priority=1,
            description="",
            owner="",
            status="",
            start_date="",
            due_date="",
        )
    else:
        pid = existing.loc[existing["name"] == selected, "id"].iloc[0]
        with conn() as c:
            df = pd.read_sql_query(
                f"SELECT * FROM {TABLE} WHERE id=?", c, params=[pid]
            )
        project = df.iloc[0].to_dict()

    # Date parsing with fallback to today to satisfy widgets
    def parse_date(d):
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except Exception:
            return date.today()

    start_val = parse_date(project.get("start_date"))
    due_val = parse_date(project.get("due_date"))

    colA, colB = st.columns([2, 2])

    with colA:
        name = st.text_input("Name*", project.get("name", ""))

        pillar_choices = [""] + distinct_values("pillar")
        pillar = st.selectbox(
            "Pillar*",
            pillar_choices,
            index=(
                pillar_choices.index(project.get("pillar", ""))
                if project.get("pillar", "") in pillar_choices
                else 0
            ),
        )

        pr_default = int(project.get("priority") or 1)
        priority = st.number_input(
            "Priority", min_value=1, max_value=10, value=pr_default, step=1
        )

        st.markdown(
            f"<span style='color:{priority_color(priority)}; font-size:22px;'>●</span> "
            f"<span style='color:{priority_color(priority)}; font-weight:bold;'>Priority Level</span>",
            unsafe_allow_html=True,
        )

        description = st.text_area("Description", project.get("description", ""))

    with colB:
        owner = st.text_input("Owner", project.get("owner", ""))

        status_choices = [""] + distinct_values("status")
        status = st.selectbox(
            "Status",
            status_choices,
            index=(
                status_choices.index(project.get("status", ""))
                if project.get("status", "") in status_choices
                else 0
            ),
        )

        start_date = st.date_input("Start Date", value=start_val)
        due_date = st.date_input("Due Date", value=due_val)

    start_str = start_date.strftime("%Y-%m-%d")
    due_str = due_date.strftime("%Y-%m-%d")

    # Clean empty strings → None for DB
    pillar_clean = pillar if pillar and pillar.strip() else None
    status_clean = status if status and status.strip() else None
    owner_clean = owner if owner and owner.strip() else None

    c1, c2, c3 = st.columns(3)

    # ---- SAVE ----
    if c1.button("New / Save", use_container_width=True):
        if not name.strip():
            st.error("Name is required.")
        else:
            with conn() as c:
                if selected == "New Project":
                    c.execute(
                        f"""
                        INSERT INTO {TABLE}
                        (name, pillar, priority, description, owner, status, start_date, due_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            name.strip(),
                            pillar_clean,
                            int(priority),
                            description.strip(),
                            owner_clean,
                            status_clean,
                            start_str,
                            due_str,
                        ),
                    )
                    st.success("Project added.")
                else:
                    c.execute(
                        f"""
                        UPDATE {TABLE}
                        SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
                        WHERE id=?
                        """,
                        (
                            name.strip(),
                            pillar_clean,
                            int(priority),
                            description.strip(),
                            owner_clean,
                            status_clean,
                            start_str,
                            due_str,
                            project["id"],
                        ),
                    )
                    st.success("Project updated.")
            # refresh cached lists & data after write
            fetch_df.clear()
            distinct_values.clear()

    # ---- DELETE ----
    if c2.button("Delete", use_container_width=True) and selected != "New Project":
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project["id"],))
        st.warning("Project deleted.")
        fetch_df.clear()
        distinct_values.clear()
        st.rerun()

    # ---- CLEAR ----
    if c3.button("Clear", use_container_width=True):
        st.rerun()


# ----------------------------------------------------------
# TAB: DASHBOARD
# ----------------------------------------------------------

with tab_dashboard:
    st.markdown("## Dashboard")

    colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

    pillars = ["All"] + distinct_values("pillar")
    statuses = ["All"] + distinct_values("status")
    owners = ["All"] + distinct_values("owner")

    # Priority as integers when possible, then sorted
    priority_vals_raw = distinct_values("priority")

    def _to_intable(x: str) -> Optional[int]:
        try:
            return int(float(x))
        except Exception:
            return None

    priority_ints = sorted({p for p in map(_to_intable, priority_vals_raw) if p is not None})
    priority_opts: List[Any] = ["All"] + priority_ints

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

    data = fetch_df(filters).copy()

    for col in ["start_date", "due_date", "pillar", "priority", "name"]:
        if col not in data.columns:
            data[col] = None

    data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
    data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

    rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])

    year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"], horizontal=True)
    year_col = "start_year" if year_mode == "Start Year" else "due_year"

    years_list = sorted(data[year_col].dropna().astype(int).unique().tolist())
    years = ["All"] + years_list
    year_f = rc2.selectbox("Year", years)

    if year_f != "All":
        data = data[data[year_col] == int(year_f)]

    top_n = rc3.slider("Top N per Pillar", 1, 10, 5)

    st.markdown("---")
    st.subheader(f"Top {top_n} Projects per Pillar")

    data["priority_num"] = pd.to_numeric(data["priority"], errors="coerce")
    top_df = (
        data.sort_values("priority_num", na_position="last")
        .groupby("pillar", dropna=False, sort=False)
        .head(top_n)
        .drop(columns=["priority_num"])
    )

    st.dataframe(
        top_df.style.applymap(highlight_priority, subset=["priority"]),
        use_container_width=True,
    )

    st.markdown("---")
    st.subheader("Projects")

    st.dataframe(
        data.style.applymap(highlight_priority, subset=["priority"]),
        use_container_width=True,
    )


# ----------------------------------------------------------
# TAB: ROADMAP
# ----------------------------------------------------------

with tab_roadmap:
    st.markdown("## Roadmap")

    data = fetch_df({}).copy()

    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt.get("start_date"), errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt.get("due_date"), errors="coerce")
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
    else:
        st.info("No dated projects to display on the roadmap.")
