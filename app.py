# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
import os
import io
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

def init_db() -> None:
    """Create the projects table if it doesn't exist."""
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT NOT NULL,
                priority INTEGER,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        c.commit()

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
        df = pd.read_sql_query(q, c, params=args)

    # Ensure expected columns exist for first-run UX
    for col in [
        "id","name","pillar","priority","description","owner",
        "status","start_date","due_date","created_at","updated_at"
    ]:
        if col not in df.columns:
            df[col] = None

    return df

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

def upsert_project(payload: Dict[str, Any], project_id: Optional[int]) -> int:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn() as c:
        if project_id:
            c.execute(
                f"""
                UPDATE {TABLE}
                SET name=?, pillar=?, priority=?, description=?, owner=?,
                    status=?, start_date=?, due_date=?, updated_at=?
                WHERE id=?
                """,
                (
                    payload["name"], payload["pillar"], payload["priority"],
                    payload.get("description",""), payload.get("owner",""),
                    payload.get("status",""), payload.get("start_date",""),
                    payload.get("due_date",""), now, project_id
                )
            )
            c.commit()
            return project_id
        else:
            c.execute(
                f"""
                INSERT INTO {TABLE} 
                    (name, pillar, priority, description, owner, status,
                     start_date, due_date, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["name"], payload["pillar"], payload["priority"],
                    payload.get("description",""), payload.get("owner",""),
                    payload.get("status",""), payload.get("start_date",""),
                    payload.get("due_date",""), now, now
                )
            )
            c.commit()
            return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])

def delete_project(project_id: int) -> None:
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project_id,))
        c.commit()

def validate_payload(name: str, pillar: str, priority_val: Any,
                     start_s: str, due_s: str) -> Dict[str, Any]:
    # Name & pillar required
    if not name or not pillar:
        raise ValueError("Name and Pillar are required.")

    # Priority to int (allow blank → None)
    prio = None
    if priority_val not in (None, "", "None"):
        try:
            prio = int(priority_val)
        except Exception:
            raise ValueError("Priority must be an integer.")

    # Dates should be valid YYYY-MM-DD if provided
    for label, s in [("Start", start_s), ("Due", due_s)]:
        if s:
            if not try_date(s):
                raise ValueError(f"{label} date must be YYYY-MM-DD.")

    return {
        "name": name.strip(),
        "pillar": pillar.strip(),
        "priority": prio,
        "start_date": start_s.strip() if start_s else "",
        "due_date": due_s.strip() if due_s else ""
    }

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buff = io.StringIO()
    df.to_csv(buff, index=False)
    return buff.getvalue().encode("utf-8")

# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# Prepare DB
if not os.path.exists(DB_PATH):
    # Create the DB file so the app still loads with a friendly message
    init_db()
else:
    init_db()

# ---- Global Filters ----
colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = ["All"] + distinct_values("pillar") or ["All"]
statuses = ["All"] + distinct_values("status") or ["All"]
owners = ["All"] + distinct_values("owner") or ["All"]

priority_vals = distinct_values("priority")
priority_opts = ["All"] + sorted(set(priority_vals)) if priority_vals else ["All"]

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

data = fetch_df(filters)

# ---- Derived Years ----
data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

# ---- CRUD Form (New/Update/Delete/Clear + CSV export) ----
st.markdown("---")
st.subheader("Project")

form_left, form_right = st.columns([3, 2])

# Left: fields (like your screenshot layout)
with form_left:
    # Row to pick an existing project to edit
    existing_choices = ["(New)"] + [
        f"{row['id']}: {row['name']}" for _, row in data.sort_values("name", na_position="last").iterrows()
        if pd.notna(row["id"]) and pd.notna(row["name"])
    ]
    selected_str = st.selectbox("Select existing (for Update/Delete)", existing_choices, index=0)
    selected_id = None if selected_str == "(New)" else int(selected_str.split(":")[0])

    # Load selected values
    sel_row = data.loc[data["id"] == selected_id].iloc[0] if selected_id and not data.empty and (data["id"] == selected_id).any() else None

    def _get(v, default=""):
        return "" if pd.isna(v) else v

    default_name = _get(sel_row["name"]) if sel_row is not None else ""
    default_pillar = _get(sel_row["pillar"]) if sel_row is not None else (pillars[1] if len(pillars) > 1 else "")
    default_priority = _get(sel_row["priority"]) if sel_row is not None else 3
    default_desc = _get(sel_row["description"]) if sel_row is not None else ""
    default_owner = _get(sel_row["owner"]) if sel_row is not None else ""
    default_status = _get(sel_row["status"]) if sel_row is not None else (statuses[1] if len(statuses) > 1 else "")
    default_start = _get(sel_row["start_date"]) if sel_row is not None else ""
    default_due = _get(sel_row["due_date"]) if sel_row is not None else ""

    with st.form("project_form", clear_on_submit=False):
        colA, colB = st.columns([2, 1])
        name_i = colA.text_input("Name*", value=default_name)
        owner_i = colB.text_input("Owner", value=default_owner)

        colC, colD, colE = st.columns([1.2, 0.8, 1])
        pillar_i = colC.text_input("Pillar*", value=default_pillar)
        priority_i = colD.number_input("Priority", min_value=0, max_value=999, value=int(default_priority) if default_priority != "" else 3, step=1)
        status_i = colE.text_input("Status", value=default_status or "Idea")

        desc_i = st.text_area("Description", value=default_desc, height=120)

        colF, colG = st.columns(2)
        start_i = colF.text_input("Start (YYYY-MM-DD)", value=str(default_start))
        due_i = colG.text_input("Due (YYYY-MM-DD)", value=str(default_due))

        col_btn = st.columns([1,1,1,1,1])
        new_save = col_btn[0].form_submit_button("New / Save")
        update_btn = col_btn[1].form_submit_button("Update")
        delete_btn = col_btn[2].form_submit_button("Delete")
        clear_btn = col_btn[3].form_submit_button("Clear")
        export_btn = col_btn[4].form_submit_button("Export CSV")

    # Handle form actions
    if new_save or update_btn or delete_btn or clear_btn or export_btn:
        try:
            if delete_btn:
                if selected_id:
                    delete_project(selected_id)
                    st.success(f"Deleted project #{selected_id}.")
                    st.experimental_rerun()
                else:
                    st.warning("Select an existing project to delete.")

            elif clear_btn:
                st.experimental_rerun()

            elif export_btn:
                # export current filtered view
                csv_bytes = to_csv_bytes(data.drop(columns=["start_year","due_year"], errors="ignore"))
                st.download_button(
                    label="Download CSV (filtered)",
                    data=csv_bytes,
                    file_name=f"projects_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            else:
                # Save or Update flow
                payload = validate_payload(
                    name=name_i, pillar=pillar_i, priority_val=priority_i,
                    start_s=start_i, due_s=due_i
                )
                payload["description"] = desc_i
                payload["owner"] = owner_i
                payload["status"] = status_i

                if update_btn:
                    if not selected_id:
                        st.warning("Pick an existing project, then click Update.")
                    else:
                        upsert_project(payload, project_id=selected_id)
                        st.success(f"Updated project #{selected_id}.")
                        st.experimental_rerun()
                else:
                    # New / Save (insert new row)
                    new_id = upsert_project(payload, project_id=None)
                    st.success(f"Saved new project #{new_id}.")
                    st.experimental_rerun()

        except Exception as ex:
            st.error(str(ex))

# Right: quick CSV export (all) and jump-to-report
with form_right:
    st.caption("Quick Actions")
    full_df = fetch_df({})
    st.download_button(
        label="Export CSV (all projects)",
        data=to_csv_bytes(full_df.drop(columns=["start_year","due_year"], errors="ignore")),
        file_name=f"projects_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True
    )
    if st.button("Report & Roadmap ↓", use_container_width=True):
        st.write("")  # no-op; streamlit can't scroll programmatically without JS

# ---- Report Controls ----
st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])

year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"])
year_col = "start_year" if year_mode == "Start Year" else "due_year"

years = ["All"] + sorted([int(y) for y in data[year_col].dropna().unique().tolist()])
year_f = rc2.selectbox("Year", years)

top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5)

show_all = rc4.checkbox("Show ALL Reports", value=True)

# Individual toggles
if not show_all:
    # Give each a unique key so Streamlit doesn't reuse the same checkbox state
    show_kpi = rc4.checkbox("KPI Cards", True, key="kpi")
    show_pillar_chart = rc4.checkbox("Pillar Status Chart", True, key="pillar_chart")
    show_roadmap = rc4.checkbox("Roadmap", True, key="roadmap")
    show_table = rc4.checkbox("Projects Table", True, key="table")
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != "All":
    data = data[data[year_col] == int(year_f)]

# ---- KPI Cards ----
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)

    k1.metric("Projects", len(data))
    k2.metric("Completed", (data["status"].astype(str).str.lower() == "done").sum())
    k3.metric("Ongoing", (data["status"].astype(str).str.lower() != "done").sum())
    k4.metric("Distinct Pillars", data["pillar"].nunique())

# ---- Pillar Status Chart ----
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    status_df["state"] = status_df["status"].astype(str).str.lower().apply(
        lambda x: "Completed" if x == "done" else "Ongoing"
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
        )
        st.plotly_chart(fig, use_container_width=True)

# ---- Top N per Pillar ----
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")

top_df = (
    data.sort_values("priority", na_position="last")
    .groupby("pillar", dropna=False, as_index=False)
    .head(top_n)
)

st.dataframe(top_df, use_container_width=True)

# ---- Roadmap (UNCHANGED LOGIC) ----
if show_roadmap:
    st.markdown("---")
    st.subheader("Roadmap")

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
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

# ---- Projects Table ----
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    st.dataframe(data, use_container_width=True)
``
