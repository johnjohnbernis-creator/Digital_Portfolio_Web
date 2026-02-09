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
    # Creates the DB file on first connection if it doesn't exist
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def ensure_table() -> bool:
    """
    Returns True if the projects table exists, False otherwise.
    """
    try:
        with conn() as c:
            cur = c.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (TABLE,),
            )
            row = cur.fetchone()
            return row is not None
    except Exception:
        return False


def bootstrap_db(seed: bool = True) -> None:
    """
    Create the projects table (and helpful indexes) if it doesn't exist.
    Optionally seed a few example rows.
    """
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
                start_date TEXT,  -- 'YYYY-MM-DD'
                due_date TEXT     -- 'YYYY-MM-DD'
            );
            """
        )
        # Helpful indexes for faster filtering
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_pillar ON {TABLE}(pillar);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_status ON {TABLE}(status);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_owner ON {TABLE}(owner);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_priority ON {TABLE}(priority);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_start ON {TABLE}(start_date);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_due ON {TABLE}(due_date);")

        if seed:
            # Only seed if table is empty
            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            count = cur.fetchone()[0]
            if count == 0:
                rows = [
                    ("Site HMI Overhaul", "Operations", 1, "Revamp line HMI screens", "J. Bernis", "Active", "2026-01-15", "2026-03-31"),
                    ("DMS Rewards", "Quality", 2, "Rewards dashboard in DMS", "M. Upadhaya", "Planned", "2026-02-01", "2026-04-15"),
                    ("Spool Tracking POC", "Manufacturing", 3, "RFID tracking for spools", "U. Otaluka", "Active", "2026-02-10", "2026-05-01"),
                    ("Enable Distribution API", "IT", 2, "Expose distribution endpoints", "G. Akin", "Blocked", "2026-02-05", "2026-03-15"),
                    ("Reminder Notifications", "IT", 4, "Automated reminders in portal", "L. Van Hekken", "Planned", "2026-03-01", "2026-04-01"),
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
    """Parse YYYY-MM-DD string to date, returning None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """
    Fetch projects with optional filters:
      - pillar/status/owner: exact match (except "All")
      - priority: numeric/text compatible filter (except "All")
      - search: matches name/description (case-insensitive)
    Sorted by start_date then due_date; empty strings keep NULLs last.
    """
    q = f"SELECT * FROM {TABLE}"
    args: List[Any] = []
    where: List[str] = []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != "All":
                where.append(f"{col} = ?")
                args.append(filters[col])

        if filters.get("priority") and filters["priority"] != "All":
            # Compare as text to be robust even if DB type is TEXT/INTEGER mix
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
    """Return distinct non-empty values for a column as strings (sorted)."""
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
def priority_color(p: Union[str, int, float, None]) -> str:
    try:
        p = int(p)  # normalize
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

# ---- Sidebar: Bootstrap / Debug ----
with st.sidebar:
    st.subheader("Admin")
    needs_table = not ensure_table()
    if needs_table:
        st.warning("`projects` table not found. Use **Bootstrap** to create it.")

    colB1, colB2 = st.columns(2)
    do_seed = colB2.checkbox("Seed sample data", value=True)
    if colB1.button("Bootstrap table", use_container_width=True):
        bootstrap_db(seed=do_seed)
        # Clear caches so new values appear immediately
        fetch_df.clear()
        distinct_values.clear()
        st.success("Bootstrap completed.")
        st.rerun()

    st.markdown("---")
    if st.button("Show Projects Table Structure"):
        if ensure_table():
            with conn() as c:
                cur = c.cursor()
                cur.execute(f"PRAGMA table_info({TABLE})")
                st.write("### SQLite Table Columns:")
                st.code(cur.fetchall())
        else:
            st.info("Table does not exist yet.")

# Hint if table missing
if not ensure_table():
    st.info(
        "The application is ready. Click **Bootstrap table** from the sidebar to create "
        "the schema and (optionally) seed sample data."
    )

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

    if ensure_table():
        with conn() as c:
            existing = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

        options = ["New Project"] + existing["name"].astype(str).tolist()
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
                st.rerun()

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
    else:
        st.info("Editor is disabled until you bootstrap the table from the sidebar.")


# ----------------------------------------------------------
# TAB: DASHBOARD
# ----------------------------------------------------------

with tab_dashboard:
    st.markdown("## Dashboard")

    if ensure_table():
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

        # Ensure columns exist when DB is light
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

        # Sort by numeric priority ascending (1 = highest)
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
    else:
        st.info("Dashboard is disabled until you bootstrap the table from the sidebar.")


# ----------------------------------------------------------
# TAB: ROADMAP
# ----------------------------------------------------------

with tab_roadmap:
    st.markdown("## Roadmap")

    if ensure_table():
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
    else:
        st.info("Roadmap is disabled until you bootstrap the table from the sidebar.")
