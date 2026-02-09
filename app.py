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


def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


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


def ensure_db() -> None:
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY,
                name TEXT, pillar TEXT, start_date TEXT, due_date TEXT,
                owner TEXT, status TEXT, priority INTEGER,
                description TEXT, created_at TEXT, updated_at TEXT
            );
            """
        )
        c.commit()


# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

ensure_db()

# ---- Filters ----
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
year_placeholder = colF5.empty()
search_f = colF6.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    search=search_f,
)

data = fetch_df(filters)

# ---- Derived Year (NO DB CHANGE) ----
data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
years = ["All"] + sorted(data["start_year"].dropna().astype(int).unique().tolist())
year_f = year_placeholder.selectbox("Year", years)

if year_f != "All":
    data = data[data["start_year"] == int(year_f)]

# ---- Projects Table ----
st.subheader("Projects")
st.dataframe(data, use_container_width=True)

# ---- Reports ----
st.markdown("---")
st.subheader("Report & Roadmap")

# ---- Pillar Status Chart ----
status_df = data.copy()
status_df["state"] = status_df["status"].apply(
    lambda x: "Completed" if str(x).lower() == "done" else "Ongoing"
)

pillar_summary = (
    status_df.groupby(["pillar", "state"])
    .size()
    .reset_index(name="count")
)

if not pillar_summary.empty:
    fig = px.bar(
        pillar_summary,
        x="pillar",
        y="count",
        color="state",
        barmode="group",
        title="Projects by Pillar — Completed vs Ongoing",
        labels={"pillar": "Pillar", "count": "Projects", "state": "Status"},
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No data available for selected filters.")
