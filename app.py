# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
import os
import io
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st


# ------------------ Optional dependencies ------------------
# PDF (ReportLab)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Plotly static image export (Kaleido + Chrome typically required)
try:
    import kaleido  # noqa: F401
    KALEIDO_AVAILABLE = True
except Exception:
    KALEIDO_AVAILABLE = False


# ------------------ Constants ------------------
DB_PATH = "portfolio.db"
TABLE = "projects"
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"

EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "pillar": "TEXT NOT NULL",
    "priority": "INTEGER DEFAULT 5",
    "description": "TEXT",
    "owner": "TEXT",
    "status": "TEXT",
    "start_date": "TEXT",
    "due_date": "TEXT",

    # NEW FIELDS:
    "plainsware_project": "TEXT DEFAULT 'No'",   # 'Yes'/'No'
    "plainsware_number": "INTEGER",             # optional, only if plainsware_project == 'Yes'
}


# ------------------ DB / Utility Helpers ------------------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def table_info(table: str) -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f"PRAGMA table_info({table})", c)


def ensure_schema_and_migrate() -> None:
    """
    Ensure the projects table exists and matches EXPECTED_COLUMNS.
    If the existing table has extra NOT NULL columns (no default) or missing required cols,
    rebuild the table and copy common columns.
    """
    with conn() as c:
        # Base create (new installs)
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
                plainsware_number INTEGER
            )
            """
        )
        c.commit()

        info = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
        existing_cols = info["name"].tolist()

        # Add missing nullable columns we can add safely
        missing = [col for col in EXPECTED_COLUMNS.keys() if col not in existing_cols]
        for col in missing:
            # SQLite cannot add NOT NULL columns without default reliably; rebuild for those.
            if col in ("name", "pillar", "id"):
                continue
            c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {EXPECTED_COLUMNS[col]}")
        c.commit()

        info = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
        existing_cols = info["name"].tolist()

        # If required columns missing, rebuild
        if "name" not in existing_cols or "pillar" not in existing_cols:
            _rebuild_projects_table(c)
            return

        # Detect extra NOT NULL columns with no default (these break inserts)
        extra_notnull = info[
            (~info["name"].isin(EXPECTED_COLUMNS.keys()))
            & (info["notnull"] == 1)
            & (info["dflt_value"].isna())
        ]
        if not extra_notnull.empty:
            _rebuild_projects_table(c)


def _rebuild_projects_table(c: sqlite3.Connection) -> None:
    """Rebuild projects table to match expected schema, copying intersecting columns."""
    old_info = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
    old_cols = old_info["name"].tolist()

    keep_cols = [col for col in EXPECTED_COLUMNS.keys() if col in old_cols and col != "id"]

    c.execute("BEGIN")
    c.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE}__new (
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
            plainsware_number INTEGER
        )
        """
    )

    if keep_cols:
        cols_csv = ", ".join(keep_cols)
        c.execute(
            f"""
            INSERT INTO {TABLE}__new ({cols_csv})
            SELECT {cols_csv} FROM {TABLE}
            """
        )

    c.execute(f"DROP TABLE {TABLE}")
    c.execute(f"ALTER TABLE {TABLE}__new RENAME TO {TABLE}")
    c.execute("COMMIT")


def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def try_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def safe_index(options: List[str], val: Optional[str], default: int = 0) -> int:
    try:
        if val in options:
            return options.index(val)
    except Exception:
        pass
    return default


@st.cache_data(show_spinner=False)
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


def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args, where = [], []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != ALL_LABEL:
                where.append(f"{col} = ?")
                args.append(filters[col])

        if filters.get("priority") and filters["priority"] != ALL_LABEL:
            where.append("priority = ?")
            try:
                args.append(int(filters["priority"]))
            except Exception:
                where.pop()

        if filters.get("search"):
            s = f"%{filters['search'].lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(start_date,''), COALESCE(due_date,'')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def fetch_all_projects() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f"SELECT * FROM {TABLE} ORDER BY id", c)


