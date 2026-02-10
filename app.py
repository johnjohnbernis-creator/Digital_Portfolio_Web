# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
import os
import io
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Tuple

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

# Plotly static image export (Kaleido + Chrome usually required)
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

# ------------------ DB Helpers ------------------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def ensure_schema() -> None:
    """Create DB schema if not present."""
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
                start_date TEXT,  -- ISO YYYY-MM-DD
                due_date   TEXT   -- ISO YYYY-MM-DD
            )
            """
        )
        c.commit()

def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def try_date(s: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD safely."""
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

# ------------------ UI Helpers ------------------
def choose_or_type(
    label: str,
    existing_values: List[str],
    default_value: str = "",
    manual_label: str = "➕ Type manually…",
    key_prefix: str = "cot",
) -> Tuple[str, bool]:
    """
    Choose from existing values or type manually.
    Uses keys to prevent StreamlitDuplicateElementId. [1](https://deepwiki.com/plotly/plotly.py/5.2-static-image-export)[2](https://peerdh.com/blogs/programming-insights/streamlits-download-button-a-comprehensive-guide)
    """
    existing_values = existing_values or []
    options = [manual_label] + existing_values

    if default_value and default_value in existing_values:
        idx = options.index(default_value)
    else:
        idx = 0

    sel_key = f"{key_prefix}__select"
    txt_key = f"{key_prefix}__text"

    choice = st.selectbox(label, options, index=idx, key=sel_key)
    if choice == manual_label:
        typed = st.text_input(f"{label} (manual entry)", value=(default_value or ""), key=txt_key)
        return typed.strip(), True
    return choice.strip(), False

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

    cols = ["id", "name", "pillar", "priority", "owner", "status", "start_date", "due_date"]
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

ensure_schema()
if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

# ------------------ Project Editor ------------------
st.markdown("---")
st.subheader("Project Editor")

if "project_selector" not in st.session_state:
    st.session_state.project_selector = NEW_LABEL

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
    st.session_state.project_selector = NEW_LABEL
    st.rerun()

if clear_clicked:
    for k in ["pillar_f", "status_f", "owner_f", "priority_f", "search_f"]:
        if k in st.session_state:
            del st.session_state[k]
    st.toast("Cleared filters.", icon="✅")

