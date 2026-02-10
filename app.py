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
st.subheader("Project")

pillar_values = distinct_values("pillar")
status_defaults = ["Idea", "Planned", "In Progress", "Blocked", "Done"]
status_values = status_defaults + [s for s in distinct_values("status") if s not in status_defaults]

# Selector for existing projects
with conn() as c:
    df_names = pd.read_sql_query(
        f"SELECT id, name FROM {TABLE} ORDER BY name COLLATE NOCASE", c
    )
project_options = ["<New Project>"] + [f"{int(r['id'])} — {r['name']}" for _, r in df_names.iterrows()]
sel = st.selectbox("Load existing", project_options, index=0)

if sel == "<New Project>":
    if st.session_state["current_project_id"] is not None:
        # Switching from a loaded record to New => queue reset
        queue_action("new")
else:
    try:
        selected_id = int(sel.split(" — ")[0])
        if selected_id != st.session_state.get("current_project_id"):
            queue_action("load", {"id": selected_id})
    except Exception:
        pass

# If we have a record selected and it's not yet populated into fields, populate now
loaded = None
if st.session_state.get("current_project_id"):
    loaded = fetch_one_by_id(st.session_state["current_project_id"])

if loaded and st.session_state["_loaded_id"] != loaded.get("id"):
    if loaded.get("pillar") and loaded["pillar"] not in pillar_values:
        pillar_values = [loaded["pillar"]] + pillar_values
    if loaded.get("status") and loaded["status"] not in status_values:
        status_values = [loaded["status"]] + status_values

    st.session_state[K_NAME] = str(loaded.get("name") or "")
    st.session_state[K_PILLAR] = str(loaded.get("pillar") or "")
    st.session_state[K_PRIORITY] = _safe_int(loaded.get("priority"), 3)
    st.session_state[K_OWNER] = str(loaded.get("owner") or "")
    st.session_state[K_STATUS] = str(loaded.get("status") or "Idea")

    start_parsed = try_date(loaded.get("start_date"))
    due_parsed = try_date(loaded.get("due_date"))
    st.session_state[K_START] = start_parsed or date.today()
    st.session_state[K_DUE] = due_parsed or date.today()
    st.session_state[K_NO_START] = start_parsed is None
    st.session_state[K_NO_DUE] = due_parsed is None

    st.session_state[K_DESC] = str(loaded.get("description") or "")
    st.session_state["_loaded_id"] = loaded.get("id")

# ---- Form (read clicks only; DO NOT mutate state here) ----
with st.form("project_form", clear_on_submit=False):
    lc1, lc2 = st.columns(2)

    lc1.text_input("Name*", key=K_NAME)
    lc1.selectbox("Pillar*", options=[""] + pillar_values, key=K_PILLAR)
    lc1.number_input("Priority", min_value=1, max_value=99, step=1, key=K_PRIORITY)

    lc2.text_input("Owner", key=K_OWNER)
    lc2.selectbox("Status", options=status_values, key=K_STATUS)

    lc2.checkbox("No Start Date", key=K_NO_START)
    lc2.date_input("Start", value=st.session_state[K_START], format="YYYY-MM-DD", key=K_START)

    lc2.checkbox("No Due Date", key=K_NO_DUE)
    lc2.date_input("Due", value=st.session_state[K_DUE], format="YYYY-MM-DD", key=K_DUE)

    st.text_area("Description", height=120, key=K_DESC)

    st.write("")  # spacer
    bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns([1, 1, 1, 1, 2])
    new_clicked     = bcol1.form_submit_button("New")
    save_clicked    = bcol2.form_submit_button("Save (Insert)")
    update_clicked  = bcol3.form_submit_button("Update")
    delete_clicked  = bcol4.form_submit_button("Delete")
    clear_clicked   = bcol5.form_submit_button("Clear")

