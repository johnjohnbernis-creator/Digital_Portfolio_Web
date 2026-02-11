# Digital Portfolio — Web Version
# --------------------------------
import os
import io
import re
import sqlite3
from datetime import datetime, date
from typing import Optional, Dict, Any

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


def clean(s):
    return (s or "").strip()


# ================== DB INIT ==================
def ensure_schema():
    """
    We store plainsware_number as TEXT so it can be alphanumeric (letters+numbers).
    If an older DB has INTEGER affinity for plainsware_number, SQLite will still accept text,
    so we keep the migration simple.
    """
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
                plainsware_number TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.commit()


ensure_schema()


# ================== SESSION STATE INIT ==================
# Filters/session keys
for key, default in {
    "pillar_f": ALL_LABEL,
    "status_f": ALL_LABEL,
    "owner_f": ALL_LABEL,
    "priority_f": ALL_LABEL,
    "plainsware_f": ALL_LABEL,
    "search_f": "",
    "_filters_cleared": False,
}.items():
    st.session_state.setdefault(key, default)

# Stable project selection by ID
st.session_state.setdefault("selected_project_id", None)

# Form state keys (THIS is the key fix to always load selected project)
FORM_DEFAULTS = {
    "form_name": "",
    "form_pillar": "",
    "form_priority": 5,
    "form_description": "",
    "form_owner": "",
    "form_status": "",
    "form_start_date": date.today(),
    "form_due_date": date.today(),
    "form_plainsware_project": "No",
    "form_plainsware_number": "",  # alphanumeric text
}
for k, v in FORM_DEFAULTS.items():
    st.session_state.setdefault(k, v)


# ================== CLEAR FILTERS CALLBACK ==================
def reset_filters():
    st.session_state.pillar_f = ALL_LABEL
    st.session_state.status_f = ALL_LABEL
    st.session_state.owner_f = ALL_LABEL
    st.session_state.priority_f = ALL_LABEL
    st.session_state.plainsware_f = ALL_LABEL
    st.session_state.search_f = ""
    st.session_state._filters_cleared = True


