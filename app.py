# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
# Streamlit >= 1.28 recommended

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
    """Convert a date to 'YYYY-MM-DD' or return None."""
    if not d:
        return None
    return d.strftime("%Y-%m-%d")

def try_date(s: Optional[Union[str, date]]) -> Optional[date]:
    """Accept None/''/str/date; return datetime.date or None."""
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
    except Exception:
        st.experimental_rerun()

def ensure_schema():
    """Create table if it doesn't exist (non-destructive)."""
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
                start_date TEXT,    -- ISO: YYYY-MM-DD
                due_date TEXT       -- ISO: YYYY-MM-DD
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

# ---------- CRUD Helpers ----------
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
                rec.get("name"),
                rec.get("pillar"),
                _safe_int(rec.get("priority")),
                rec.get("description"),
                rec.get("owner"),
                rec.get("status"),
                rec.get("start_date") or None,
                rec.get("due_date") or None,
            ),
        )
        c.commit()
        return cur.lastrowid

def update_project(project_id: int, rec: Dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            f"""
            UPDATE {TABLE}
            SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
            WHERE id=?
            """,
            (
                rec.get("name"),
                rec.get("pillar"),
                _safe_int(rec.get("priority")),
                rec.get("description"),
                rec.get("owner"),
                rec.get("status"),
                rec.get("start_date") or None,
                rec.get("due_date") or None,
                project_id,
            ),
        )
        c.commit()

def delete_project(project_id: int) -> None:
    with conn() as c:
        c.execute(f"DELETE FROM {TABLE} WHERE id=?", (project_id,))
        c.commit()

def fetch_one_by_id(project_id: int) -> Optional[Dict[str, Any]]:
    with conn() as c:
        df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
    if df.empty:
        return None
    return df.iloc[0].to_dict()

# ---------- App ----------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

ensure_schema()

# ---------- Keys & Action Queue ----------
K_NAME = "w_name"
K_PILLAR = "w_pillar"
K_PRIORITY = "w_priority"
K_OWNER = "w_owner"
K_STATUS = "w_status"
K_START = "w_start"   # date
K_DUE = "w_due"       # date
K_DESC = "w_desc"
K_NO_START = "w_no_start"
K_NO_DUE = "w_no_due"

ACTION_KEY = "_pending_action"       # 'new' | 'clear' | 'load'
ACTION_PAYLOAD = "_pending_payload"  # e.g., {'id': 123}

# Initialize persistent state
st.session_state.setdefault("current_project_id", None)
st.session_state.setdefault("_loaded_id", None)

