# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
# Requires:
#   pip install streamlit pandas plotly
#
# Run:
#   streamlit run app.py
#
# DB schema (table: projects)
#   id (INTEGER PK), name (TEXT), pillar (TEXT), start_date (TEXT, 'YYYY-MM-DD'),
#   due_date (TEXT), owner (TEXT), status (TEXT), priority (INTEGER),
#   description (TEXT), created_at (TEXT), updated_at (TEXT)

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
    # Create a connection to the SQLite database
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def to_iso(d: Optional[date]) -> str:
    # Return date as YYYY-MM-DD or empty string
    if not d:
        return ""
    return d.strftime("%Y-%m-%d")


def try_date(s: Optional[str]) -> Optional[date]:
    # Parse 'YYYY-MM-DD' to date; return None on failure or if empty
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    # Fetch filtered project rows as a DataFrame
    q = f"SELECT * FROM {TABLE}"
    args: List[Any] = []
    where: List[str] = []

    if filters:
        if filters.get("pillar") and filters["pillar"] != "All":
            where.append("pillar = ?")
            args.append(filters["pillar"])

        if filters.get("status") and filters["status"] != "All":
            where.append("status = ?")
            args.append(filters["status"])

        if filters.get("owner") and filters["owner"] != "All":
            where.append("owner = ?")
            args.append(filters["owner"])

        if filters.get("priority") and filters["priority"] != "All":
            where.append("CAST(priority AS TEXT) = ?")
            args.append(str(filters["priority"]))

        if filters.get("search"):
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            s = f"%{str(filters['search']).lower()}%"
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(start_date, ''), COALESCE(due_date, '')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def distinct_values(col: str) -> List[str]:
    # Return distinct non-empty string values for a column
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


def get_all_projects() -> pd.DataFrame:
    # Return id+name for all projects (for dropdown)
    with conn() as c:
        return pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)


def get_project(pid: int) -> Optional[Dict[str, Any]]:
    # Return a single project row as dict, or None
    with conn() as c:
        cur = c.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def insert_project(values: Dict[str, Any]) -> int:
    # Insert a project and return its new id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = {**values, "created_at": now, "updated_at": now}
    cols = ",".join(values.keys())
    qmarks = ",".join(["?"] * len(values))
    with conn() as c:
        cur = c.execute(
            f"INSERT INTO {TABLE} ({cols}) VALUES ({qmarks})",
            tuple(values.values()),
        )
        c.commit()
        return cur.lastrowid