# ------------------ Form ------------------
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

    with c1:
        project_name = st.text_input("Name*", value=name_val, key="editor_name")

        project_pillar, _ = choose_or_type(
            label="Pillar*",
            existing_values=pillar_list,
            default_value=pillar_val or "",
            key_prefix="editor_pillar",
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

    with c2:
        project_owner, _ = choose_or_type(
            label="Owner",
            existing_values=owner_list,
            default_value=owner_val or "",
            key_prefix="editor_owner",
        )

        project_status = st.selectbox(
            "Status",
            [""] + status_list,
            index=safe_index([""] + status_list, status_val),
            key="editor_status",
        )

        start_date = st.date_input("Start Date", value=start_val, key="editor_start")
        due_date = st.date_input("Due Date", value=due_val, key="editor_due")

    col_a, col_b, col_c = st.columns(3)
    submitted_new = col_a.form_submit_button("Save New")
    submitted_update = col_b.form_submit_button("Update")
    submitted_delete = col_c.form_submit_button("Delete")

# ------------------ CRUD Actions (outside the form) ------------------
def clear_cached_lists():
    try:
        st.cache_data.clear()
    except Exception:
        pass

def safe_int_priority(x: Any, default: int = 5) -> int:
    try:
        return int(x)
    except Exception:
        return default

if submitted_new:
    errors = []
    if not project_name:
        errors.append("Name is required.")
    if not project_pillar:
        errors.append("Pillar is required.")
    if not project_owner:
        errors.append("Owner is required.")

    safe_priority = safe_int_priority(project_priority, default=5)

    if errors:
        st.error(" ".join(errors))
    else:
        with conn() as c:
            c.execute(
                f"""
                INSERT INTO {TABLE}
                (name, pillar, priority, description, owner, status, start_date, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_name.strip(),
                    project_pillar.strip(),
                    safe_priority,
                    (description or "").strip(),
                    project_owner.strip(),
                    (project_status or "").strip(),
                    to_iso(start_date),
                    to_iso(due_date),
                ),
            )
            c.commit()

        clear_cached_lists()
        st.success("✅ Project created successfully!")
        st.session_state.project_selector = NEW_LABEL
        st.rerun()

if submitted_update:
    if not loaded_project:
        st.warning("Select an existing project to update.")
    else:
        errors = []
        if not project_name:
            errors.append("Name is required.")
        if not project_pillar:
            errors.append("Pillar is required.")
        if not project_owner:
            errors.append("Owner is required.")

        safe_priority = safe_int_priority(project_priority, default=5)

        if errors:
            st.error(" ".join(errors))
        else:
            with conn() as c:
                c.execute(
                    f"""
                    UPDATE {TABLE}
                    SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?
                    WHERE id=?
                    """,
                    (
                        project_name.strip(),
                        project_pillar.strip(),
                        safe_priority,
                        (description or "").strip(),
                        project_owner.strip(),
                        (project_status or "").strip(),
                        to_iso(start_date),
                        to_iso(due_date),
                        int(loaded_project["id"]),
                    ),
                )
                c.commit()

            clear_cached_lists()
            st.success("✅ Project updated!")
            st.rerun()

if submitted_delete:
    if not loaded_project:
        st.warning("Select an existing project to delete.")
    else:
        with conn() as c:
            c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded_project["id"]),))
            c.commit()

        clear_cached_lists()
        st.warning("Project deleted.")
        st.session_state.project_selector = NEW_LABEL
        st.rerun()

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

# Derived year columns
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
        pillar_summary = status_df.groupby(["pillar", "state"], dropna=False).size().reset_index(name="count")
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
            gantt,
            x_start="Start",
            x_end="Finish",
            y="name",
            color="pillar",
            title="Project Timeline",
        )
        roadmap_fig.update_yaxes(autorange="reversed")
        st.plotly_chart(roadmap_fig, use_container_width=True)
    else:
        st.info("No valid date ranges to draw the roadmap.")

# ------------------ Projects Table ------------------
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    if not data.empty:
        st.dataframe(data, use_container_width=True)
    else:
        st.info("No projects match your current filters.")

# ------------------ Export Options (outside the form) ------------------
# (download_button must not be inside st.form) [3](https://stackoverflow.com/questions/77120936/the-problem-with-displaying-an-application-through-an-iframe-in-streamlit-nothi)[4](https://deepwiki.com/streamlit/streamlit/7-widget-system)
st.markdown("---")
st.subheader("Export Options")

# Filtered CSV
st.download_button(
    "⬇️ Download CSV Report (Filtered)",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="portfolio_filtered.csv",
    mime="text/csv",
    key="export_csv_filtered",
)

# Full DB CSV
full_df = fetch_all_projects()
st.download_button(
    "🗄️ Download FULL Database (CSV)",
    data=full_df.to_csv(index=False).encode("utf-8"),
    file_name="portfolio_full_database.csv",
    mime="text/csv",
    key="export_csv_full_db",
)

# Printable PDF (only if reportlab exists)
if REPORTLAB_AVAILABLE:
    pdf_bytes = build_pdf_report(data, title="Digital Portfolio Report (Filtered)")
    st.download_button(
        "🖨️ Download Printable Report (PDF)",
        data=pdf_bytes,
        file_name="portfolio_report_filtered.pdf",
        mime="application/pdf",
        key="export_pdf_filtered",
    )

# Export Roadmap (always works as HTML; PNG only if Kaleido available)
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
        img_bytes = pio.to_image(roadmap_fig, format="png", scale=2)
        st.download_button(
            "📸 Download Roadmap (PNG)",
            data=img_bytes,
            file_name="roadmap.png",
            mime="image/png",
            key="export_roadmap_png",
        )