# Defaults for a blank form (NOTE: date_input needs a date; checkboxes control saving None)
DEFAULTS: Dict[str, Any] = {
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

def set_defaults():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v

# Queue an action and rerun (so we mutate state BEFORE widgets are created)
def queue_action(name: str, payload: Optional[Dict[str, Any]] = None):
    st.session_state[ACTION_KEY] = name
    st.session_state[ACTION_PAYLOAD] = payload or {}
    _rerun()

# ---------- Handle queued actions (runs BEFORE any widget is rendered) ----------
pending = st.session_state.pop(ACTION_KEY, None)
payload = st.session_state.pop(ACTION_PAYLOAD, None)

if pending == "new" or pending == "clear":
    st.session_state["current_project_id"] = None
    st.session_state["_loaded_id"] = None
    set_defaults()
elif pending == "load" and payload:
    # Set the record we want to load next; loader below will populate fields
    st.session_state["current_project_id"] = payload.get("id")
    st.session_state["_loaded_id"] = None  # force re-population

# Ensure defaults exist on first run
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

# ---------- Project Editor ----------
st.markdown("---")
# ---------- Project Editor (NONCE-based keys; safe for New/Save/Update/Clear) ----------
st.markdown("---")
st.subheader("Project")

from datetime import date

# --- helpers ---
def iso_or_none(d: Optional[date], keep_none_flag: bool) -> Optional[str]:
    if keep_none_flag:
        return None
    if not d:
        return None
    return d.strftime("%Y-%m-%d")

def parse_date_from_db(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except Exception:
        return None

# --- persistent state ---
st.session_state.setdefault("current_project_id", None)
st.session_state.setdefault("form_nonce", 0)       # drives all widget keys
st.session_state.setdefault("_loaded_id", None)    # which row is currently loaded into form

def bump_nonce_and_rerun():
    st.session_state["form_nonce"] += 1
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()

# Build options (before form)
pillar_values = distinct_values("pillar")
status_defaults = ["Idea", "Planned", "In Progress", "Blocked", "Done"]
status_values = status_defaults + [s for s in distinct_values("status") if s not in status_defaults]

# Load list for selector
with conn() as c:
    df_names = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name COLLATE NOCASE", c)

project_options = ["<New Project>"] + [f"{int(r['id'])} — {r['name']}" for _, r in df_names.iterrows()]
sel = st.selectbox("Load existing", project_options, index=0)

# Handle selection (no widget mutation; just set current id and bump keys)
if sel == "<New Project>":
    if st.session_state["current_project_id"] is not None:
        st.session_state["current_project_id"] = None
        st.session_state["_loaded_id"] = None
        bump_nonce_and_rerun()
else:
    try:
        selected_id = int(sel.split(" — ")[0])
        if selected_id != st.session_state.get("current_project_id"):
            st.session_state["current_project_id"] = selected_id
            st.session_state["_loaded_id"] = None
            bump_nonce_and_rerun()
    except Exception:
        pass

# Fetch currently loaded record (if any)
loaded = fetch_one_by_id(st.session_state["current_project_id"]) if st.session_state.get("current_project_id") else None

# Initial values for widgets
if loaded and st.session_state["_loaded_id"] != loaded.get("id"):
    # Ensure options contain values from the record
    if loaded.get("pillar") and loaded["pillar"] not in pillar_values:
        pillar_values = [loaded["pillar"]] + pillar_values
    if loaded.get("status") and loaded["status"] not in status_values:
        status_values = [loaded["status"]] + status_values

    init = {
        "name":        str(loaded.get("name") or ""),
        "pillar":      str(loaded.get("pillar") or ""),
        "priority":    int(loaded.get("priority") or 3),
        "owner":       str(loaded.get("owner") or ""),
        "status":      str(loaded.get("status") or "Idea"),
        "start_date":  parse_date_from_db(loaded.get("start_date")) or date.today(),
        "no_start":    loaded.get("start_date") in (None, "", "None"),
        "due_date":    parse_date_from_db(loaded.get("due_date")) or date.today(),
        "no_due":      loaded.get("due_date") in (None, "", "None"),
        "description": str(loaded.get("description") or ""),
    }
    st.session_state["_loaded_id"] = loaded.get("id")
else:
    # default blank/new
    init = {
        "name":        "",
        "pillar":      "",
        "priority":    3,
        "owner":       "",
        "status":      "Idea",
        "start_date":  date.today(),
        "no_start":    True,
        "due_date":    date.today(),
        "no_due":      True,
        "description": "",
    }

# All widget keys depend on nonce => brand‑new widgets after every action
N = st.session_state["form_nonce"]
def k(s: str) -> str:
    return f"{s}_{N}"

with st.form(f"project_form_{N}", clear_on_submit=False):
    lc1, lc2 = st.columns(2)

    name = lc1.text_input("Name*", value=init["name"], key=k("name"))
    pillar = lc1.selectbox("Pillar*", options=[""] + pillar_values, index=([""] + pillar_values).index(init["pillar"]) if init["pillar"] in pillar_values else 0, key=k("pillar"))
    priority = lc1.number_input("Priority", min_value=1, max_value=99, step=1, value=int(init["priority"]), key=k("priority"))

    owner = lc2.text_input("Owner", value=init["owner"], key=k("owner"))
    status = lc2.selectbox("Status", options=status_values, index=(status_values.index(init["status"]) if init["status"] in status_values else 0), key=k("status"))

    no_start = lc2.checkbox("No Start Date", value=bool(init["no_start"]), key=k("no_start"))
    start_dt = lc2.date_input("Start", value=init["start_date"], format="YYYY-MM-DD", key=k("start"))

    no_due = lc2.checkbox("No Due Date", value=bool(init["no_due"]), key=k("no_due"))
    due_dt = lc2.date_input("Due", value=init["due_date"], format="YYYY-MM-DD", key=k("due"))

    description = st.text_area("Description", value=init["description"], height=120, key=k("desc"))

    st.write("")
    b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 2])
    new_clicked    = b1.form_submit_button("New")
    save_clicked   = b2.form_submit_button("Save (Insert)")
    update_clicked = b3.form_submit_button("Update")
   rm_submit_button("Delete")
    clear_clicked  = b5.form_submit_button("Clear")

