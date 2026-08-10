from __future__ import annotations

# ==========================================================
# Digital Portfolio
# Roadmap visible | KPI TRIFORCE priority | Year filter
# Completed vs Open bar chart | Editor + Report
# ==========================================================

import re
from contextlib import contextmanager
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import streamlit as st
import sqlitecloud

# ==========================================================
# Streamlit config
# ==========================================================
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("📊 Digital Portfolio")

# ==========================================================
# Constants
# ==========================================================
TABLE = "projects"
ALL_LABEL = "All"
NEW_LABEL = "<New Project>"

PRESET_PILLARS = [
    "Digital Mindset",
    "Advanced Analytics",
    "Integration & Visualization",
    "Data Availability & Connectivity",
    "Smart Operations",
    "Vision Lab + Smart Operations",
]

PRESET_STATUSES = ["Idea", "Planned", "In Progress", "Completed"]

PRESET_KPI_LEVERS = [
    "OEE",
    "Labor Productivity",
    "Material Efficiency",
    "Spending / Cost Performance",
    "Multiple KPI Triforce Impact",
    "Other",
]

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "pillar": "TEXT NOT NULL",
    "priority": "INTEGER DEFAULT 5",
    "priority_score": "INTEGER DEFAULT 0",
    "year": "INTEGER",
    "kpi_lever": "TEXT",
    "oee_impact": "INTEGER DEFAULT 0",
    "labor_productivity_impact": "INTEGER DEFAULT 0",
    "material_efficiency_impact": "INTEGER DEFAULT 0",
    "spending_impact": "INTEGER DEFAULT 0",
    "site_controllable": "INTEGER DEFAULT 0",
    "scalable_sustainable": "INTEGER DEFAULT 0",
    "jjos_tier_aligned": "INTEGER DEFAULT 0",
    "description": "TEXT",
    "owner": "TEXT",
    "status": "TEXT",
    "start_date": "TEXT",
    "due_date": "TEXT",
    "plainsware_project": "TEXT DEFAULT 'No'",
    "plainsware_number": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

# ==========================================================
# Helpers
# ==========================================================
def now_ts():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def safe_int(x, default=0):
    try:
        if pd.isna(x):
            return default
        return int(x)
    except Exception:
        return default


def to_iso(d):
    return d.strftime("%Y-%m-%d") if d else ""


def try_date(v):
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except Exception:
        return None


def safe_text(v, default=""):
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except Exception:
        return default
    return str(v)


def get_project_year(loaded):
    loaded_year = safe_int(loaded.get("year"), 0)

    if loaded_year > 0:
        return loaded_year

    due_year = try_date(loaded.get("due_date"))
    if due_year:
        return due_year.year

    start_year = try_date(loaded.get("start_date"))
    if start_year:
        return start_year.year

    return date.today().year


def validate_plainsware(plainsware_project, plainsware_number):
    if str(plainsware_project).strip().lower() == "yes":
        if not plainsware_number:
            raise ValueError("Planisware Project Number is required.")

        value = str(plainsware_number).strip().upper()

        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Must be JJMD-1234567 format.")

        return value

    return None


def calculate_priority_score(
    oee_impact,
    labor_productivity_impact,
    material_efficiency_impact,
    spending_impact,
    site_controllable,
    scalable_sustainable,
    jjos_tier_aligned,
):
    """
    KPI TRIFORCE priority score.

    Higher score means higher strategic priority.

    Criteria:
    - OEE
    - Labor Productivity
    - Material Efficiency
    - Spending / Cost Performance
    - Site controllability
    - Scalability and sustainability
    - JJOS and Tiered Management alignment
    """

    score = (
        safe_int(oee_impact) * 3
        + safe_int(labor_productivity_impact) * 3
        + safe_int(material_efficiency_impact) * 3
        + safe_int(spending_impact) * 2
        + safe_int(site_controllable) * 2
        + safe_int(scalable_sustainable) * 2
        + safe_int(jjos_tier_aligned) * 1
    )

    return score


