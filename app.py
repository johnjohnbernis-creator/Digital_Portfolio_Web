# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
# Streamlit Cloud version (buttons FIXED — now outside the form)

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


def to_iso(d: Optional[date]) -> Optional[str]:
    if not d:
        return None
    return d.strftime("%Y-%m-%d")


def try_date(s: Optional[Union[str, date]]) -> Optional[date]:
    if isinstance(s, date):
        return s
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _rerun():
    try:
        st.rerun()
    except:
        st.experimental_rerun()


def ensure_schema():
    """Create table (old schema)"""
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
                due_date TEXT
            )
            """
        )
        c.commit()


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


# ---------- CRUD helpers ----------
def insert_project(rec: Dict[str, Any]) -> int:
    with conn() as c:
        cur = c.cursor()
        cur.execute(
            f"""
            INSERT INTO {TABLE}
            (name, pillar, priority, description, owner, status, start_date, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec["name"],
                rec["pillar"],
                _safe_int(rec["priority"]),
                rec["description"],
                rec["owner"],
                rec["status"],
                rec["start_date"],
                rec["due_date"],
            ),
        )
        c.commit()
        return cur.lastrowid


def update_project(pid: int, rec: Dict[str, Any]):
    with conn() as c:
        c.execute(
            f"""
            UPDATE {TABLE}
            SET name=?, pillar=?, priority=?, description=?, owner=?, status=?,
                start_date=?, due_date=?
            WHERE id=?
            """,
            (
                rec["name"],
                rec["pillar"],
                _safe_int(rec["priority"]),
                rec["description"],
                rec["owner"],
                rec["status"],
                rec["start_date"],
                rec["due_date"],
                pid,
            ),
        )
        c.commit()


def delete_project(pid: int):
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (pid,))
        c.commit()


def fetch_one_by_id(pid: int):
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[pid])
    if df.empty:
        return None
    return df.iloc[0].to_dict()


# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

ensure_schema()

# ---------- State ----------
st.session_state.setdefault("current_project_id", None)
st.session_state.setdefault("_loaded_id", None)

K_NAME = "name"
K_PILLAR = "pillar"
K_PRIORITY = "priority"
K_OWNER = "owner"
K_STATUS = "status"
K_START = "start"
K_DUE = "due"
K_DESC = "desc"
K_NO_START = "nostart"
K_NO_DUE = "nodue"

DEFAULTS = {
    K_NAME: "",
    K_PILLAR: "",
    K_PRIORITY: 3,
    K_OWNER: "",
    K_STATUS: "Idea",
    K_START: date.today(),
    K_DUE: date.today(),
    K_DESC: "",
    K_NO_START: True,
    K_NO_DUE: True,
}

for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def reset_form():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


# ---------- Project Selector ----------
st.subheader("Project")

with conn() as c:
    df_names = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

opts = ["<New Project>"] + [f"{int(r['id'])} — {r['name']}" for _, r in df_names.iterrows()]
sel = st.selectbox("Load existing", opts)

if sel == "<New Project>":
    if st.session_state["current_project_id"] is not None:
        st.session_state["current_project_id"] = None
        st.session_state["_loaded_id"] = None
        reset_form()
else:
    pid = int(sel.split(" — ")[0])
    if pid != st.session_state["current_project_id"]:
        st.session_state["current_project_id"] = pid
        st.session_state["_loaded_id"] = None

# ---------- LOAD SELECTED ----------
if st.session_state["current_project_id"]:
    rec = fetch_one_by_id(st.session_state["current_project_id"])
    if rec and st.session_state["_loaded_id"] != rec["id"]:
        st.session_state[K_NAME] = rec.get("name", "")
        st.session_state[K_PILLAR] = rec.get("pillar", "")
        st.session_state[K_PRIORITY] = rec.get("priority", 3)
        st.session_state[K_OWNER] = rec.get("owner", "")
        st.session_state[K_STATUS] = rec.get("status", "")

        sd = try_date(rec.get("start_date"))
        dd = try_date(rec.get("due_date"))

        st.session_state[K_START] = sd or date.today()
        st.session_state[K_DUE] = dd or date.today()
        st.session_state[K_NO_START] = sd is None
        st.session_state[K_NO_DUE] = dd is None

        st.session_state[K_DESC] = rec.get("description", "")
        st.session_state["_loaded_id"] = rec["id"]