# ================== LOAD DATA ==================
def distinct(col):
    with conn() as c:
        df = pd.read_sql_query(
            f"SELECT DISTINCT {col} FROM {TABLE} "
            f"WHERE {col} IS NOT NULL AND TRIM({col}) <> '' "
            f"ORDER BY {col}",
            c
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
    row = df.iloc[0].to_dict()
    # Always treat plainsware_number as string in the app
    row["plainsware_number"] = "" if row.get("plainsware_number") is None else str(row.get("plainsware_number"))
    return row


# ================== PROJECT LOADER (KEY FIX) ==================
def load_selected_into_form():
    """
    When selector changes, push DB values into form_* session_state keys.
    This forces the form to show the selected project values.
    """
    pid = st.session_state.selected_project_id

    # New Project
    if pid is None:
        for k, v in FORM_DEFAULTS.items():
            st.session_state[k] = v
        return

    row = fetch_one(int(pid))
    if not row:
        return

    st.session_state["form_name"] = row.get("name", "") or ""
    st.session_state["form_pillar"] = row.get("pillar", "") or ""
    st.session_state["form_priority"] = int(row.get("priority", 5) or 5)
    st.session_state["form_description"] = row.get("description", "") or ""
    st.session_state["form_owner"] = row.get("owner", "") or ""
    st.session_state["form_status"] = row.get("status", "") or ""
    st.session_state["form_start_date"] = try_date(row.get("start_date"))
    st.session_state["form_due_date"] = try_date(row.get("due_date"))
    st.session_state["form_plainsware_project"] = row.get("plainsware_project", "No") or "No"
    st.session_state["form_plainsware_number"] = str(row.get("plainsware_number", "") or "")


# ================== PAGE ==================
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

st.subheader("Project Editor")

# Build project selector as stable IDs
with conn() as c:
    projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

id_to_name = dict(zip(projects["id"], projects["name"]))
selector_options = [None] + projects["id"].tolist()

def fmt(pid):
    return NEW_LABEL if pid is None else f"{pid} — {id_to_name.get(pid, '')}"

colA, colB = st.columns([3, 1])

colA.selectbox(
    "Select Project to Edit",
    selector_options,
    format_func=fmt,
    key="selected_project_id",
    on_change=load_selected_into_form,
)

colB.button("Clear Filters", on_click=reset_filters)

# Ensure the form matches the selection on first render
if "_loaded_once" not in st.session_state:
    load_selected_into_form()
    st.session_state["_loaded_once"] = True

loaded = fetch_one(int(st.session_state.selected_project_id)) if st.session_state.selected_project_id else None


# ================== EDIT FORM ==================
st.markdown("---")
with st.form("project_form"):
    c1, c2 = st.columns(2)

    with c1:
        st.text_input("Name*", key="form_name")

        # Make sure current value is included even if not in distinct list
        pillar_options = sorted(set(distinct("pillar") + ([st.session_state["form_pillar"]] if st.session_state["form_pillar"] else [])))
        if not pillar_options:
            pillar_options = [""]

        st.selectbox("Pillar*", options=pillar_options, key="form_pillar")

        st.number_input("Priority", min_value=1, max_value=99, step=1, format="%d", key="form_priority")
        st.text_area("Description", height=120, key="form_description")

    with c2:
        owner_options = sorted(set(distinct("owner") + ([st.session_state["form_owner"]] if st.session_state["form_owner"] else [])))
        if not owner_options:
            owner_options = [""]

        st.selectbox("Owner*", options=owner_options, key="form_owner")

        status_options = [""] + sorted(set(distinct("status") + ([st.session_state["form_status"]] if st.session_state["form_status"] else [])))
        st.selectbox("Status", options=status_options, key="form_status")

        st.date_input("Start Date", key="form_start_date")
        st.date_input("Due Date", key="form_due_date")

        # ✅ Plainsware selector
        st.selectbox("Plainsware Project?", ["No", "Yes"], key="form_plainsware_project")

        # ✅ REQUIRED alphanumeric when Yes
        if st.session_state["form_plainsware_project"] == "Yes":
            st.text_input(
                "Plainsware Project Number*",
                key="form_plainsware_number",
                help="Letters + numbers only, no spaces. Example: PW123A"
            )
            st.caption("Required when Plainsware Project is Yes.")
        else:
            st.session_state["form_plainsware_number"] = ""

    b1, b2, b3 = st.columns(3)
    save_new = b1.form_submit_button("Save New")
    update = b2.form_submit_button("Update")
    delete = b3.form_submit_button("Delete")


# ================== VALIDATION + CRUD ==================
def validate_common():
    errors = []
    if not clean(st.session_state["form_name"]):
        errors.append("Name is required.")
    if not clean(st.session_state["form_pillar"]):
        errors.append("Pillar is required.")
    if not clean(st.session_state["form_owner"]):
        errors.append("Owner is required.")

    if st.session_state["form_plainsware_project"] == "Yes":
        v = clean(st.session_state["form_plainsware_number"])
        if not v:
            errors.append("Plainsware Project Number is required when Plainsware Project is Yes.")
        elif not re.fullmatch(r"[A-Za-z0-9]+", v):
            errors.append("Plainsware Project Number must contain ONLY letters and numbers (no spaces).")

    return errors


if save_new:
    errs = validate_common()
    if errs:
        st.error(" ".join(errs))
    else:
        pw_number_db = clean(st.session_state["form_plainsware_number"]) if st.session_state["form_plainsware_project"] == "Yes" else None
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
                    clean(st.session_state["form_name"]),
                    clean(st.session_state["form_pillar"]),
                    safe_int(st.session_state["form_priority"], 5),
                    clean(st.session_state["form_description"]),
                    clean(st.session_state["form_owner"]),
                    clean(st.session_state["form_status"]),
                    to_iso(st.session_state["form_start_date"]),
                    to_iso(st.session_state["form_due_date"]),
                    st.session_state["form_plainsware_project"],
                    pw_number_db,
                    ts,
                    ts,
                ),
            )
            c.commit()

            new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Select new project and reload
        st.session_state.selected_project_id = int(new_id)
        load_selected_into_form()
        st.success("✅ Project created!")
        st.rerun()


if update:
    if not loaded:
        st.warning("Select an existing project to update.")
    else:
        errs = validate_common()
        if errs:
            st.error(" ".join(errs))
        else:
            pw_number_db = clean(st.session_state["form_plainsware_number"]) if st.session_state["form_plainsware_project"] == "Yes" else None
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
                        clean(st.session_state["form_name"]),
                        clean(st.session_state["form_pillar"]),
                        safe_int(st.session_state["form_priority"], 5),
                        clean(st.session_state["form_description"]),
                        clean(st.session_state["form_owner"]),
                        clean(st.session_state["form_status"]),
                        to_iso(st.session_state["form_start_date"]),
                        to_iso(st.session_state["form_due_date"]),
                        st.session_state["form_plainsware_project"],
                        pw_number_db,
                        ts,
                        int(loaded["id"]),
                    ),
                )
                c.commit()

            load_selected_into_form()
            st.success("✅ Project updated!")
            st.rerun()


if delete:
    if not loaded:
        st.warning("Select an existing project to delete.")
    else:
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded["id"]),))
            c.commit()

        # Go back to new project
        st.session_state.selected_project_id = None
        load_selected_into_form()
        st.warning("Project deleted.")
        st.rerun()


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