def status_to_state(x: Any) -> str:
    s = str(x).strip().lower()
    return "Completed" if s in {"done", "complete", "completed"} else "Ongoing"


def safe_int(x: Any, default: int = 5) -> int:
    try:
        return int(x)
    except Exception:
        return default


def clear_cached_lists() -> None:
    try:
        st.cache_data.clear()
    except Exception:
        pass


def build_pdf_report(df: pd.DataFrame, title: str = "Digital Portfolio Report") -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, height - 45, title)

    c.setFont("Helvetica", 10)
    c.drawString(40, height - 65, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawString(40, height - 80, f"Rows: {len(df)}")

    cols = [
        "id", "name", "pillar", "priority", "owner", "status", "start_date", "due_date",
        "plainsware_project", "plainsware_number"
    ]
    cols = [col for col in cols if col in df.columns]

    y = height - 110
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, " | ".join(cols))
    y -= 14

    c.setFont("Helvetica", 8)
    preview = df[cols].fillna("").head(40)
    for _, row in preview.iterrows():
        line = " | ".join(str(row[col])[:28] for col in cols)
        c.drawString(40, y, line)
        y -= 10
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 8)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


# ------------------ App Boot ------------------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# ------------------ Session State (RESET FIX) ------------------
# IMPORTANT: apply reset BEFORE widget instantiation (prevents StreamlitAPIException)
if "project_selector" not in st.session_state:
    st.session_state.project_selector = NEW_LABEL

if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False

if st.session_state.reset_project_selector:
    st.session_state.project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False


# ------------------ Project Editor ------------------
st.markdown("---")
st.subheader("Project Editor")

with conn() as c:
    df_projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

project_options = [NEW_LABEL] + [
    f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()
]

selected_project = st.selectbox(
    "Select Project to Edit",
    project_options,
    index=safe_index(project_options, st.session_state.project_selector),
    key="project_selector",
)