# ---------- FORM ----------
with st.form("project_form"):
    c1, c2 = st.columns(2)

    c1.text_input("Name*", key=K_NAME)
    c1.text_input("Pillar*", key=K_PILLAR)
    c1.number_input("Priority", min_value=1, max_value=99, key=K_PRIORITY)

    c2.text_input("Owner", key=K_OWNER)
    c2.text_input("Status", key=K_STATUS)

    c2.checkbox("No Start Date", key=K_NO_START)
    c2.date_input("Start", key=K_START)

    c2.checkbox("No Due Date", key=K_NO_DUE)
    c2.date_input("Due", key=K_DUE)

    st.text_area("Description", height=120, key=K_DESC)

    submitted = st.form_submit_button("Apply Changes (no save)")


# ---------- BUTTONS OUTSIDE FORM (THE FIX) ----------
b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 2])

new_click = b1.button("New")
save_click = b2.button("Save (Insert)")
update_click = b3.button("Update")
del_click = b4.button("Delete")
clear_click = b5.button("Clear")

# ---------- CRUD ACTIONS ----------
def build_rec():
    return dict(
        name=st.session_state[K_NAME].strip(),
        pillar=st.session_state[K_PILLAR].strip(),
        priority=_safe_int(st.session_state[K_PRIORITY]),
        description=st.session_state[K_DESC].strip(),
        owner=st.session_state[K_OWNER].strip(),
        status=st.session_state[K_STATUS].strip(),
        start_date=None if st.session_state[K_NO_START] else to_iso(try_date(st.session_state[K_START])),
        due_date=None if st.session_state[K_NO_DUE] else to_iso(try_date(st.session_state[K_DUE])),
    )


if new_click:
    st.session_state["current_project_id"] = None
    st.session_state["_loaded_id"] = None
    reset_form()
    _rerun()

if clear_click:
    reset_form()
    st.session_state["current_project_id"] = None
    _rerun()

if save_click:
    rec = build_rec()
    if not rec["name"] or not rec["pillar"]:
        st.error("Name and Pillar are required.")
    else:
        new_id = insert_project(rec)
        st.success(f"Inserted with ID {new_id}")
        st.session_state["current_project_id"] = new_id
        st.session_state["_loaded_id"] = None
        _rerun()

if update_click:
    if not st.session_state["current_project_id"]:
        st.warning("No project loaded.")
    else:
        rec = build_rec()
        update_project(st.session_state["current_project_id"], rec)
        st.success("Updated.")
        st.session_state["_loaded_id"] = None
        _rerun()

if del_click:
    if not st.session_state["current_project_id"]:
        st.warning("Nothing to delete.")
    else:
        delete_project(st.session_state["current_project_id"])
        st.success("Deleted.")
        st.session_state["current_project_id"] = None
        reset_form()
        _rerun()


# ---------- Filters ----------
st.markdown("---")
st.subheader("Filters")

cF1, cF2, cF3, cF4, cF5 = st.columns([1,1,1,1,2])

pillars = ["All"] + distinct_values("pillar")
statuses = ["All"] + distinct_values("status")
owners = ["All"] + distinct_values("owner")
priority_vals = distinct_values("priority")
priority_opts = ["All"] + sorted(set(priority_vals))

pillar_f = cF1.selectbox("Pillar", pillars)
status_f = cF2.selectbox("Status", statuses)
owner_f = cF3.selectbox("Owner", owners)
priority_f = cF4.selectbox("Priority", priority_opts)
search_f = cF5.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    search=search_f,
)
data = fetch_df(filters)


# ---------- Reports ----------
st.markdown("---")
st.subheader("Projects")

st.dataframe(data, use_container_width=True)
