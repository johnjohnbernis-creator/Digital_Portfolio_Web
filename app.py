# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------

import os
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Union

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = "portfolio.db"
TABLE = "projects"


# ---------- DB Utilities ----------
def conn() -> sqlite3.Connection:
    """Return a SQLite DB connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def ensure_table() -> bool:
    """Return True if the projects table exists."""
    try:
        with conn() as c:
            cur = c.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (TABLE,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def bootstrap_db(seed: bool = True) -> None:
    """Create table + indexes; optionally seed demo rows."""
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                pillar TEXT,
                priority INTEGER,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT
            );
            """
        )

        # Indexes
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_pillar ON {TABLE}(pillar);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_status ON {TABLE}(status);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_owner ON {TABLE}(owner);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_priority ON {TABLE}(priority);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_start ON {TABLE}(start_date);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_due ON {TABLE}(due_date);")

        if seed:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            if cur.fetchone()[0] == 0:
                rows = [
                    ("Site HMI Overhaul", "Operations", 1, "Revamp line HMI screens", "J. Bernis",
                     "Active", "2026-01-15", "2026-03-31"),
                    ("DMS Rewards", "Quality", 2, "Rewards dashboard in DMS", "M. Upadhaya",
                     "Planned", "2026-02-01", "2026-04-15"),
                    ("Spool Tracking POC", "Manufacturing", 3, "RFID tracking for spools", "U. Otaluka",
                     "Active", "2026-02-10", "2026-05-01"),
                    ("Enable Distribution API", "IT", 2, "Expose distribution endpoints", "G. Akin",
                     "Blocked", "2026-02-05", "2026-03-15"),
                    ("Reminder Notifications", "IT", 4, "Email / app reminders", "L. Van Hekken",
                     "Planned", "2026-03-01", "2026-04-01"),
                ]
                cur.executemany(
                    f"""
                    INSERT INTO {TABLE}
                    (name, pillar, priority, description, owner, status, start_date, due_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )


# ---------- Helpers ----------
def try_date(s: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD string, returning None if invalid."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Fetch DB rows with optional filters."""
    q = f"SELECT * FROM {TABLE}"
    args: List[Any] = []
    where: List[str] = []

    if filters:
        for col in ("pillar", "status", "owner"):
            val = filters.get(col)
            if val and val != "All":
                where.append(f"{col} = ?")
                args.append(val)

        if filters.get("priority") not in (None, "All"):
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


@st.cache_data(show_spinner=False)
def distinct_values(col: str) -> List[str]:
    """Return sorted list of distinct non-empty values in a column."""
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
def priority_color(p: Union[str, int, float, None]) -> str:
    """Return color name for priority number."""
    try:
        p = int(p)
    except Exception:
        return "grey"

    if p == 1:
        return "red"
    if p in (2, 3):
        return "orange"
    if 4 <= p <= 6:
        return "gold"
    return "green"


def highlight_priority(val):
    return f"color:{priority_color(val)}; font-weight:bold;"


# ----------------------------------------------------------
# Streamlit APP
# ----------------------------------------------------------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# ---------- Sidebar ----------
with st.sidebar:
    st.subheader("Admin")

    if not ensure_table():
        st.warning("Table not found. Click Bootstrap.")

    col_b1, col_b2 = st.columns(2)
    seed = col_b2.checkbox("Seed sample", value=True)

    if col_b1.button("Bootstrap", use_container_width=True):
        bootstrap_db(seed)
        fetch_df.clear()
        distinct_values.clear()
        st.success("Database initialized.")
        st.rerun()

    st.markdown("---")

    if st.button("Show Table Structure"):
        if ensure_table():
            with conn() as c:
                cur = c.cursor()
                cur.execute(f"PRAGMA table_info({TABLE})")
                st.code(cur.fetchall())
        else:
            st.info("Table does not exist.")


# ----------------------------------------------------------
#                     TABS
# ----------------------------------------------------------
tab_editor, tab_dashboard, tab_roadmap = st.tabs(
    ["🛠 Editor", "📊 Dashboard", "🗺 Roadmap"]
)

# ----------------------------------------------------------
#                     EDITOR TAB
# ----------------------------------------------------------
with tab_editor:
    st.header("Project Editor")

    if ensure_table():
        with conn() as c:
            df_names = pd.read_sql_query(
                f"SELECT id, name FROM {TABLE} ORDER BY name",
                c
            )

        options = ["New Project"] + df_names["name"].tolist()
        selected = st.selectbox("Select Project", options)

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
                "due_date": ""
            }
        else:
            pid = int(df_names.loc[df_names["name"] == selected, "id"].iloc[0])
            with conn() as c:
                df = pd.read_sql_query(
                    f"SELECT * FROM {TABLE} WHERE id=?",
                    c,
                    params=[pid],
                )
            project = df.iloc[0].to_dict()

        def parse(d):
            try:
                return datetime.strptime(str(d), "%Y-%m-%d").date()
            except Exception:
                return date.today()

        start_val = parse(project["start_date"])
        due_val = parse(project["due_date"])

        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("Name*", project["name"])
            pillars = [""] + distinct_values("pillar")
            pillar = st.selectbox(
                "Pillar*",
                pillars,
                index=pillars.index(project["pillar"]) if project["pillar"] in pillars else 0
            )
            priority = st.number_input(
                "Priority",
                min_value=1,
                max_value=10,
                value=int(project["priority"] or 1)
            )
            st.markdown(
                f"<span style='color:{priority_color(priority)}; font-size:22px;'>●</span> "
                f"<b style='color:{priority_color(priority)};'>Priority</b>",
                unsafe_allow_html=True,
            )
            description = st.text_area("Description", project["description"])

        with col2:
            owner = st.text_input("Owner", project["owner"])
            statuses = [""] + distinct_values("status")
            status = st.selectbox(
                "Status",
                statuses,
                index=statuses.index(project["status"]) if project["status"] in statuses else 0
            )
            start_date = st.date_input("Start", value=start_val)
            due_date = st.date_input("Due", value=due_val)

        # DB-safe values
        pillar_clean = pillar or None
        status_clean = status or None
        owner_clean = owner or None

        c1, c2, c3 = st.columns(3)

        if c1.button("Save", use_container_width=True):
            if not name.strip():
                st.error("Name required.")
            else:
                with conn() as c:
                    if project["id"] is None:
                        c.execute(
                            f"""
                            INSERT INTO {TABLE}
                            (name, pillar, priority, description, owner, status, start_date, due_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                name.strip(), pillar_clean, int(priority),
                                description.strip(), owner_clean, status_clean,
                                start_date.strftime("%Y-%m-%d"),
                                due_date.strftime("%Y-%m-%d")
                            ),
                        )
                    else:
                        c.execute(
                            f"""
                            UPDATE {TABLE}
                            SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
                            WHERE id=?
                            """,
                            (
                                name.strip(), pillar_clean, int(priority),
                                description.strip(), owner_clean, status_clean,
                                start_date.strftime("%Y-%m-%d"),
                                due_date.strftime("%Y-%m-%d"),
                                project["id"]
                            ),
                        )
                fetch_df.clear()
                distinct_values.clear()
                st.success("Saved.")
                st.rerun()

        if c2.button("Delete", use_container_width=True) and project["id"]:
            with conn() as c:
                c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project["id"],))
            fetch_df.clear()
            distinct_values.clear()
            st.warning("Deleted.")
            st.rerun()

        if c3.button("Clear", use_container_width=True):
            st.rerun()

    else:
        st.info("Bootstrap DB first.")


# ----------------------------------------------------------
#                     DASHBOARD TAB
# ----------------------------------------------------------
with tab_dashboard:
    st.header("Dashboard")

    if ensure_table():
        col1, col2, col3, col4, col5, col6 = st.columns([1, 1, 1, 1, 1, 2])

        pillars = ["All"] + distinct_values("pillar")
        statuses = ["All"] + distinct_values("status")
        owners = ["All"] + distinct_values("owner")
        pr_vals = distinct_values("priority")

        def safe_int(x: str) -> Optional[int]:
            try:
                return int(float(x))
            except Exception:
                return None

        pr_list = sorted({p for p in map(safe_int, pr_vals) if p is not None})
        pr_opts = ["All"] + pr_list

        pillar_f = col1.selectbox("Pillar", pillars)
        status_f = col2.selectbox("Status", statuses)
        owner_f = col3.selectbox("Owner", owners)
        pr_f = col4.selectbox("Priority", pr_opts)
        search_f = col6.text_input("Search")

        filters = dict(
            pillar=pillar_f,
            status=status_f,
            owner=owner_f,
            priority=pr_f,
            search=search_f,
        )

        data = fetch_df(filters).copy()

        for col in ["start_date", "due_date"]:
            data[col] = pd.to_datetime(data[col], errors="coerce")

        st.divider()
        st.subheader("Projects")
        st.dataframe(
            data.style.applymap(highlight_priority, subset=["priority"]),
            use_container_width=True,
        )
    else:
        st.info("Bootstrap DB first.")


# ----------------------------------------------------------
#                     ROADMAP TAB
# ----------------------------------------------------------
with tab_roadmap:
    st.header("Roadmap")

    if ensure_table():
        df = fetch_df().copy()

        df["Start"] = pd.to_datetime(df["start_date"], errors="coerce")
        df["Finish"] = pd.to_datetime(df["due_date"], errors="coerce")

        gantt = df.dropna(subset=["Start", "Finish"])

        if not gantt.empty:
            fig = px.timeline(
                gantt,
                x_start="Start",
                x_end="Finish",
                y="name",
                color="pillar"
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No valid dated projects.")
    else:
        st.info("Bootstrap DB first.")