# Build record to persist (outside the form)
start_out: Optional[str] = None if st.session_state[K_NO_START] else to_iso(try_date(st.session_state[K_START]))
due_out: Optional[str] = None if st.session_state[K_NO_DUE] else to_iso(try_date(st.session_state[K_DUE]))
rec = dict(
    name=(st.session_state[K_NAME] or "").strip(),
    pillar=(st.session_state[K_PILLAR] or "").strip(),
    priority=_safe_int(st.session_state[K_PRIORITY], None),
    description=(st.session_state[K_DESC] or "").strip(),
    owner=(st.session_state[K_OWNER] or "").strip(),
    status=(st.session_state[K_STATUS] or "").strip(),
    start_date=start_out,
    due_date=due_out,
)

def missing_required(r: Dict[str, Any]) -> Optional[str]:
    if not r["name"]:
        return "Name is required."
    if not r["pillar"]:
        return "Pillar is required."
    return None

# ---- Button handlers (queue action, then rerun) ----
if new_clicked:
    queue_action("new")

if clear_clicked:
    queue_action("clear")

if save_clicked:
    err = missing_required(rec)
    if err:
        st.error(err)
    else:
        try:
            new_id = insert_project(rec)
            st.success(f"Project inserted with id {new_id}.")
            queue_action("load", {"id": new_id})
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
                queue_action("load", {"id": st.session_state["current_project_id"]})
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
            queue_action("new")
        except Exception as e:
            st.error("Unexpected error while deleting the project.")
            st.exception(e)

# ---------- Filters ----------
st.markdown("---")
st.subheader("Filters")

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
search_f = colF6.text_input("Search")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    search=search_f,
)
data = fetch_df(filters)

# ---------- Reports ----------
# Derived Years
data["start_year"] = pd.to_datetime(data["start_date"], errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data["due_date"], errors="coerce").dt.year

st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"])
year_col = "start_year" if year_mode == "Start Year" else "due_year"
years = ["All"] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years)
top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5)
show_all = rc4.checkbox("Show ALL Reports", value=True)

if not show_all:
    show_kpi = rc4.checkbox("KPI Cards", True)
    show_pillar_chart = rc4.checkbox("Pillar Status Chart", True)
    show_roadmap = rc4.checkbox("Roadmap", True)
    show_table = rc4.checkbox("Projects Table", True)
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != "All":
    data = data[data[year_col] == int(year_f)]

# KPI
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Projects", len(data))
    k2.metric("Completed", (data["status"].str.lower() == "done").sum())
    k3.metric("Ongoing", (data["status"].str.lower() != "done").sum())
    k4.metric("Distinct Pillars", data["pillar"].nunique())

# Pillar Status
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    status_df["state"] = status_df["status"].apply(
        lambda x: "Completed" if str(x).lower() == "done" else "Ongoing"
    )
    pillar_summary = (
        status_df.groupby(["pillar", "state"]).size().reset_index(name="count")
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

# Top N per Pillar
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")
top_df = (
    data.sort_values("priority", na_position="last")
    .groupby("pillar", as_index=False, sort=False)
    .head(top_n)
)
st.dataframe(top_df, use_container_width=True)

# Roadmap
if show_roadmap:
    st.markdown("---")
    st.subheader("Roadmap")
    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt["start_date"], errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt["due_date"], errors="coerce")
    gantt = gantt.dropna(subset=["Start", "Finish"])
    if not gantt.empty:
        fig = px.timeline(gantt, x_start="Start", x_end="Finish", y="name", color="pillar")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

# Projects Table
st.markdown("---")
st.subheader("Projects")
st.dataframe(data, use_container_width=True)

# CSV Export
st.markdown("---")
st.subheader("Export")
exp1, exp2 = st.columns([1, 1])
csv_filtered = data.to_csv(index=False).encode("utf-8")
exp1.download_button(
    label="Export Filtered CSV",
    data=csv_filtered,
    file_name=f"projects_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)
with conn() as c:
    df_all = pd.read_sql_query(f"SELECT * FROM {TABLE} ORDER BY name COLLATE NOCASE", c)
csv_all = df_all.to_csv(index=False).encode("utf-8")
exp2.download_button(
    label="Export ALL CSV",
    data=csv_all,
    file_name=f"projects_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)
