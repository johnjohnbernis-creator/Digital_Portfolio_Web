# Digital Portfolio — Web Version
# --------------------------------
import os
import io
import sqlite3
from datetime import datetime, date
from typing import Optional, Dict, Any, List

import pandas as pd
import streamlit as st
import plotly.express as px


# ================== CONSTANTS ==================
DB_PATH = "portfolio.db"
TABLE = "projects"
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"


# ================== HELPERS ==================
def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def try_date(s):
    if not s:
        return date.today()
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return date.today()


def safe_int(x, default=5):
    try:
        return int(x)
    except Exception:
        return default


def status_to_state(x):
    return "Completed" if str(x).strip().lower() in ("done", "complete", "completed") else "Ongoing"


# ================== DB INIT ==================
def ensure_schema():
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT,
                plainsware_project TEXT DEFAULT 'No',
                plainsware_number INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.commit()


ensure_schema()


# ================== SESSION STATE INIT ==================
for key, default in {
    "project_selector": NEW_LABEL,
    "pillar_f": ALL_LABEL,
    "status_f": ALL_LABEL,
    "owner_f": ALL_LABEL,
    "priority_f": ALL_LABEL,
    "plainsware_f": ALL_LABEL,
    "search_f": "",
    "_filters_cleared": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ================== CLEAR FILTERS CALLBACK ==================
def reset_filters():
    st.session_state.pillar_f = ALL_LABEL
    st.session_state.status_f = ALL_LABEL
    st.session_state.owner_f = ALL_LABEL
    st.session_state.priority_f = ALL_LABEL
    st.session_state.plainsware_f = ALL_LABEL
    st.session_state.search_f = ""
    st.session_state._filters_cleared = True


# ================== PAGE ==================
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")


# ================== LOAD DATA ==================
def distinct(col):
    with conn() as c:
        df = pd.read_sql_query(
            f"SELECT DISTINCT {col} FROM {TABLE} WHERE {col} IS NOT NULL AND TRIM({col}) <> '' ORDER BY {col}", c
        )
    return df[col].astype(str).tolist()


def fetch_data(filters: Dict[str, Any]):
    q = f"SELECT * FROM {TABLE}"
    where, args = [], []

    for col in ["pillar", "status", "owner"]:
        v = filters.get(col)
        if v and v != ALL_LABEL:
            where.append(f"{col}=?")
            args.append(v)

    if filters.get("priority") != ALL_LABEL:
        where.append("priority=?")
        args.append(int(filters["priority"]))

    if filters.get("plainsware") != ALL_LABEL:
        where.append("plainsware_project=?")
        args.append(filters["plainsware"])

    if filters.get("search"):
        where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
        s = f"%{filters['search'].lower()}%"
        args += [s, s]

    if where:
        q += " WHERE " + " AND ".join(where)

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def fetch_one(project_id: int) -> Optional[Dict[str, Any]]:
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
    if df.empty:
        return None
    return df.iloc[0].to_dict()


# ================== PROJECT EDITOR ==================
st.subheader("Project Editor")

with conn() as c:
    projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

options = [NEW_LABEL] + [f"{r.id} — {r.name}" for r in projects.itertuples()]

colA, colB = st.columns([3, 1])

selected = colA.selectbox(
    "Select Project to Edit",
    options,
    key="project_selector",
)

colB.button("Clear Filters", on_click=reset_filters)

loaded = None
if selected != NEW_LABEL:
    try:
        pid = int(selected.split(" — ", 1)[0])
        loaded = fetch_one(pid)
    except Exception:
        loaded = None


# ================== EDIT FORM ==================
st.markdown("---")
with st.form("project_form"):
    c1, c2 = st.columns(2)

    # Defaults (from selected row)
    name_val = (loaded or {}).get("name", "")
    pillar_val = (loaded or {}).get("pillar", "")
    priority_val = int((loaded or {}).get("priority", 5) or 5)
    owner_val = (loaded or {}).get("owner", "")
    status_val = (loaded or {}).get("status", "")
    desc_val = (loaded or {}).get("description", "")

    start_val = try_date((loaded or {}).get("start_date"))
    due_val = try_date((loaded or {}).get("due_date"))

    pw_val = (loaded or {}).get("plainsware_project", "No") or "No"
    pw_num_val = (loaded or {}).get("plainsware_number", None)

    with c1:
        project_name = st.text_input("Name*", value=name_val)
        pillar_options = distinct("pillar")
        project_pillar = st.selectbox("Pillar*", options=(pillar_options or [""]), index=(pillar_options.index(pillar_val) if pillar_val in pillar_options else 0))
        project_priority = st.number_input("Priority", min_value=1, max_value=99, value=int(priority_val), step=1, format="%d")
        description = st.text_area("Description", value=desc_val, height=120)

    with c2:
        owner_options = distinct("owner")
        project_owner = st.selectbox("Owner*", options=(owner_options or [""]), index=(owner_options.index(owner_val) if owner_val in owner_options else 0))

        status_options = [""] + distinct("status")
        project_status = st.selectbox("Status", status_options, index=(status_options.index(status_val) if status_val in status_options else 0))

        start_date = st.date_input("Start Date", value=start_val)
        due_date = st.date_input("Due Date", value=due_val)

        # ✅ Plainsware selector
        plainsware_project = st.selectbox(
            "Plainsware Project?",
            ["No", "Yes"],
            index=1 if str(pw_val).strip() == "Yes" else 0,
        )

        # ✅ REQUIRED number when Yes
        plainsware_number = None
        if plainsware_project == "Yes":
            default_num = 1
            try:
                if pw_num_val is not None and str(pw_num_val).strip().isdigit():
                    default_num = int(pw_num_val)
            except Exception:
                pass

            plainsware_number = st.number_input(
                "Plainsware Project Number*",
                min_value=1,
                step=1,
                value=default_num,
                format="%d",
            )
            st.caption("Required when Plainsware Project is Yes.")

    b1, b2, b3 = st.columns(3)
    save_new = b1.form_submit_button("Save New")
    update = b2.form_submit_button("Update")
    delete = b3.form_submit_button("Delete")


# ================== VALIDATION + CRUD ==================
def clean(s):
    return (s or "").strip()


def validate_common():
    errors = []
    if not clean(project_name):
        errors.append("Name is required.")
    if not clean(project_pillar):
        errors.append("Pillar is required.")
    if not clean(project_owner):
        errors.append("Owner is required.")

    # ✅ NEW rule: if Plainsware Yes -> number required
    if plainsware_project == "Yes":
        if plainsware_number is None:
            errors.append("Plainsware Project Number is required when Plainsware Project is Yes.")
        else:
            n = safe_int(plainsware_number, default=0)
            if n <= 0:
                errors.append("Plainsware Project Number must be a positive integer.")

    return errors


if save_new:
    errs = validate_common()
    if errs:
        st.error(" ".join(errs))
    else:
        pw_number_db = safe_int(plainsware_number, default=0) if plainsware_project == "Yes" else None
        ts = now_ts()
        with conn() as c:
            c.execute(
                f"""
                INSERT INTO {TABLE}
                (name, pillar, priority, description, owner, status, start_date, due_date,
                 plainsware_project, plainsware_number,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean(project_name),
                    clean(project_pillar),
                    safe_int(project_priority, 5),
                    clean(description),
                    clean(project_owner),
                    clean(project_status),
                    to_iso(start_date),
                    to_iso(due_date),
                    plainsware_project,
                    pw_number_db,
                    ts,
                    ts,
                ),
            )
            c.commit()
        st.success("✅ Project created!")


if update:
    if not loaded:
        st.warning("Select an existing project to update.")
    else:
        errs = validate_common()
        if errs:
            st.error(" ".join(errs))
        else:
            pw_number_db = safe_int(plainsware_number, default=0) if plainsware_project == "Yes" else None
            ts = now_ts()
            with conn() as c:
                c.execute(
                    f"""
                    UPDATE {TABLE}
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?,
                        plainsware_project=?, plainsware_number=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        clean(project_name),
                        clean(project_pillar),
                        safe_int(project_priority, 5),
                        clean(description),
                        clean(project_owner),
                        clean(project_status),
                        to_iso(start_date),
                        to_iso(due_date),
                        plainsware_project,
                        pw_number_db,
                        ts,
                        int(loaded["id"]),
                    ),
                )
                c.commit()
            st.success("✅ Project updated!")