loaded_project = None
if selected_project != NEW_LABEL:
    try:
        project_id = int(selected_project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
        loaded_project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_project = None

pillar_list = distinct_values("pillar")
status_list = distinct_values("status")
owner_list = distinct_values("owner")

bcol1, bcol2 = st.columns([1, 1])
new_clicked = bcol1.button("New", key="btn_new_project")
clear_clicked = bcol2.button("Clear Filters", key="btn_clear_filters")

if new_clicked:
    # Use reset flag (safe) instead of assigning project_selector after widget exists
    st.session_state.reset_project_selector = True
    st.rerun()

if clear_clicked:
    for k in ["pillar_f", "status_f", "owner_f", "priority_f", "search_f"]:
        if k in st.session_state:
            del st.session_state[k]
    st.toast("Cleared filters.", icon="✅")


# ------------------ Form (Entry) ------------------
with st.form("project_form"):
    c1, c2 = st.columns(2)

    name_val = loaded_project.get("name") if loaded_project else ""
    pillar_val = loaded_project.get("pillar") if loaded_project else ""
    priority_val = int(loaded_project.get("priority", 5)) if loaded_project else 5
    owner_val = loaded_project.get("owner") if loaded_project else ""
    status_val = loaded_project.get("status") if loaded_project else ""
    start_val = try_date(loaded_project.get("start_date")) if loaded_project else date.today()
    due_val = try_date(loaded_project.get("due_date")) if loaded_project else date.today()
    desc_val = loaded_project.get("description") if loaded_project else ""

    # NEW: Plainsware defaults
    plainsware_val = loaded_project.get("plainsware_project", "No") if loaded_project else "No"
    plainsware_num_val = loaded_project.get("plainsware_number") if loaded_project else None

    # LEFT
    with c1:
        project_name = st.text_input("Name*", value=name_val, key="editor_name")

        pillar_options = pillar_list[:] if pillar_list else [""]
        pillar_index = pillar_options.index(pillar_val) if pillar_val in pillar_options else None
        project_pillar = st.selectbox(
            "Pillar*",
            options=pillar_options,
            index=pillar_index,
            placeholder="Select or type a new pillar…",
            accept_new_options=True,
            key="editor_pillar",
        )

        project_priority = st.number_input(
            "Priority",
            min_value=1,
            max_value=99,
            value=int(priority_val),
            step=1,
            format="%d",
            key="editor_priority",
        )

        description = st.text_area("Description", value=desc_val, height=120, key="editor_desc")

    # RIGHT
    with c2:
        owner_options = owner_list[:] if owner_list else [""]
        owner_index = owner_options.index(owner_val) if owner_val in owner_options else None
        project_owner = st.selectbox(
            "Owner",
            options=owner_options,
            index=owner_index,
            placeholder="Select or type a new owner…",
            accept_new_options=True,
            key="editor_owner",
        )

        project_status = st.selectbox(
            "Status",
            [""] + status_list,
            index=safe_index([""] + status_list, status_val),
            key="editor_status",
        )

        start_date = st.date_input("Start Date", value=start_val, key="editor_start")
        due_date = st.date_input("Due Date", value=due_val, key="editor_due")

        # NEW: Plainsware fields
        plainsware_project = st.selectbox(
            "Plainsware Project?",
            ["No", "Yes"],
            index=1 if str(plainsware_val).strip() == "Yes" else 0,
            key="editor_plainsware_project",
        )

        plainsware_number = None
        if plainsware_project == "Yes":
            # Require a number when Yes
            default_num = 1
            try:
                if plainsware_num_val is not None and str(plainsware_num_val).strip().isdigit():
                    default_num = int(plainsware_num_val)
            except Exception:
                pass

            plainsware_number = st.number_input(
                "Plainsware Project Number",
                min_value=1,
                step=1,
                value=default_num,
                format="%d",
                key="editor_plainsware_number",
            )

    col_a, col_b, col_c = st.columns(3)
    submitted_new = col_a.form_submit_button("Save New")
    submitted_update = col_b.form_submit_button("Update")
    submitted_delete = col_c.form_submit_button("Delete")


# ------------------ CRUD Actions (outside form) ------------------
def _clean(s: Any) -> str:
    return (s or "").strip()


if submitted_new:
    errors = []

    project_name_clean = _clean(project_name)
    project_pillar_clean = _clean(project_pillar)
    project_owner_clean = _clean(project_owner)
    project_status_clean = _clean(project_status)
    safe_priority = safe_int(project_priority, default=5)

    if not project_name_clean:
        errors.append("Name is required.")
    if not project_pillar_clean:
        errors.append("Pillar is required.")
    if not project_owner_clean:
        errors.append("Owner is required.")

    # NEW validation: if Plainsware Yes, require number
    pw_number_db = None
    if plainsware_project == "Yes":
        if plainsware_number is None:
            errors.append("Plainsware Project Number is required when Plainsware Project is Yes.")
        else:
            pw_number_db = safe_int(plainsware_number, default=0)
            if pw_number_db <= 0:
                errors.append("Plainsware Project Number must be a positive integer.")

    if errors:
        st.error(" ".join(errors))
    else:
        try:
            with conn() as c:
                c.execute(
                    f"""
                    INSERT INTO {TABLE}
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     plainsware_project, plainsware_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_name_clean,
                        project_pillar_clean,
                        safe_priority,
                        _clean(description),
                        project_owner_clean,
                        project_status_clean,
                        to_iso(start_date),
                        to_iso(due_date),
                        plainsware_project,
                        pw_number_db,
                    ),
                )
                c.commit()

            clear_cached_lists()
            st.success("✅ Project created successfully!")
            st.session_state.reset_project_selector = True
            st.rerun()

        except sqlite3.IntegrityError as e:
            st.error(f"SQLite IntegrityError: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected save error: {e}")
            st.stop()


if submitted_update:
    if not loaded_project:
        st.warning("Select an existing project to update.")
    else:
        errors = []

        project_name_clean = _clean(project_name)
        project_pillar_clean = _clean(project_pillar)
        project_owner_clean = _clean(project_owner)
        project_status_clean = _clean(project_status)
        safe_priority = safe_int(project_priority, default=5)

        if not project_name_clean:
            errors.append("Name is required.")
        if not project_pillar_clean:
            errors.append("Pillar is required.")
        if not project_owner_clean:
            errors.append("Owner is required.")

        # NEW validation: if Plainsware Yes, require number
        pw_number_db = None
        if plainsware_project == "Yes":
            if plainsware_number is None:
                errors.append("Plainsware Project Number is required when Plainsware Project is Yes.")
            else:
                pw_number_db = safe_int(plainsware_number, default=0)
                if pw_number_db <= 0:
                    errors.append("Plainsware Project Number must be a positive integer.")

        if errors:
            st.error(" ".join(errors))
        else:
            try:
                with conn() as c:
                    c.execute(
                        f"""
                        UPDATE {TABLE}
                        SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?,
                            plainsware_project=?, plainsware_number=?
                        WHERE id=?
                        """,
                        (
                            project_name_clean,
                            project_pillar_clean,
                            safe_priority,
                            _clean(description),
                            project_owner_clean,
                            project_status_clean,
                            to_iso(start_date),
                            to_iso(due_date),
                            plainsware_project,
                            pw_number_db,
                            int(loaded_project["id"]),
                        ),
                    )
                    c.commit()

                clear_cached_lists()
                st.success("✅ Project updated!")
                st.rerun()

            except sqlite3.IntegrityError as e:
                st.error(f"SQLite IntegrityError: {e}")
                st.stop()


if submitted_delete:
    if not loaded_project:
        st.warning("Select an existing project to delete.")
    else:
        try:
            with conn() as c:
                c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded_project["id"]),))
                c.commit()

            clear_cached_lists()
            st.warning("Project deleted.")
            st.session_state.reset_project_selector = True
            st.rerun()

        except sqlite3.IntegrityError as e:
            st.error(f"SQLite IntegrityError: {e}")
            st.stop()


# ------------------ Global Filters ------------------
st.markdown("---")
st.subheader("Filters")

colF1, colF2, colF3, colF4, colF6 = st.columns([1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + distinct_values("pillar")
statuses = [ALL_LABEL] + distinct_values("status")
owners = [ALL_LABEL] + distinct_values("owner")

priority_vals: List[int] = []
try:
    pv = distinct_values("priority")
    priority_vals = sorted({int(x) for x in pv if str(x).strip().isdigit()})
except Exception:
    pass
priority_opts = [ALL_LABEL] + [str(x) for x in priority_vals]

pillar_f = colF1.selectbox("Pillar", pillars, key="pillar_f")
status_f = colF2.selectbox("Status", statuses, key="status_f")
owner_f = colF3.selectbox("Owner", owners, key="owner_f")
priority_f = colF4.selectbox("Priority", priority_opts, key="priority_f")
search_f = colF6.text_input("Search", key="search_f")

filters = dict(pillar=pillar_f, status=status_f, owner=owner_f, priority=priority_f, search=search_f)
data = fetch_df(filters)

# ------------------ Derived Years ------------------
data["start_year"] = pd.to_datetime(data.get("start_date", ""), errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data.get("due_date", ""), errors="coerce").dt.year


# ------------------ Report Controls ------------------
st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"], key="year_mode")
year_col = "start_year" if year_mode == "Start Year" else "due_year"

years = [ALL_LABEL] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years, key="year_f")

top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5, key="top_n")
show_all = rc4.checkbox("Show ALL Reports", value=True, key="show_all_reports")

if not show_all:
    cK1, cK2, cK3, cK4 = st.columns(4)
    show_kpi = cK1.checkbox("KPI Cards", True, key="show_kpi")
    show_pillar_chart = cK2.checkbox("Pillar Status Chart", True, key="show_pillar_chart")
    show_roadmap = cK3.checkbox("Roadmap", True, key="show_roadmap")
    show_table = cK4.checkbox("Projects Table", True, key="show_table")
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != ALL_LABEL:
    data = data[data[year_col] == int(year_f)]

# ------------------ KPI Cards ------------------
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    total = len(data)
    completed = (data["status"].apply(status_to_state) == "Completed").sum()
    ongoing = (data["status"].apply(status_to_state) != "Completed").sum()
    pillars_count = data["pillar"].replace("", pd.NA).dropna().nunique()

    k1.metric("Projects", total)
    k2.metric("Completed", completed)
    k3.metric("Ongoing", ongoing)
    k4.metric("Distinct Pillars", int(pillars_count))

# ------------------ Pillar Status Chart ------------------
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    if not status_df.empty:
        status_df["state"] = status_df["status"].apply(status_to_state)
        pillar_summary = (
            status_df.groupby(["pillar", "state"], dropna=False)
            .size()
            .reset_index(name="count")
        )
        pillar_summary["pillar"] = pillar_summary["pillar"].replace("", "(Unspecified)")
        fig = px.bar(
            pillar_summary,
            x="pillar",
            y="count",
            color="state",
            barmode="group",
            title="Projects by Pillar — Completed vs Ongoing",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data available for pillar chart.")

# ------------------ Top N per Pillar ------------------
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")

if not data.empty:
    top_df = (
        data.replace({"pillar": {"": "(Unspecified)"}})
        .sort_values(["pillar", "priority", "name"], na_position="last")
        .groupby("pillar", dropna=False, as_index=False)
        .head(top_n)
    )
    st.dataframe(top_df, use_container_width=True)
else:
    st.info("No projects to display for Top N.")

# ------------------ Roadmap ------------------
roadmap_fig = None
if show_roadmap:
    st.markdown("---")
    st.subheader("Roadmap")

    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt.get("start_date", ""), errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt.get("due_date", ""), errors="coerce")
    gantt = gantt.dropna(subset=["Start", "Finish"])

    if not gantt.empty:
        roadmap_fig = px.timeline(
            gantt, x_start="Start", x_end="Finish", y="name", color="pillar",
            title="Project Timeline"
        )
        roadmap_fig.update_yaxes(autorange="reversed")
        st.plotly_chart(roadmap_fig, use_container_width=True)
    else:
        st.info("No valid date ranges to draw the roadmap.")

# ------------------ Projects Table ------------------
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    st.dataframe(data, use_container_width=True)

# ------------------ Export Options (outside form) ------------------
st.markdown("---")
st.subheader("Export Options")

st.download_button(
    "⬇️ Download CSV Report (Filtered)",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="portfolio_filtered.csv",
    mime="text/csv",
    key="export_csv_filtered",
)

full_df = fetch_all_projects()
st.download_button(
    "🗄️ Download FULL Database (CSV)",
    data=full_df.to_csv(index=False).encode("utf-8"),
    file_name="portfolio_full_database.csv",
    mime="text/csv",
    key="export_csv_full_db",
)

if REPORTLAB_AVAILABLE:
    pdf_bytes = build_pdf_report(data, title="Digital Portfolio Report (Filtered)")
    st.download_button(
        "🖨️ Download Printable Report (PDF)",
        data=pdf_bytes,
        file_name="portfolio_report_filtered.pdf",
        mime="application/pdf",
        key="export_pdf_filtered",
    )

if roadmap_fig is not None:
    st.markdown("---")
    st.subheader("Export Roadmap")

    st.download_button(
        "🌐 Download Roadmap (Interactive HTML)",
        data=roadmap_fig.to_html(include_plotlyjs="cdn"),
        file_name="roadmap.html",
        mime="text/html",
        key="export_roadmap_html",
    )

    if KALEIDO_AVAILABLE:
        try:
            img_bytes = pio.to_image(roadmap_fig, format="png", scale=2)
            st.download_button(
                "📸 Download Roadmap (PNG)",
                data=img_bytes,
                file_name="roadmap.png",
                mime="image/png",
                key="export_roadmap_png",
            )
        except Exception as e:
            st.info(f"PNG export unavailable in this runtime: {e}")