# Build record from current widget state (read from session_state using the dynamic keys)
rec = dict(
    name        = st.session_state.get(k("name"), "").strip(),
    pillar      = st.session_state.get(k("pillar"), "").strip(),
    priority    = _safe_int(st.session_state.get(k("priority"), 3), None),
    owner       = st.session_state.get(k("owner"), "").strip(),
    status      = st.session_state.get(k("status"), "").strip(),
    start_date  = iso_or_none(st.session_state.get(k("start")), st.session_state.get(k("no_start"), False)),
    due_date    = iso_or_none(st.session_state.get(k("due")),   st.session_state.get(k("no_due"), False)),
    description = st.session_state.get(k("desc"), "").strip(),
)

def missing_required(r: Dict[str, Any]) -> Optionalif not r["name"]:
        return "Name is required."
    if not r["pillar"]:
        return "Pillar is required."
    return None

# ---- Button handlers (NO widget key mutation — only DB + id + bump keys) ----
if new_clicked:
    st.session_state["current_project_id"] = None
    st.session_state["_loaded_id"] = None
    bump_nonce_and_rerun()

if clear_clicked:
    st.session_state["current_project_id"] = None
    st.session_state["_loaded_id"] = None
    bump_nonce_and_rerun()

if save_clicked:
    err = missing_required(rec)
    if err:
        st.error(err)
    else:
        try:
            new_id = insert_project(rec)
            st.success(f"Project inserted with id {new_id}.")
            st.session_state["current_project_id"] = new_id
            st.session_state["_loaded_id"] = None   # force load from DB next run
            bump_nonce_and_rerun()
        except sqlite3.IntegrityError as e:
            st.error("Insert failed due to a database integrity constraint.")
            st.exception(e)
        except Exception as e:
            st.error("Unexpected error while inserting the project.")
            st.exception(e)

if update_clicked:
    if not st.session_state.get("current_project_id"):
        st.warning("No project is loaded. Choose one or click 'Save (Insert)' for a new record.")
    else:
        err = missing_required(rec)
        if err:
            st.error(err)
        else:
            try:
                update_project(st.session_state["current_project_id"], rec)
                st.success(f"Project {st.session_state['current_project_id']} updated.")
                st.session_state["_loaded_id"] = None
                bump_nonce_and_rerun()
            except sqlite3.IntegrityError as e:
                st.error("Update failed due to a database integrity constraint.")
                st.exception(e)
            except Exception as e:
                st.error("Unexpected error while updating the project.")
                st.exception(e)

if delete_clicked:
    if not st.session_state.get("current_project_id"):
        st.warning("No project is loaded to delete.")
    else:
        try:
            delete_project(st.session_state["current_project_id"])
            st.success("Project deleted.")
            st.session_state["current_project_id"] = None
            st.session_state["_loaded_id"] = None
            bump_nonce_and_rerun()
        except Exception as e:
            st.error("Unexpected error while deleting the project.")
            st.exception(e)