def update_project(pid: int, values: Dict[str, Any]) -> None:
    # Update a project by id
    values = {**values, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    set_clause = ", ".join([f"{k}=?" for k in values.keys()])
    with conn() as c:
        c.execute(
            f"UPDATE {TABLE} SET {set_clause} WHERE id = ?",
            (*values.values(), pid),
        )
        c.commit()


def delete_project(pid: int) -> None:
    # Delete a project by id
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id = ?", (pid,))
        c.commit()


def ensure_db() -> None:
    # Create the table if it does not exist (no overwrite)
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY,
                name TEXT, pillar TEXT, start_date TEXT, due_date TEXT,
                owner TEXT, status TEXT, priority INTEGER, description TEXT,
                created_at TEXT, updated_at TEXT
            );
            """
        )
        c.commit()


def _safe_rerun() -> None:
    # Streamlit rerun helper for compatibility across versions
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

if not os.path.exists(DB_PATH):
    st.error(
        f"Database not found at `{DB_PATH}`. Place `portfolio.db` next to `app.py` and reload."
    )
    st.stop()

ensure_db()

# ---- Global Filters (top) ----
colF1, colF2, colF3, colF4, colF5 = st.columns([1, 1, 1, 1, 2])
pillars = ["All"] + distinct_values("pillar")
statuses = ["All"] + distinct_values("status")
owners = ["All"] + distinct_values("owner")

# Priority options (robust: list -> Series to use dropna/astype)
priority_vals = distinct_values("priority")
if priority_vals:
    s = pd.Series(priority_vals, dtype="object")
    nums = pd.to_numeric(s, errors="coerce").dropna().astype(int).unique()
    priority_opts = ["All"] + [str(p) for p in sorted(nums.tolist())]
else:
    priority_opts = ["All"]

pillar_f = colF1.selectbox("Pillar", options=pillars, index=0)
status_f = colF2.selectbox("Status", options=statuses, index=0)
owner_f = colF3.selectbox("Owner", options=owners, index=0)  # filter dropdown only
priority_f = colF4.selectbox("Priority", options=priority_opts, index=0)
search_f = colF5.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    search=search_f,
)
data = fetch_df(filters)

st.subheader("Projects")
st.dataframe(data)  # keep compatible with older Streamlit

# ---- HMI / CRUD ----
st.markdown("---")
st.subheader("Project Editor")

# Selection by DROPDOWN (Option B)
all_projects = get_all_projects()
options = ["— New —"] + [
    f"{row['name']}  (id:{row['id']})" for _, row in all_projects.iterrows()
]
sel_label = st.selectbox("Select project to edit", options=options, index=0)


def parse_id(label: str) -> Optional[int]:
    # Extract the integer id from a selection label like 'Name  (id:123)'
    if "id:" not in label:
        return None
    try:
        return int(label.split("id:")[-1].rstrip(")"))
    except Exception:
        return None


selected_id = parse_id(sel_label)

# Load selected record or start blank
rec: Dict[str, Any] = get_project(selected_id) if selected_id is not None else {}
rec = rec or {}

# Prepare option lists for dropdowns (allow typing new values in form only)
pillar_list = sorted(
    set(distinct_values("pillar") + ([rec.get("pillar")] if rec.get("pillar") else []))
)
owner_list = sorted(
    set(distinct_values("owner") + ([rec.get("owner")] if rec.get("owner") else []))
)
status_list = sorted(
    set(distinct_values("status") + ([rec.get("status")] if rec.get("status") else []))
)

with st.form("editor_form", clear_on_submit=False):
    c1, c2 = st.columns(2)

    # ---------------- Column 1 ----------------
    with c1:
        # Name
        name = st.text_input("Name*", value=rec.get("name", ""))

        # Pillar (free-text option)
        PILLAR_NEW_LABEL = "⟶ Type a new pillar…"

        pillar_options = pillar_list.copy()
        if rec.get("pillar") and rec["pillar"] not in pillar_options:
            pillar_options = [rec["pillar"]] + pillar_options
        pillar_options = [PILLAR_NEW_LABEL] + (pillar_options if pillar_options else [""])

        if rec.get("pillar") and rec["pillar"] in pillar_options:
            pillar_default_idx = pillar_options.index(rec["pillar"])
        else:
            pillar_default_idx = 0

        pillar_choice = st.selectbox("Pillar*", options=pillar_options, index=pillar_default_idx)
        if pillar_choice == PILLAR_NEW_LABEL:
            pillar = st.text_input("New pillar*", value=rec.get("pillar", "")).strip()
        else:
            pillar = str(pillar_choice).strip()

        # Priority
        try:
            pr_default = int(rec.get("priority")) if rec.get("priority") is not None else 3
        except Exception:
            pr_default = 3
        priority = st.number_input("Priority*", min_value=1, max_value=9, value=pr_default)

        # Description
        description = st.text_area("Description", value=rec.get("description", ""), height=140)

    # ---------------- Column 2 ----------------
    with c2:
        # Owner (free-text option)
        OWNER_NEW_LABEL = "⟶ Type a new owner…"

        owner_options = owner_list.copy()
        if rec.get("owner") and rec["owner"] not in owner_options:
            owner_options = [rec["owner"]] + owner_options
        owner_options = [OWNER_NEW_LABEL] + (owner_options if owner_options else [""])

        if rec.get("owner") and rec["owner"] in owner_options:
            owner_default_idx = owner_options.index(rec["owner"])
        else:
            owner_default_idx = 0

        owner_choice = st.selectbox("Owner*", options=owner_options, index=owner_default_idx)
        if owner_choice == OWNER_NEW_LABEL:
            owner = st.text_input("New owner name*", value=rec.get("owner", "")).strip()
        else:
            owner = str(owner_choice).strip()

        # Status (free-text option)
        STATUS_NEW_LABEL = "⟶ Type a new status…"

        status_options = status_list.copy()
        if rec.get("status") and rec["status"] not in status_options:
            status_options = [rec["status"]] + status_options
        status_options = [STATUS_NEW_LABEL] + (status_options if status_options else [""])

        if rec.get("status") and rec["status"] in status_options:
            status_default_idx = status_options.index(rec["status"])
        else:
            status_default_idx = 0

        status_choice = st.selectbox("Status*", options=status_options, index=status_default_idx)
        if status_choice == STATUS_NEW_LABEL:
            status = st.text_input("New status*", value=rec.get("status", "")).strip()
        else:
            status = str(status_choice).strip()

        # Dates
        start_d = st.date_input(
            "Start (YYYY-MM-DD)", value=try_date(rec.get("start_date")) or date.today()
        )
        due_d = st.date_input(
            "Due (YYYY-MM-DD)", value=try_date(rec.get("due_date")) or date.today()
        )

    # Buttons
    bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns([1, 1, 1, 1, 2])
    new_clicked = bcol1.form_submit_button("New")
    save_clicked = bcol2.form_submit_button("Save (Insert)")
    update_clicked = bcol3.form_submit_button("Update")
    delete_clicked = bcol4.form_submit_button("Delete")
    clear_clicked = bcol5.form_submit_button("Clear")

    # Handle actions
    if new_clicked or clear_clicked:
        _safe_rerun()

    payload = {
        "name": name.strip(),
        "pillar": pillar.strip(),
        "priority": int(priority),
        "owner": owner.strip(),
        "status": status.strip(),
        "start_date": to_iso(start_d),
        "due_date": to_iso(due_d),
        "description": description.strip(),
    }

    # Basic validation
    valid = all([payload["name"], payload["pillar"], payload["owner"], payload["status"]])

    if save_clicked:
        if not valid:
            st.error("Please fill required fields marked with * before saving.")
        else:
            new_id = insert_project(payload)
            st.success(f"Inserted project with id {new_id}.")
            _safe_rerun()

    if update_clicked:
        if selected_id is None:
            st.error("Select an existing project from the dropdown to update.")
        elif not valid:
            st.error("Please fill required fields marked with * before updating.")
        else:
            update_project(selected_id, payload)
            st.success(f"Updated project id {selected_id}.")
            _safe_rerun()

    if delete_clicked:
        if selected_id is None:
            st.error("Select a project from the dropdown to delete.")
        else:
            delete_project(selected_id)
            st.success(f"Deleted project id {selected_id}.")
            _safe_rerun()

# ---- Export CSV ----
st.markdown("---")
csv_data = data.to_csv(index=False).encode("utf-8")
st.download_button(
    "Export CSV (Filtered)",
    data=csv_data,
    file_name="digital_portfolio_filtered.csv",
    mime="text/csv",
)

# ---- KPIs + Roadmap Report ----
st.markdown("---")
st.subheader("Report & Roadmap")

# KPI tiles
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
by_pillar = (
    data["pillar"].value_counts(dropna=True) if "pillar" in data.columns else pd.Series(dtype=int)
)
by_status = (
    data["status"].value_counts(dropna=True) if "status" in data.columns else pd.Series(dtype=int)
)
earliest = (
    pd.to_datetime(data["start_date"], errors="coerce").min()
    if "start_date" in data.columns
    else pd.NaT
)
latest = (
    pd.to_datetime(data["due_date"], errors="coerce").max()
    if "due_date" in data.columns
    else pd.NaT
)

kpi1.metric("Distinct Pillars", len(by_pillar.index))
kpi2.metric("Distinct Statuses", len(by_status.index))
kpi3.metric("Earliest Start", earliest.strftime("%Y-%m-%d") if pd.notna(earliest) else "—")
kpi4.metric("Latest Due", latest.strftime("%Y-%m-%d") if pd.notna(latest) else "—")

# Gantt
fig: Optional[Any] = None
if {"name", "start_date", "due_date"}.issubset(set(data.columns)):
    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt["start_date"], errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt["due_date"], errors="coerce")
    gantt = gantt.dropna(subset=["Start", "Finish"])
    if not gantt.empty:
        kwargs = dict(x_start="Start", x_end="Finish", y="name")
        if "pillar" in gantt.columns:
            kwargs["color"] = "pillar"
        fig = px.timeline(gantt, **kwargs)
        fig.update_yaxes(autorange="reversed")
        # Older Streamlit may not support use_container_width here
        try:
            st.plotly_chart(fig, use_container_width=True)
        except TypeError:
            st.plotly_chart(fig)
    else:
        st.info("No valid Start/Due dates to draw a roadmap.")
else:
    st.info("Roadmap requires columns: name, start_date, due_date.")

# Download HTML report (KPIs + Gantt + table)
with st.expander("Generate HTML Report"):
    st.write("Click to download a self-contained HTML snapshot (KPIs + roadmap + current table).")

    table_html = data.to_html(index=False)
    chart_html = ""
    try:
        if fig is not None:
            chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    except Exception:
        pass

    kpi_html = f"""
    <div style="display:flex;gap:20px;margin:10px 0;">
      <div><b>Distinct Pillars:</b> {len(by_pillar.index)}</div>
      <div><b>Distinct Statuses:</b> {len(by_status.index)}</div>
      <div><b>Earliest Start:</b> {earliest.strftime('%Y-%m-%d') if pd.notna(earliest) else '—'}</div>
      <div><b>Latest Due:</b> {latest.strftime('%Y-%m-%d') if pd.notna(latest) else '—'}</div>
    </div>
    """

    html = f"""
    <html>
      <head>
        <meta charset="utf-8">
        <title>Digital Portfolio — Report & Roadmap</title>
      </head>
      <body>
        <h2>Digital Portfolio — Report & Roadmap</h2>
        {kpi_html}
        <h3>Roadmap</h3>
        {chart_html}
        <h3>Projects (Filtered)</h3>
        {table_html}
      </body>
    </html>
    """

    st.download_button(
        "Download HTML Report",
        data=html.encode("utf-8"),
        file_name="Digital_Portfolio_Report.html",
        mime="text/html",
    )