# ==========================================================
# SQLiteCloud connection
# ==========================================================
def _get_sqlitecloud_url():
    url = (st.secrets.get("SQLITECLOUD_URL_PORTFOLIO") or "").strip()

    if not url:
        st.error("Missing SQLITECLOUD_URL_PORTFOLIO")
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
        st.error("Database connection failed")
        st.exception(e)
        st.stop()

    finally:
        if c:
            c.close()


# ==========================================================
# Schema safety, no data loss
# ==========================================================
def ensure_schema():
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                pillar TEXT
            )
            """
        )

        cols = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)["name"].tolist()

        for col, ddl in EXPECTED_COLUMNS.items():
            if col not in cols:
                if col == "id":
                    continue

                c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")


ensure_schema()


# ==========================================================
# Data loading
# ==========================================================
def fetch_all():
    with conn() as c:
        return pd.read_sql_query(f"SELECT * FROM {TABLE}", c)


def fetch_filtered(filters):
    q = f"SELECT * FROM {TABLE}"
    args = []
    where = []

if filters["status"] != ALL_LABEL:
    where.append("status=?")
    args.append(filters["status"])

if filters["kpi"] != ALL_LABEL:
    where.append("kpi_lever=?")
    args.append(filters["kpi"])

if filters["priority"] != ALL_LABEL:
    where.append("priority=?")
    args.append(int(filters["priority"]))

    if filters["year"] != ALL_LABEL:
        where.append(
            """
            (
                year=?
                OR substr(due_date, 1, 4)=?
                OR substr(start_date, 1, 4)=?
            )
            """
        )

        args.extend(
            [
                int(filters["year"]),
                str(filters["year"]),
                str(filters["year"]),
            ]
        )

    if filters["search"]:
        s = f"%{filters['search'].lower()}%"

        where.append(
            """
            (
                LOWER(name) LIKE ?
                OR LOWER(description) LIKE ?
                OR LOWER(owner) LIKE ?
                OR LOWER(kpi_lever) LIKE ?
            )
            """
        )

        args.extend([s, s, s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)


def enrich_data(df):
    if df.empty:
        return df

    df = df.copy()

    numeric_cols = [
        "priority",
        "priority_score",
        "year",
        "oee_impact",
        "labor_productivity_impact",
        "material_efficiency_impact",
        "spending_impact",
        "site_controllable",
        "scalable_sustainable",
        "jjos_tier_aligned",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["Start"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["End"] = pd.to_datetime(df["due_date"], errors="coerce")

    if "year" in df.columns:
        df["display_year"] = df["year"]
    else:
        df["display_year"] = 0

    df.loc[df["display_year"] == 0, "display_year"] = (
        df["End"].dt.year.fillna(0).astype(int)
    )

    df.loc[df["display_year"] == 0, "display_year"] = (
        df["Start"].dt.year.fillna(0).astype(int)
    )

    df["status_group"] = df["status"].apply(
        lambda x: "Completed"
        if str(x).strip().lower() == "completed"
        else "Open"
    )

    return df


data_all_raw = fetch_all()
data_all_raw = enrich_data(data_all_raw)

available_years = []

if not data_all_raw.empty and "display_year" in data_all_raw.columns:
    available_years = sorted(
        [
            int(y)
            for y in data_all_raw["display_year"].dropna().unique()
            if int(y) > 0
        ],
        reverse=True,
    )

if date.today().year not in available_years:
    available_years.insert(0, date.today().year)


# ==========================================================
# Sidebar Filters
# ==========================================================
st.sidebar.header("Filters")

filters = {
    "pillar": st.sidebar.selectbox("Pillar", [ALL_LABEL] + PRESET_PILLARS),
    "status": st.sidebar.selectbox("Status", [ALL_LABEL] + PRESET_STATUSES),

    "kpi": st.sidebar.selectbox(
        "KPI Lever",
        [ALL_LABEL] + PRESET_KPI_LEVERS
    ),

    "priority": st.sidebar.selectbox(
        "Priority",
        [ALL_LABEL] + [str(i) for i in range(1, 100)],
    ),

    "year": st.sidebar.selectbox(
        "Year",
        [ALL_LABEL] + available_years
    ),

    "search": st.sidebar.text_input("Search"),
}

data_all = data_all_raw
data_filtered = enrich_data(fetch_filtered(filters))


# ==========================================================
# Project Editor
# ==========================================================
st.subheader("✏️ Project Editor")

with conn() as c:
    plist = pd.read_sql_query(
        f"SELECT id, name FROM {TABLE} ORDER BY name",
        c,
    )

opts = [NEW_LABEL] + [
    f"{r.id} - {r.name}" for r in plist.itertuples(index=False)
]

sel = st.selectbox("Select Project", opts)

loaded = {}
pid = None

if sel != NEW_LABEL:
    pid = int(sel.split(" - ")[0])

    with conn() as c:
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE} WHERE id=?",
            c,
            params=[pid],
        )

    if not df.empty:
        loaded = df.iloc[0].to_dict()


c1, c2 = st.columns(2)

with c1:
    name = st.text_input("Name*", safe_text(loaded.get("name")))

    pillar_default = safe_text(loaded.get("pillar"))
    pillar_index = (
        PRESET_PILLARS.index(pillar_default)
        if pillar_default in PRESET_PILLARS
        else 0
    )

    pillar = st.selectbox(
        "Pillar*",
        PRESET_PILLARS,
        index=pillar_index,
    )

    owner = st.text_input("Owner*", safe_text(loaded.get("owner")))

    year_value = st.number_input(
        "Year",
        min_value=2020,
        max_value=2100,
        value=get_project_year(loaded),
        step=1,
    )

    manual_priority = st.number_input(
        "Manual Priority, lower number means higher priority",
        min_value=1,
        max_value=99,
        value=safe_int(loaded.get("priority"), 5),
        step=1,
    )

    desc = st.text_area(
        "Description",
        safe_text(loaded.get("description")),
    )


with c2:
    status_default = safe_text(loaded.get("status"))
    status_options = [""] + PRESET_STATUSES
    status_index = (
        status_options.index(status_default)
        if status_default in status_options
        else 0
    )

    status = st.selectbox(
        "Status",
        status_options,
        index=status_index,
    )

    sd = st.date_input(
        "Start Date",
        try_date(loaded.get("start_date")) or date.today(),
    )

    dd = st.date_input(
        "Due Date",
        try_date(loaded.get("due_date")) or date.today(),
    )

    pw_default = safe_text(loaded.get("plainsware_project"), "No")
    pw_index = ["No", "Yes"].index(pw_default) if pw_default in ["No", "Yes"] else 0

    pw = st.selectbox(
        "Planisware Project?",
        ["No", "Yes"],
        index=pw_index,
    )

    if pw == "Yes":
        pwn = st.text_input(
            "Planisware #",
            safe_text(loaded.get("plainsware_number")),
        )
    else:
        pwn = ""


# ==========================================================
# KPI TRIFORCE Prioritization Criteria
# ==========================================================
st.markdown("### 🔺 KPI TRIFORCE Prioritization Criteria")
st.caption(
    "Score each item from 0 to 5. Higher KPI TRIFORCE score means stronger strategic priority."
)

k1, k2, k3 = st.columns(3)

with k1:
    kpi_default = safe_text(loaded.get("kpi_lever"))
    kpi_index = (
        PRESET_KPI_LEVERS.index(kpi_default)
        if kpi_default in PRESET_KPI_LEVERS
        else 0
    )

    kpi_lever = st.selectbox(
        "Primary KPI Lever",
        PRESET_KPI_LEVERS,
        index=kpi_index,
    )

    oee_impact = st.slider(
        "OEE Impact",
        0,
        5,
        safe_int(loaded.get("oee_impact"), 0),
    )

    labor_productivity_impact = st.slider(
        "Labor Productivity Impact",
        0,
        5,
        safe_int(loaded.get("labor_productivity_impact"), 0),
    )


with k2:
    material_efficiency_impact = st.slider(
        "Material Efficiency Impact",
        0,
        5,
        safe_int(loaded.get("material_efficiency_impact"), 0),
    )

    spending_impact = st.slider(
        "Spending / Cost Performance Impact",
        0,
        5,
        safe_int(loaded.get("spending_impact"), 0),
    )

    site_controllable = st.slider(
        "Site Controllable",
        0,
        5,
        safe_int(loaded.get("site_controllable"), 0),
    )


with k3:
    scalable_sustainable = st.slider(
        "Scalable and Sustainable",
        0,
        5,
        safe_int(loaded.get("scalable_sustainable"), 0),
    )

    jjos_tier_aligned = st.slider(
        "JJOS / Tiered Management Aligned",
        0,
        5,
        safe_int(loaded.get("jjos_tier_aligned"), 0),
    )


priority_score = calculate_priority_score(
    oee_impact,
    labor_productivity_impact,
    material_efficiency_impact,
    spending_impact,
    site_controllable,
    scalable_sustainable,
    jjos_tier_aligned,
)

st.metric("Calculated KPI TRIFORCE Priority Score", priority_score)


# ==========================================================
# Save / Update / Delete buttons
# ==========================================================
b1, b2, b3 = st.columns(3)

if b1.button("Save New"):
    if not name.strip():
        st.error("Name is required.")
        st.stop()

    if not owner.strip():
        st.error("Owner is required.")
        st.stop()

    try:
        pwn_db = validate_plainsware(pw, pwn)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    with conn() as c:
        sql = f"""
        INSERT INTO {TABLE}
        (
            name,
            pillar,
            priority,
            priority_score,
            year,
            kpi_lever,
            oee_impact,
            labor_productivity_impact,
            material_efficiency_impact,
            spending_impact,
            site_controllable,
            scalable_sustainable,
            jjos_tier_aligned,
            description,
            owner,
            status,
            start_date,
            due_date,
            plainsware_project,
            plainsware_number,
            created_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """

        c.execute(
            sql,
            (
                name,
                pillar,
                manual_priority,
                priority_score,
                year_value,
                kpi_lever,
                oee_impact,
                labor_productivity_impact,
                material_efficiency_impact,
                spending_impact,
                site_controllable,
                scalable_sustainable,
                jjos_tier_aligned,
                desc,
                owner,
                status,
                to_iso(sd),
                to_iso(dd),
                pw,
                pwn_db,
                now_ts(),
                now_ts(),
            ),
        )

    st.success("Project created")
    st.rerun()


if pid and b2.button("Update"):
    if not name.strip():
        st.error("Name is required.")
        st.stop()

    if not owner.strip():
        st.error("Owner is required.")
        st.stop()

    try:
        pwn_db = validate_plainsware(pw, pwn)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    with conn() as c:
        sql = f"""
        UPDATE {TABLE}
        SET
            name=?,
            pillar=?,
            priority=?,
            priority_score=?,
            year=?,
            kpi_lever=?,
            oee_impact=?,
            labor_productivity_impact=?,
            material_efficiency_impact=?,
            spending_impact=?,
            site_controllable=?,
            scalable_sustainable=?,
            jjos_tier_aligned=?,
            description=?,
            owner=?,
            status=?,
            start_date=?,
            due_date=?,
            plainsware_project=?,
            plainsware_number=?,
            updated_at=?
        WHERE id=?
        """

        c.execute(
            sql,
            (
                name,
                pillar,
                manual_priority,
                priority_score,
                year_value,
                kpi_lever,
                oee_impact,
                labor_productivity_impact,
                material_efficiency_impact,
                spending_impact,
                site_controllable,
                scalable_sustainable,
                jjos_tier_aligned,
                desc,
                owner,
                status,
                to_iso(sd),
                to_iso(dd),
                pw,
                pwn_db,
                now_ts(),
                pid,
            ),
        )

    st.success("Project updated")
    st.rerun()


if pid and b3.button("Delete"):
    with conn() as c:
        c.execute(
            f"DELETE FROM {TABLE} WHERE id=?",
            (pid,),
        )

    st.warning("Project deleted")
    st.rerun()


# ==========================================================
# KPIs
# ==========================================================
st.subheader("📌 KPIs")

completed_count = 0
open_count = 0
avg_priority_score = 0

if not data_filtered.empty:
    completed_count = int((data_filtered["status_group"] == "Completed").sum())
    open_count = int((data_filtered["status_group"] == "Open").sum())
    avg_priority_score = round(data_filtered["priority_score"].mean(), 1)

kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

kpi_col1.metric("Projects", len(data_filtered))
kpi_col2.metric("Completed", completed_count)
kpi_col3.metric("Open", open_count)
kpi_col4.metric("Avg KPI TRIFORCE Score", avg_priority_score)


# ==========================================================
# Completed vs Open Bar Graph
# ==========================================================
st.subheader("📊 Completed vs Open")

if data_filtered.empty:
    st.info("No projects available for the selected filters.")
else:
    status_summary = (
        data_filtered.groupby("status_group")
        .size()
        .reset_index(name="Project Count")
    )

    status_summary["status_group"] = pd.Categorical(
        status_summary["status_group"],
        categories=["Open", "Completed"],
        ordered=True,
    )

    status_summary = status_summary.sort_values("status_group")

    fig_status = px.bar(
        status_summary,
        x="status_group",
        y="Project Count",
        color="status_group",
        text="Project Count",
        title="Completed vs Open Projects",
        labels={
            "status_group": "Status",
            "Project Count": "Number of Projects",
        },
    )

    fig_status.update_traces(textposition="outside")
    fig_status.update_layout(showlegend=False)

    st.plotly_chart(fig_status, use_container_width=True)


# ==========================================================
# Roadmap
# ==========================================================
st.subheader("🗺️ Roadmap, KPI TRIFORCE Priority Sorted")

rm = data_all.copy()

if not rm.empty:
    rm["Start"] = pd.to_datetime(rm["start_date"], errors="coerce")
    rm["End"] = pd.to_datetime(rm["due_date"], errors="coerce")
    rm = rm.dropna(subset=["Start", "End"])

    rm = rm.sort_values(
        by=[
            "display_year",
            "priority_score",
            "priority",
            "Start",
            "name",
        ],
        ascending=[
            True,
            False,
            True,
            True,
            True,
        ],
    )

if rm.empty:
    st.info("No projects have valid Start and Due dates for roadmap.")
else:
    hover_cols = [
        "display_year",
        "status",
        "owner",
        "kpi_lever",
        "priority_score",
        "priority",
    ]

    hover_cols = [c for c in hover_cols if c in rm.columns]

    fig = px.timeline(
        rm,
        x_start="Start",
        x_end="End",
        y="name",
        color="pillar",
        hover_data=hover_cols,
    )

    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)


# ==========================================================
# Report Section
# ==========================================================
st.subheader("📑 Report")

if data_filtered.empty:
    st.info("No projects match the selected filters.")
else:
    report_df = data_filtered.sort_values(
        by=[
            "display_year",
            "priority_score",
            "priority",
            "pillar",
            "name",
        ],
        ascending=[
            True,
            False,
            True,
            True,
            True,
        ],
    )

    visible_cols = [
        "id",
        "display_year",
        "name",
        "pillar",
        "kpi_lever",
        "priority_score",
        "priority",
        "status",
        "status_group",
        "owner",
        "start_date",
        "due_date",
        "oee_impact",
        "labor_productivity_impact",
        "material_efficiency_impact",
        "spending_impact",
        "site_controllable",
        "scalable_sustainable",
        "jjos_tier_aligned",
        "description",
        "plainsware_project",
        "plainsware_number",
    ]

    visible_cols = [c for c in visible_cols if c in report_df.columns]

    st.dataframe(
        report_df[visible_cols],
        use_container_width=True,
    )

    st.download_button(
        "⬇️ Download Report CSV",
        data=report_df[visible_cols].to_csv(index=False).encode("utf-8"),
        file_name="digital_portfolio_report.csv",
        mime="text/csv",
    )
