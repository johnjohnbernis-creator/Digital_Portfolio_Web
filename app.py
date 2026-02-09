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


# ---------- Utilities ----------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


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
    Sorted by start_date then due_date; empty strings used to keep NULLs last.
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

if not os.path.exists(DB_PATH):
    st.error("Database not found. Make sure 'portfolio.db' is present.")
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
