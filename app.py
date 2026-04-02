from __future__ import annotations

# ==========================================================
# Digital Portfolio — Clean & Safe Web App
# ==========================================================

import streamlit as st
import pandas as pd
import plotly.express as px
import sqlitecloud

from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, List

# ==========================================================
# Streamlit config (MUST BE FIRST)
# ==========================================================
st.set_page_config(
    page_title="Digital Portfolio",
    layout="wide",
)

st.title("📊 Digital Portfolio")

# ==========================================================
# Constants
# ==========================================================
TABLE = "projects"

PRESET_PILLARS = [
    "Digital Mindset",
    "Advanced Analytics",
    "Integration & Visualization",
    "Data Availability & Connectivity",
    "Smart Operations",
    "Vision Lab + Smart Operations",
]

PRESET_STATUSES = ["Planned", "In Progress", "Completed", "Idea"]
ALL_LABEL = "All"

# ==========================================================
# Utilities
# ==========================================================
def now_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def safe_index(options: List[str], value: str) -> int:
    return options.index(value) if value in options else 0


# ==========================================================
# Database connection (SAFE, NO DATA LOSS)
# ==========================================================
def _get_sqlitecloud_url() -> str:
    url = (st.secrets.get("SQLITECLOUD_URL_PORTFOLIO") or "").strip()
    if not url:
        st.error("Missing secret: SQLITECLOUD_URL_PORTFOLIO")
        st.stop()
    return url


@contextmanager
def conn():
    c = None
    try:
        c = sqlitecloud.connect(_get_sqlitecloud_url())

        db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()
        if db_name:
            c.execute(f'USE DATABASE "{db_name}"')

        yield c

    except Exception as e:
        st.error("🚨 Database connection failed")
        st.exception(e)
        st.stop()
    finally:
        if c:
            c.close()


# ==========================================================
# Schema — SAFE (does NOT overwrite existing data)
# ==========================================================
def ensure_schema():
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


ensure_schema()

# ==========================================================
# Data access
# ==========================================================
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
    return df[col].astype(str).tolist()


def load_projects(filters: Dict[str, Any]) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    clauses, args = [], []

    if filters["pillar"] != ALL_LABEL:
        clauses.append("pillar = ?")
        args.append(filters["pillar"])

    if filters["status"] != ALL_LABEL:
        clauses.append("status = ?")
        args.append(filters["status"])

    if filters["owner"] != ALL_LABEL:
        clauses.append("owner = ?")
        args.append(filters["owner"])

    if filters["search"]:
        clauses.append("(LOWER(name) LIKE ? OR LOWER(owner) LIKE ?)")
        s = f"%{filters['search'].lower()}%"
        args.extend([s, s])

    if clauses:
        q += " WHERE " + " AND ".join(clauses)

    q += " ORDER BY created_at DESC"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


# ==========================================================
# Sidebar filters
# ==========================================================
st.sidebar.header("Filters")

pillar_f = st.sidebar.selectbox(
    "Pillar",
    [ALL_LABEL] + PRESET_PILLARS,
)

status_f = st.sidebar.selectbox(
    "Status",
    [ALL_LABEL] + PRESET_STATUSES,
)

owner_f = st.sidebar.selectbox(
    "Owner",
    [ALL_LABEL] + distinct_values("owner"),
)

search_f = st.sidebar.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    search=search_f,
)

# ==========================================================
# Load data
# ==========================================================
data = load_projects(filters)

# ==========================================================
# KPIs
# ==========================================================
st.markdown("## 📌 KPIs")
k1, k2, k3 = st.columns(3)

k1.metric("Total Projects", len(data))
k2.metric("Completed", int((data["status"] == "Completed").sum()))
k3.metric("Distinct Pillars", int(data["pillar"].nunique()) if not data.empty else 0)

# ==========================================================
# Charts
# ==========================================================
if not data.empty:
    st.markdown("## 📊 Projects by Pillar")
    fig = px.bar(
        data,
        x="pillar",
        color="status",
        title="Projects by Pillar",
    )
    st.plotly_chart(fig, use_container_width=True)

# ==========================================================
# Table
# ==========================================================
st.markdown("## 📋 Projects")
st.dataframe(data, use_container_width=True)

# ==========================================================
# Exports
# ==========================================================
st.markdown("## ⬇️ Exports")

st.download_button(
    "Download Filtered CSV",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="digital_portfolio_filtered.csv",
    mime="text/csv",
)

with conn() as c:
    full_df = pd.read_sql_query(f"SELECT * FROM {TABLE}", c)

st.download_button(
    "Download FULL Database (CSV)",
    data=full_df.to_csv(index=False).encode("utf-8"),
    file_name="digital_portfolio_full.csv",
    mime="text/csv",
)