if delete:
    if not loaded:
        st.warning("Select an existing project to delete.")
    else:
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded["id"]),))
            c.commit()
        st.warning("Project deleted.")


# ================== FILTERS ==================
st.markdown("---")
st.subheader("Filters")

f1, f2, f3, f4, f5, f6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + distinct("pillar")
statuses = [ALL_LABEL] + distinct("status")
owners = [ALL_LABEL] + distinct("owner")
priorities = [ALL_LABEL] + sorted({str(x) for x in distinct("priority") if str(x).isdigit()})
plainsware_opts = [ALL_LABEL, "Yes", "No"]

f1.selectbox("Pillar", pillars, key="pillar_f")
f2.selectbox("Status", statuses, key="status_f")
f3.selectbox("Owner", owners, key="owner_f")
f4.selectbox("Priority", priorities, key="priority_f")
f5.selectbox("Plainsware", plainsware_opts, key="plainsware_f")
f6.text_input("Search", key="search_f")

if st.session_state._filters_cleared:
    st.toast("Filters cleared", icon="✅")
    st.session_state._filters_cleared = False


# ================== APPLY FILTERS ==================
filters = {
    "pillar": st.session_state.pillar_f,
    "status": st.session_state.status_f,
    "owner": st.session_state.owner_f,
    "priority": st.session_state.priority_f,
    "plainsware": st.session_state.plainsware_f,
    "search": st.session_state.search_f,
}
df = fetch_data(filters)


# ================== DASHBOARD ==================
st.markdown("---")
st.subheader("Summary")

c1, c2, c3 = st.columns(3)
c1.metric("Projects", len(df))
c2.metric("Completed", (df["status"].apply(status_to_state) == "Completed").sum() if not df.empty else 0)
c3.metric("Ongoing", (df["status"].apply(status_to_state) == "Ongoing").sum() if not df.empty else 0)

if not df.empty:
    fig = px.bar(
        df.groupby("pillar").size().reset_index(name="count"),
        x="pillar",
        y="count",
        title="Projects by Pillar",
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Projects")
st.dataframe(df, use_container_width=True)
