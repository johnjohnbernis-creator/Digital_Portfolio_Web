# ----------------------------------------------------------
# Digital Portfolio — Web Version (Portfolio App)
# ✅ Persistent SQLite Cloud version
# - No local DB file (Streamlit Cloud filesystem is ephemeral)  # see Streamlit docs note [1]( /
# - Uses sqlitecloud (sqlite3-compatible DB-API style)          # [2]( /
# - Uses DB-in-path connection string: ...:8860/Portfolio?apikey=...  # [2]( /
# - Adds PRESET_PILLARS merged with DB values (fixes "only one pillar")
# ----------------------------------------------------------

import os
import io
from contextlib import contextmanager
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse, parse_qs, urlunparse
import zipfile
import hashlib
import hmac
import datetime as dt
import re
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
import sqlitecloud
from PIL import Image, ImageDraw, ImageFont

# ------------------ Optional dependencies ------------------
# Optional add-ons (app runs without them)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    REPORTLAB_AVAILABLE = True
    import streamlit_hotkeys as hotkeys  # optional
except Exception:
    REPORTLAB_AVAILABLE = False
    hotkeys = None

try:
    import kaleido  # noqa: F401

    KALEIDO_AVAILABLE = True
    from streamlit_image_zoom import image_zoom  # optional (zoom/pan)
except Exception:
    KALEIDO_AVAILABLE = False

# ------------------ Constants ------------------
TABLE = "projects"

# FIX: HTML entity → real text (prevents Python/UI issues)
# You originally had "&lt;New Project&gt;" which can cause comparisons to fail if any decoding happens.
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"

# FIX: HTML entities → real text (keep your labels readable)
# Keeping your original intent but using real ampersands avoids UI oddities.
PRESET_PILLARS = [
    "Digital Mindset",
    "Advanced Analytics",
    "Integration & Visualization",
    "Data Availability & Connectivity",
    "Smart Operations",
    "Vision Lab + Smart operations",
]
PRESET_STATUSES = [
    "Planned",
    "In Progress",
    "Completed",
    "Idea",
]


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------ Safe URL masking for UI/debug ------------------
def _mask_url(url: str) -> str:
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        if "apikey" in q:
            q["apikey"] = ["****"]
        masked_query = "&".join([f"{k}={v[0]}" for k, v in q.items()])
        return f"{u.scheme}://{u.netloc}{u.path}" + (f"?{masked_query}" if masked_query else "")
    except Exception:
        return "****"


def _normalize_sqlitecloud_netloc(netloc: str) -> str:
    """
    Fix common cluster hostname typo: crgxc3wk.g1.sqlite.cloud -> crgxc3wkg1.sqlite.cloud
    Leaves everything else untouched.
    """
    # Separate host:port if present
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        fixed_host = host
        # Fix pattern: "<something>.g<digits>.sqlite.cloud" -> "<something>g<digits>.sqlite.cloud"
        # Example: crgxc3wk.g1.sqlite.cloud -> crgxc3wkg1.sqlite.cloud
        import re

        fixed_host = re.sub(r"([a-zA-Z0-9]+)\.g(\d+\.sqlite\.cloud)$", r"\1g\2", fixed_host)
        return f"{fixed_host}:{port}"
    else:
        import re

        return re.sub(r"([a-zA-Z0-9]+)\.g(\d+\.sqlite\.cloud)$", r"\1g\2", netloc)


def _swap_port(url: str, new_port: int) -> str:
    u = urlparse(url)
    # Build new netloc with swapped port
    if u.hostname:
        host = u.hostname
        # preserve userinfo if any
        userinfo = ""
        if u.username:
            userinfo = u.username
            if u.password:
                userinfo += f":{u.password}"
            userinfo += "@"
        netloc = f"{userinfo}{host}:{new_port}"
        return urlunparse((u.scheme, netloc, u.path, u.params, u.query, u.fragment))
    return url


def _get_sqlitecloud_url() -> str:
    """
    Digital Portfolio app:
    - Uses ONLY SQLITECLOUD_URL_PORTFOLIO to prevent cross-app mixing.
    """
    url = (st.secrets.get("SQLITECLOUD_URL_PORTFOLIO") or "").strip()

    if not url:
        st.error("Missing Streamlit secret: SQLITECLOUD_URL_PORTFOLIO (Digital Portfolio must not share DB).")
        st.stop()

    if "YOUR_REAL_API_KEY" in url:
        st.error("SQLiteCloud URL contains placeholder YOUR_REAL_API_KEY.")
        st.caption(f"Current: {_mask_url(url)}")
        st.stop()

    return url


def _validate_db_name(db_name: str) -> bool:
    """
    Keep USE DATABASE but prevent injection / invalid names.
    Allow typical SQLiteCloud DB names: letters, digits, underscore, dash, dot.
    """
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", db_name))


# ------------------ JJMD / Planisware validation ------------------
import re

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)


def validate_plainsware(plainsware_project: str, plainsware_number: Any) -> Optional[str]:
    """
    If Plainsware Project = Yes, user must manually enter a Planisware number
    in the format JJMD-0079575 (JJMD- + 7 digits).
    """
    if str(plainsware_project).strip().lower() == "yes":
        if plainsware_number is None or not str(plainsware_number).strip():
            raise ValueError("Planisware Project Number is required when Plainsware Project is Yes.")
        value = str(plainsware_number).strip().upper()
        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Planisware Project Number must be in the format JJMD-0079575 (JJMD- + 7 digits).")
        return value
    return None


# ✅ plainsware_number is TEXT
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
    "plainsware_project": "TEXT DEFAULT 'No'",
    "plainsware_number": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}


# ------------------ Misc Helpers ------------------
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


def safe_int(x: Any, default: int = 5) -> int:
    try:
        return int(x)
    except Exception:
        return default


def status_to_state(x: Any) -> str:
    s = str(x).strip().lower()
    return "Completed" if s in {"done", "complete", "completed"} else "Ongoing"


def _clean(s: Any) -> str:
    return (s or "").strip()


# ------------------ Editor helpers (FIXED placement + COMPLETE) ------------------
# These MUST be top-level functions (not indented inside another function).

def editor_defaults():
    """Defaults for editor widget keys."""
    return {
        "editor_name": "",
        "editor_pillar": PRESET_PILLARS[0] if PRESET_PILLARS else "",
        "editor_priority": 5,
        "editor_desc": "",
        "editor_owner": "",
        "editor_status": "",
        "editor_start": date.today(),
        "editor_due": date.today(),
        "editor_plainsware_project": "No",
        "editor_plainsware_number": "",
    }


def editor_clear_widgets():
    """Clear EVERYTHING in the editor by resetting widget keys."""
    for k, v in editor_defaults().items():
        st.session_state[k] = v


def editor_prime_from_loaded(loaded_project: Optional[dict], pillar_options: List[str], status_list: List[str]):
    """
    Populate editor widget keys from DB row.
    Must be called BEFORE the form widgets are created on the run.
    """
    if not loaded_project:
        editor_clear_widgets()
        return

    st.session_state["editor_name"] = loaded_project.get("name") or ""
    image_zoom = None

    pv = loaded_project.get("pillar") or (pillar_options[0] if pillar_options else "")
    st.session_state["editor_pillar"] = pv if pv in pillar_options else (pillar_options[0] if pillar_options else "")

    st.session_state["editor_priority"] = safe_int(loaded_project.get("priority"), 5)
    st.session_state["editor_desc"] = loaded_project.get("description") or ""
    st.session_state["editor_owner"] = loaded_project.get("owner") or ""

    sv = loaded_project.get("status") or ""
    st.session_state["editor_status"] = sv if (sv == "" or sv in status_list) else ""

    st.session_state["editor_start"] = try_date(loaded_project.get("start_date")) or date.today()
    st.session_state["editor_due"] = try_date(loaded_project.get("due_date")) or date.today()

    pw = loaded_project.get("plainsware_project", "No") or "No"
    st.session_state["editor_plainsware_project"] = "Yes" if str(pw).strip().lower() == "yes" else "No"
# ROI rectangle selection (for snapshot)
try:
    from streamlit_drawable_canvas import st_canvas  # optional
except Exception:
    st_canvas = None

    st.session_state["editor_plainsware_number"] = (loaded_project.get("plainsware_number") or "").strip()
# -----------------------
# CONFIG
# -----------------------
st.set_page_config(page_title="Holistic FoilVision", layout="wide")

# ✅ Databricks-safe: allow IMAGE_ROOT override (for /Volumes/...) while keeping your Windows default.
# If IMAGE_ROOT is not set, it falls back to your current working folder.
DEFAULT_ROOT_FOLDER = r"C:\Holistic_Foil"
ROOT_FOLDER = os.environ.get("IMAGE_ROOT", "").strip() or DEFAULT_ROOT_FOLDER  # MUST contain subfolders with images

# ------------------ SQLite Cloud Connection (context manager) ------------------
@contextmanager
def conn():
    """
    Open/close a SQLite Cloud connection.
    FIX: Hard-pin the DB file using USE DATABASE to avoid any mixing.
    SQLiteCloud supports selecting DB via USE DATABASE after connecting.
    """
    url = _get_sqlitecloud_url()
SUPPORTED_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

    # --- Connection attempts (no deletions; just safer behavior) ---
    last_exc = None
    candidates = []
BASE_DIR = os.path.dirname(__file__)

    candidates.append(url)
# ✅ Databricks-safe: allow OUTPUT_DIR override (for /Volumes/.../outputs) while keeping local default.
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "").strip() or os.path.join(BASE_DIR, "output")
SNAPSHOT_DIR = os.path.join(OUTPUT_DIR, "snapshots")

    # normalize hostname typos
    try:
        u = urlparse(url)
        normalized_netloc = _normalize_sqlitecloud_netloc(u.netloc)
        if normalized_netloc != u.netloc:
            candidates.append(urlunparse((u.scheme, normalized_netloc, u.path, u.params, u.query, u.fragment)))
    except Exception:
        pass
# Prefer enhanced config if present
DEFECTS_CONFIG_PATH = os.path.join(BASE_DIR, "defects_config_enhanced.csv")
if not os.path.isfile(DEFECTS_CONFIG_PATH):
    DEFECTS_CONFIG_PATH = os.path.join(BASE_DIR, "defects_config.csv")

    # port fallback 8860 -> 8861
    try:
        u = urlparse(url)
        if u.port == 8860:
            candidates.append(_swap_port(url, 8861))
            # also combine with normalized host + port swap
            try:
                u2 = urlparse(candidates[-1])
                normalized_netloc2 = _normalize_sqlitecloud_netloc(u2.netloc)
                if normalized_netloc2 != u2.netloc:
                    candidates.append(urlunparse((u2.scheme, normalized_netloc2, u2.path, u2.params, u2.query, u2.fragment)))
            except Exception:
                pass
    except Exception:
        pass
OPERATORS_CONFIG_PATH = os.path.join(BASE_DIR, "operators.yaml")

    c = None
    for candidate in candidates:
        try:
            c = sqlitecloud.connect(candidate)
            url = candidate  # remember the one that worked for masking/debug
            break
        except Exception as e:
            last_exc = e
            c = None

    if c is None:
        st.error("🚨 Database unavailable (connection attempts failed).")
        st.caption(f"Connection tried: {_mask_url(candidates[0])}")
        if len(candidates) > 1:
            st.caption(f"Fallback tried: {_mask_url(candidates[-1])}")
        st.exception(last_exc)
# -----------------------
# Compatibility helpers
# -----------------------
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.stop()

    # FIX: Optional but recommended: select DB file after connecting
    db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()
    try:
        if db_name:
            if not _validate_db_name(db_name):
                st.error("Invalid SQLITECLOUD_DB_PORTFOLIO. Only letters/digits/._- allowed.")
                st.caption(f"Value: {db_name!r}")
                st.stop()
            c.execute(f'USE DATABASE "{db_name}"')
        yield c
    finally:
def notify_success(msg: str):
    if hasattr(st, "toast"):
        try:
            c.close()
            st.toast(msg)
            return
        except Exception:
            pass
    st.success(msg)


def assert_db_awake():
    """Fail fast with the real exception (masked URL shown). FIX: uses same URL as conn()."""
    url = _get_sqlitecloud_url()
def safe_altair(chart):
    try:
        with conn() as c:
            c.execute("SELECT 1")
    except Exception as e:
        st.error("🚨 Database unavailable.")
        st.caption(f"Connection: {_mask_url(url)}")
        st.exception(e)
        st.stop()


# ------------------ Schema / Migration Helpers ------------------
def _table_info_df(c) -> pd.DataFrame:
    return pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)


def _needs_rebuild_due_to_created_at(info: pd.DataFrame) -> bool:
    if info.empty:
        return False
    row = info[info["name"] == "created_at"]
    if row.empty:
        return False
    notnull = int(row.iloc[0]["notnull"]) == 1
    dflt = row.iloc[0]["dflt_value"]
    no_default = pd.isna(dflt) or str(dflt).strip() == ""
    return bool(notnull and no_default)


def _needs_rebuild_due_to_plainsware_number_type(info: pd.DataFrame) -> bool:
    if info.empty:
        return False
    row = info[info["name"] == "plainsware_number"]
    if row.empty:
        return False
    col_type = str(row.iloc[0]["type"] or "").strip().upper()
    return col_type != "TEXT"


def _rebuild_projects_table(c) -> None:
    old_info = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
    old_cols = old_info["name"].tolist()

    legacy_map = {
        "plainsware_proj": "plainsware_project",
        "plainsware_num": "plainsware_number",
        st.altair_chart(chart, use_container_width=True)
    except TypeError:
        st.altair_chart(chart)

# -----------------------
# Helpers
# -----------------------
def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def now_utc_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def safe_list_subfolders(root_folder: str):
    if not os.path.isdir(root_folder):
        return []
    return sorted([f for f in os.listdir(root_folder) if os.path.isdir(os.path.join(root_folder, f))])

def list_images_recursive(folder_path: str):
    rels = []
    if not os.path.isdir(folder_path):
        return rels
    for root, _, files in os.walk(folder_path):
        for fn in files:
            if fn.lower().endswith(SUPPORTED_EXT):
                full = os.path.join(root, fn)
                rels.append(os.path.relpath(full, folder_path))
    rels.sort()
    return rels

def summarize_extensions(folder_path: str):
    exts = []
    total = 0
    for root, _, files in os.walk(folder_path):
        for fn in files:
            total += 1
            ext = os.path.splitext(fn)[1].lower() or "(no ext)"
            exts.append(ext)
    return total, Counter(exts)

def load_defects_config(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame([{
            "defect": "Other",
            "category": "Other",
            "defect_family": "Other",
            "description": "",
            "classification_options": "Critical\nClass I\nClass II\nClass III",
            "active": 1,
            "test_dependent": "No",
            "vision_eligible": "Yes",
            "color_hex": "",
        }])

    df = pd.read_csv(path)
    defaults = {
        "defect": "",
        "category": "Other",
        "defect_family": "Other",
        "description": "",
        "classification_options": "Critical\nClass I\nClass II\nClass III",
        "active": 1,
        "test_dependent": "No",
        "vision_eligible": "Yes",
        "color_hex": "",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    keep_old, keep_new = [], []
    for col in old_cols:
        if col == "id":
            continue
        if col in EXPECTED_COLUMNS:
            keep_old.append(col)
            keep_new.append(col)
        elif col in legacy_map and legacy_map[col] in EXPECTED_COLUMNS:
            keep_old.append(col)
            keep_new.append(legacy_map[col])

    c.execute("BEGIN")
    c.execute(
        f"""
        CREATE TABLE {TABLE}__new (
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
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    if keep_old:
        c.execute(
            f"""
            INSERT INTO {TABLE}__new ({", ".join(keep_new)})
            SELECT {", ".join(keep_old)} FROM {TABLE}
            """
        )

    c.execute(
        f"""
        UPDATE {TABLE}__new
        SET created_at = COALESCE(NULLIF(created_at,''), CURRENT_TIMESTAMP),
            updated_at = COALESCE(NULLIF(updated_at,''), CURRENT_TIMESTAMP)
        """
    )

    c.execute(f"DROP TABLE {TABLE}")
    c.execute(f"ALTER TABLE {TABLE}__new RENAME TO {TABLE}")
    c.execute("COMMIT")
    df["active"] = pd.to_numeric(df["active"], errors="coerce").fillna(1).astype(int)
    for c in ["defect", "category", "defect_family", "description", "classification_options",
              "test_dependent", "vision_eligible", "color_hex"]:
        df[c] = df[c].astype(str).str.strip()

    df = df[(df["active"] == 1) & (df["defect"] != "")].copy()
    return df

def ensure_schema_and_migrate() -> None:
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
def load_operator_config(path: str):
    if not os.path.isfile(path):
        return None
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def verify_login(op_cfg: dict, username: str, password: str) -> bool:
    salt = str(op_cfg.get("salt", ""))
    users = op_cfg.get("users", {}) or {}
    user = users.get(username, {})
    expected = str(user.get("password_sha256", ""))
    candidate = sha256_hex(salt + password)
    return hmac.compare_digest(candidate, expected)

def load_existing_csv(path: str) -> pd.DataFrame:
    if os.path.isfile(path):
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def write_csv(path: str, df: pd.DataFrame):
    df.to_csv(path, index=False)

def dedupe_master(master_df: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty:
        return master_df
    for c in ["Folder", "Image", "Operator"]:
        if c not in master_df.columns:
            master_df[c] = ""
    return master_df.drop_duplicates(subset=["Folder", "Image", "Operator"], keep="last").reset_index(drop=True)

# -------------------------------
# ✅ ADDITIVE: Robust classification parser
# Handles separators: newline, |, │, ¦, ; and regex fallback
# -------------------------------
def parse_classification_options(raw_value):
    s = "" if raw_value is None else str(raw_value)
    s = s.strip()
    if (not s) or (s.lower() in ("nan", "none")):
        return ["Critical", "Class I", "Class II", "Class III"]

    for sep in ["\\r\\n", "\\r", "\n", "|", "│", "¦", ";"]:
        s = s.replace(sep, "\n")

    parts = [p.strip() for p in s.split("\n") if p.strip()]

    if len(parts) <= 1:
        tokens = re.findall(r"(?i)critical|class\s*i{1,3}\b", s)
        if tokens:
            norm = []
            for t in tokens:
                tl = t.lower().strip()
                if tl == "critical":
                    norm.append("Critical")
                elif tl.startswith("class"):
                    roman = re.sub(r"(?i)^class\s*", "", t).strip().upper()
                    norm.append(f"Class {roman}")
            seen = set()
            out = []
            for x in norm:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            if out:
                parts = out

    if not parts:
        parts = ["Critical", "Class I", "Class II", "Class III"]

    crit = [x for x in parts if x.strip().lower() == "critical"]
    rest = [x for x in parts if x.strip().lower() != "critical"]
    return crit + rest

def build_pareto(df_bad: pd.DataFrame, label_col: str):
    counts = df_bad.groupby(label_col).size().reset_index(name="Count").sort_values("Count", ascending=False)
    counts["Cumulative %"] = counts["Count"].cumsum() / max(1, counts["Count"].sum()) * 100
    return counts

def pareto_chart(pareto_counts: pd.DataFrame, label_col: str, title: str):
    try:
        import altair as alt
        bar = alt.Chart(pareto_counts).mark_bar().encode(
            x=alt.X(f"{label_col}:N", sort='-y', title=label_col),
            y=alt.Y("Count:Q", title="Occurrences"),
            tooltip=[label_col, "Count"]
        )

        info = _table_info_df(c)
        existing_set = set(info["name"].tolist())

        if "plainsware_proj" in existing_set and "plainsware_project" not in existing_set:
            try:
                c.execute(f'ALTER TABLE {TABLE} RENAME COLUMN "plainsware_proj" TO "plainsware_project"')
            except Exception:
                _rebuild_projects_table(c)

        if "plainsware_num" in existing_set and "plainsware_number" not in existing_set:
            try:
                c.execute(f'ALTER TABLE {TABLE} RENAME COLUMN "plainsware_num" TO "plainsware_number"')
            except Exception:
                _rebuild_projects_table(c)

        info = _table_info_df(c)

        if _needs_rebuild_due_to_created_at(info):
            _rebuild_projects_table(c)
            info = _table_info_df(c)

        if _needs_rebuild_due_to_plainsware_number_type(info):
            _rebuild_projects_table(c)
            info = _table_info_df(c)

        existing_set = set(info["name"].tolist())

        for col, ddl in EXPECTED_COLUMNS.items():
            if col not in existing_set and col not in ("id", "name", "pillar"):
                try:
                    c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
                except Exception:
                    _rebuild_projects_table(c)
                    break


# FIX: Cache must vary by DB to prevent mixed dropdown values
_DB_KEY = ""


@st.cache_data(show_spinner=False)
def distinct_values(col: str, _db_key: str = "") -> List[str]:
    with conn() as c:
        df = pd.read_sql_query(
            f"""
            SELECT DISTINCT {col}
            FROM {TABLE}
            WHERE {col} IS NOT NULL AND TRIM({col}) <> ''
            ORDER BY {col}
            """,
            c,
        line = alt.Chart(pareto_counts).mark_line(color="red").encode(
            x=alt.X(f"{label_col}:N", sort=pareto_counts[label_col].tolist()),
            y=alt.Y("Cumulative %:Q", axis=alt.Axis(title="Cumulative %")),
            tooltip=["Cumulative %"]
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

        if filters.get("plainsware") and filters["plainsware"] != ALL_LABEL:
            where.append("plainsware_project = ?")
            args.append(filters["plainsware"])

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

    q += " ORDER BY COALESCE(start_date,''), COALESCE(due_date,''), COALESCE(created_at,'')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)

        return (bar + line).properties(title=title)
    except Exception:
        return None

def fetch_all_projects() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f"SELECT * FROM {TABLE} ORDER BY id", c)
# -----------------------
# Defect color mapping
# -----------------------
DEFAULT_PALETTE = [
    "#E41A1C", "#377EB8", "#4DAF4A", "#984EA3", "#FF7F00",
    "#A65628", "#F781BF", "#999999", "#66C2A5", "#FC8D62",
    "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494"
]

def deterministic_color(name: str) -> str:
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return DEFAULT_PALETTE[h % len(DEFAULT_PALETTE)]

def clear_cache() -> None:
def build_defect_color_map(defects_df: pd.DataFrame) -> dict:
    m = {}
    for _, r in defects_df.iterrows():
        d = str(r.get("defect", "")).strip()
        if not d:
            continue
        cfg_color = str(r.get("color_hex", "")).strip()
        if cfg_color and cfg_color.startswith("#") and len(cfg_color) in (4, 7):
            m[d] = cfg_color
        else:
            m[d] = deterministic_color(d)
    return m

# -----------------------
# Snapshot creation
# -----------------------
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def create_snapshot(img: Image.Image, crop_box_xyxy, color_hex: str, label: str) -> Image.Image:
    x1, y1, x2, y2 = crop_box_xyxy
    w, h = img.size
    x1 = clamp(int(round(x1)), 0, w - 1)
    y1 = clamp(int(round(y1)), 0, h - 1)
    x2 = clamp(int(round(x2)), 1, w)
    y2 = clamp(int(round(y2)), 1, h)
    if x2 <= x1 + 1 or y2 <= y1 + 1:
        pad = 40
        x1 = clamp(x1 - pad, 0, w - 1)
        y1 = clamp(y1 - pad, 0, h - 1)
        x2 = clamp(x2 + pad, 1, w)
        y2 = clamp(y2 + pad, 1, h)

    roi = img.crop((x1, y1, x2, y2)).convert("RGB")
    border = max(6, int(min(roi.size) * 0.02))
    out = Image.new("RGB", (roi.size[0] + border * 2, roi.size[1] + border * 2), color_hex)
    out.paste(roi, (border, border))

    bar_h = max(28, int(out.size[1] * 0.08))
    labeled = Image.new("RGB", (out.size[0], out.size[1] + bar_h), "#111111")
    labeled.paste(out, (0, bar_h))
    draw = ImageDraw.Draw(labeled)
    try:
        st.cache_data.clear()
        font = ImageFont.load_default()
    except Exception:
        pass


# ------------------ PDF Export ------------------
def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    if not REPORTLAB_AVAILABLE:
        return b""
    buffer = io.BytesIO()
    cpdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter  # noqa: F841

    cpdf.setFont("Helvetica-Bold", 14)
    cpdf.drawString(40, height - 40, title)

    cpdf.setFont("Helvetica", 9)
    y = height - 70

    cols = ["id", "name", "pillar", "priority", "owner", "status",
            "start_date", "due_date", "plainsware_project", "plainsware_number"]
    cpdf.drawString(40, y, " | ".join(cols))
    y -= 14

    for _, row in df.iterrows():
        line = " | ".join([str(row.get(col, ""))[:40] for col in cols])
        cpdf.drawString(40, y, line)
        y -= 12
        if y < 50:
            cpdf.showPage()
            cpdf.setFont("Helvetica", 9)
            y = height - 50

    cpdf.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


# ------------------ App Boot ------------------
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# Now safe to compute DB key (no Streamlit calls before set_page_config)
_DB_KEY = _mask_url(_get_sqlitecloud_url())

# ✅ APP1 safety lock (must be BEFORE any DB call)
db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()

if not db_name:
    st.error("❌ Missing secret: SQLITECLOUD_DB_PORTFOLIO")
        font = None
    draw.text((10, 6), label, fill=color_hex, font=font)
    return labeled

def save_snapshot_file(snapshot_img: Image.Image, rel_path_under_output: str) -> str:
    full_path = os.path.join(OUTPUT_DIR, rel_path_under_output)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    snapshot_img.save(full_path, format="PNG")
    return rel_path_under_output

def export_zip_from_master(master_df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("MASTER__image_review_results.csv", master_df.to_csv(index=False))
        if "SnapshotPath" in master_df.columns:
            snap_paths = (
                master_df["SnapshotPath"]
                .dropna()
                .astype(str)
                .str.strip()
                .loc[lambda s: s != ""]
                .unique()
                .tolist()
            )
            for relp in snap_paths:
                fullp = os.path.join(OUTPUT_DIR, relp)
                if os.path.isfile(fullp):
                    z.write(fullp, arcname=os.path.join("snapshots", os.path.basename(relp)))
        z.writestr(
            "README.txt",
            "This ZIP contains:\n"
            " - MASTER__image_review_results.csv\n"
            " - snapshots/ (PNG files for BAD decisions where ROI was selected)\n\n"
            "SnapshotPath column in the CSV corresponds to the PNG file name in snapshots/.\n"
        )
    return bio.getvalue()

# -----------------------
# SESSION STATE INIT
# -----------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "operator" not in st.session_state:
    st.session_state.operator = None
if "current_folder" not in st.session_state:
    st.session_state.current_folder = None
if "image_index" not in st.session_state:
    st.session_state.image_index = 0
if "results" not in st.session_state:
    st.session_state.results = []
if "resume_loaded" not in st.session_state:
    st.session_state.resume_loaded = False

# -----------------------
# UI
# -----------------------
st.title("Holistic FoilVision")
ensure_dirs()

# -----------------------
# LOGIN
# -----------------------
st.sidebar.header("🔐 Operator Login")
op_cfg = load_operator_config(OPERATORS_CONFIG_PATH)

if st.session_state.logged_in and st.session_state.operator:
    st.sidebar.success(f"Logged in as: {st.session_state.operator}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.operator = None
        st.session_state.current_folder = None
        st.session_state.image_index = 0
        st.session_state.results = []
        st.session_state.resume_loaded = False
        safe_rerun()
else:
    if op_cfg is None:
        operator_name = st.sidebar.text_input("Operator name", value="")
        if st.sidebar.button("Enter") and operator_name.strip():
            st.session_state.logged_in = True
            st.session_state.operator = operator_name.strip()
            safe_rerun()
    else:
        users = sorted(list((op_cfg.get("users") or {}).keys()))
        username = st.sidebar.selectbox("Username", users) if users else st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Login"):
            if verify_login(op_cfg, username, password):
                disp = (op_cfg.get("users") or {}).get(username, {}).get("name") or username
                st.session_state.logged_in = True
                st.session_state.operator = disp
                safe_rerun()
            else:
                st.sidebar.error("Invalid username/password")

if not st.session_state.logged_in:
    st.stop()

EXPECTED_DB_PATH = f"/{db_name}"
actual_path = urlparse(_get_sqlitecloud_url()).path or ""

if actual_path != EXPECTED_DB_PATH:
    st.error(
        f"❌ APP1 wrong DB configured. Expected {EXPECTED_DB_PATH}, got {actual_path}"
    )
# -----------------------
# DEFECT CONFIG + FILTERS + LEGEND
# -----------------------
defects_df = load_defects_config(DEFECTS_CONFIG_PATH)
defect_color_map = build_defect_color_map(defects_df)

st.sidebar.markdown("---")
st.sidebar.subheader("Defect dropdown")
st.sidebar.caption(f"Using: {os.path.basename(DEFECTS_CONFIG_PATH)}")

vision_only = st.sidebar.checkbox("Vision-Eligible only", value=False)
filtered_defects = defects_df.copy()
if vision_only:
    filtered_defects = filtered_defects[filtered_defects["vision_eligible"].str.lower() == "yes"].copy()

categories = sorted(filtered_defects["category"].dropna().unique().tolist())

with st.sidebar.expander("📘 Defect Legend", expanded=False):
    legend_cols = ["category", "defect_family", "defect", "vision_eligible", "test_dependent"]
    legend = defects_df[legend_cols].copy().sort_values(["category", "defect_family", "defect"])
    legend["color_hex"] = legend["defect"].map(defect_color_map).fillna("#999999")
    st.dataframe(legend)

# Zoom controls (only used when BAD)
zoom_behavior = st.sidebar.selectbox("Zoom behavior (only when BAD)", ["Click-to-zoom", "Magnifier lens", "Scroll wheel", "Both"], index=0)
zoom_factor = st.sidebar.slider("Zoom factor", min_value=2.0, max_value=8.0, value=3.0, step=0.5)
zoom_increment = st.sidebar.slider("Scroll increment", min_value=0.1, max_value=0.9, value=0.3, step=0.1)
behavior_to_mode = {"Click-to-zoom": "dragmove", "Magnifier lens": "mousemove", "Scroll wheel": "scroll", "Both": "both"}
zoom_mode = behavior_to_mode.get(zoom_behavior, "dragmove")

# -----------------------
# FOLDER SELECTION
# -----------------------
folders = safe_list_subfolders(ROOT_FOLDER)
if not folders:
    st.error(f"No subfolders found under ROOT_FOLDER: {ROOT_FOLDER}")
    st.stop()

# ✅ TEMP banner for verification (REMOVE after confirming once)
st.caption("APP1 DB URL → " + _mask_url(_get_sqlitecloud_url()))

assert_db_awake()
ensure_schema_and_migrate()
assert_db_awake()
ensure_schema_and_migrate()

# ------------------ Session State ------------------
if "project_selector" not in st.session_state:
    st.session_state.project_selector = NEW_LABEL
if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False

# NEW: track last loaded project id to know when to repopulate editor
if "last_loaded_project_id" not in st.session_state:
    st.session_state.last_loaded_project_id = None
selected_folder = st.selectbox("Select a folder with images", folders)
folder_path = os.path.join(ROOT_FOLDER, selected_folder)
images = list_images_recursive(folder_path)

if not images:
    total_files, ext_counts = summarize_extensions(folder_path)
    st.warning("No images found in this folder.")
    st.write(f"Folder path: {folder_path}")
    st.write(f"Total files found (all types): {total_files}")
    st.write("File extensions found:")
    st.json({k: int(v) for k, v in ext_counts.most_common(20)})
    st.info(f"Supported extensions: {', '.join(SUPPORTED_EXT)}")
    st.stop()

# NEW: filter reset flag (fix Clear Filters)
if "reset_filters" not in st.session_state:
    st.session_state.reset_filters = False
operator_safe = "".join([c for c in st.session_state.operator if c.isalnum() or c in (" ", "_", "-")]).strip().replace(" ", "_")
session_results_path = os.path.join(OUTPUT_DIR, f"{selected_folder}__{operator_safe}__results.csv")
master_results_path = os.path.join(OUTPUT_DIR, "MASTER__image_review_results.csv")

if st.session_state.current_folder != selected_folder:
    st.session_state.current_folder = selected_folder
    st.session_state.image_index = 0
    st.session_state.results = []
    st.session_state.resume_loaded = False

if not st.session_state.resume_loaded:
    existing = load_existing_csv(session_results_path)
    if not existing.empty:
        with st.expander("🔄 Resume saved progress?", expanded=False):
            st.write(f"Found {len(existing)} saved reviews for this folder/operator.")
            if st.button("Resume"):
                st.session_state.results = existing.to_dict("records")
                reviewed = set(existing["Image"].astype(str).tolist()) if "Image" in existing.columns else set()
                idx = 0
                for j, imgname in enumerate(images):
                    if imgname not in reviewed:
                        idx = j
                        break
                else:
                    idx = min(len(images) - 1, len(images) - 1)
                st.session_state.image_index = idx
                st.session_state.resume_loaded = True
                safe_rerun()

            if st.button("Start fresh"):
                st.session_state.resume_loaded = True
                safe_rerun()
    else:
        st.session_state.resume_loaded = True

# -----------------------
# Keys
# -----------------------
def decision_key(i): return f"decision_{selected_folder}_{operator_safe}_{i}"
def category_key(i): return f"defcat_{selected_folder}_{operator_safe}_{i}"
def family_key(i): return f"deffam_{selected_folder}_{operator_safe}_{i}"
def defect_key(i): return f"defect_{selected_folder}_{operator_safe}_{i}"
def class_key(i): return f"class_{selected_folder}_{operator_safe}_{i}"
def comment_key(i): return f"comment_{selected_folder}_{operator_safe}_{i}"
def roi_key(i): return f"roi_{selected_folder}_{operator_safe}_{i}"
def crit_confirm_key(i): return f"crit_confirm_{selected_folder}_{operator_safe}_{i}"

def go_prev():
    st.session_state.image_index = max(0, st.session_state.image_index - 1)

def go_next():
    st.session_state.image_index = min(len(images) - 1, st.session_state.image_index + 1)

# -----------------------
# Save logic
# -----------------------
def save_current():
    i = st.session_state.image_index
    img_rel = images[i]
    decision = st.session_state.get(decision_key(i), "Good")
    defect = st.session_state.get(defect_key(i), "")
    classification = st.session_state.get(class_key(i), "")
    comment = st.session_state.get(comment_key(i), "")
    roi_xyxy = ""
    snapshot_rel_path = ""

    if decision == "Bad":
        if not str(defect).strip():
            st.warning("Select a Defect before saving a Bad decision.")
            return False
        if not str(classification).strip():
            st.warning("Select a Classification before saving a Bad decision.")
            return False
        if str(classification).strip().lower() == "critical":
            if not bool(st.session_state.get(crit_confirm_key(i), False)):
                st.warning("Critical classification requires confirmation before saving.")
                return False

        roi = st.session_state.get(roi_key(i), None)
        if not roi or not isinstance(roi, (tuple, list)) or len(roi) != 4:
            st.warning("Draw/select the defect area (ROI) to create the snapshot before saving.")
            return False

        roi_xyxy = ",".join([str(int(round(x))) for x in roi])
        img_path = os.path.join(folder_path, img_rel)
        img = Image.open(img_path)
        color_hex = defect_color_map.get(str(defect).strip(), "#FF00FF")
        label = f"{defect} \n {classification}"
        snap = create_snapshot(img, roi, color_hex, label)
        review_id = sha256_hex(f"{selected_folder}\n{img_rel}\n{st.session_state.operator}")
        snap_name = f"{selected_folder}__{operator_safe}__{review_id[:12]}__{os.path.basename(img_rel)}.png"
        relp = os.path.join("snapshots", snap_name)
        snapshot_rel_path = save_snapshot_file(snap, relp)
    else:
        defect = ""
        classification = ""
        roi_xyxy = ""
        snapshot_rel_path = ""
        st.session_state[crit_confirm_key(i)] = False

    record = {
        "review_id": sha256_hex(f"{selected_folder}\n{img_rel}\n{st.session_state.operator}"),
        "ReviewedAtUTC": now_utc_iso(),
        "Operator": st.session_state.operator,
        "Folder": selected_folder,
        "Image": img_rel,
        "Decision": decision,
        "Defect": defect,
        "Classification": classification,
        "Comment": comment,
        "ROI_xyxy": roi_xyxy,
        "SnapshotPath": snapshot_rel_path,
    }

if st.session_state.reset_project_selector:
    st.session_state.project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False
    st.session_state.last_loaded_project_id = None
    # also clear editor widgets
    editor_clear_widgets()
    updated = False
    for k, r in enumerate(st.session_state.results):
        if r.get("Folder") == selected_folder and r.get("Image") == img_rel and r.get("Operator") == st.session_state.operator:
            st.session_state.results[k] = record
            updated = True
            break
    if not updated:
        st.session_state.results.append(record)

    df_session = pd.DataFrame(st.session_state.results)
    write_csv(session_results_path, df_session)

    df_master = load_existing_csv(master_results_path)
    df_master = pd.concat([df_master, df_session], ignore_index=True)
    df_master = dedupe_master(df_master)
    write_csv(master_results_path, df_master)

    notify_success("Saved ✅")
    return True

def save_and_next():
    ok = save_current()
    if ok:
        go_next()

# -----------------------
# MAIN DISPLAY
# -----------------------
i = st.session_state.image_index
img_rel = images[i]
img_path = os.path.join(folder_path, img_rel)

if decision_key(i) not in st.session_state:
    st.session_state[decision_key(i)] = "Good"

current_decision = st.session_state.get(decision_key(i), "Good")

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader(f"Image {i+1} of {len(images)} — {os.path.basename(img_rel)}")
    img = Image.open(img_path)

    if current_decision == "Bad" and image_zoom is not None:
        image_zoom(
            img,
            mode=zoom_mode,
            size=(900, 650),
            keep_aspect_ratio=True,
            keep_resolution=True,
            zoom_factor=float(zoom_factor),
            increment=float(zoom_increment),
        )
        st.caption("Tip: Use zoom for inspection, then draw ROI (rectangle) below to save snapshot.")
    else:
        st.image(img, width=900)

# ------------------ Project Editor ------------------
st.markdown("---")
st.subheader("Project Editor")
    st.markdown("### 🎯 Defect Area (ROI) + Snapshot")
    if current_decision != "Bad":
        st.info("ROI + Snapshot is only required when Decision = Bad.")
    else:
        if st_canvas is None:
            st.warning("ROI selector not available. Install: pip install streamlit-drawable-canvas")
        else:
            chosen_def = st.session_state.get(defect_key(i), "")
            color_hex = defect_color_map.get(str(chosen_def).strip(), "#00FF00") if chosen_def else "#00FF00"

            target_w, target_h = 900, 650
            img_w, img_h = img.size
            scale = min(target_w / img_w, target_h / img_h)
            disp_w = int(img_w * scale)
            disp_h = int(img_h * scale)
            disp_img = img.resize((disp_w, disp_h))

            st.write("Draw a rectangle around the defect area (used to create the snapshot in the report).")
            canvas_result = st_canvas(
                fill_color="rgba(0, 0, 0, 0)",
                stroke_width=3,
                stroke_color=color_hex,
                background_image=disp_img,
                update_streamlit=True,
                height=disp_h,
                width=disp_w,
                drawing_mode="rect",
                display_toolbar=True,
                key=f"canvas_{selected_folder}_{operator_safe}_{i}",
            )

with conn() as c:
    df_projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)
            roi_xyxy = None
            if canvas_result is not None and canvas_result.json_data is not None:
                objs = canvas_result.json_data.get("objects", [])
                if objs:
                    r = objs[-1]
                    left_px = float(r.get("left", 0))
                    top_px = float(r.get("top", 0))
                    w_px = float(r.get("width", 0)) * float(r.get("scaleX", 1))
                    h_px = float(r.get("height", 0)) * float(r.get("scaleY", 1))

                    x1 = left_px / scale
                    y1 = top_px / scale
                    x2 = (left_px + w_px) / scale
                    y2 = (top_px + h_px) / scale
                    roi_xyxy = (x1, y1, x2, y2)

                    if roi_xyxy:
                        st.session_state[roi_key(i)] = roi_xyxy
                        chosen_def = st.session_state.get(defect_key(i), "")
                        chosen_class = st.session_state.get(class_key(i), "")
                        label = f"{chosen_def} \n {chosen_class}".strip(" \n")
                        preview = create_snapshot(img, roi_xyxy, color_hex, label if label else "Snapshot")
                        preview_w = min(900, preview.size[0]) if hasattr(preview, "size") else 900
                        st.image(preview, caption=f"Snapshot Preview (border = {color_hex})", width=preview_w)
                else:
                    st.caption("No ROI selected yet. Draw a rectangle to enable snapshot saving.")

with right:
    st.subheader("Inspection Decision")
    st.radio(
        "Decision",
        ["Good", "Bad"],
        index=0 if st.session_state[decision_key(i)] == "Good" else 1,
        key=decision_key(i),
    )

project_options = [NEW_LABEL] + [f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()]
    if st.session_state[decision_key(i)] == "Bad":
        if categories:
            if category_key(i) not in st.session_state:
                st.session_state[category_key(i)] = categories[0]
            chosen_cat = st.selectbox("Category", categories, key=category_key(i))
        else:
            chosen_cat = "Other"

selected_project = st.selectbox(
    "Select Project to Edit",
    project_options,
    index=safe_index(project_options, st.session_state.project_selector),
    key="project_selector",
)
        df_cat = filtered_defects[filtered_defects["category"] == chosen_cat].copy()
        families = sorted(df_cat["defect_family"].dropna().unique().tolist())

loaded_project = None
current_project_id = None
if selected_project != NEW_LABEL:
    try:
        current_project_id = int(selected_project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[current_project_id])
        loaded_project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_project = None
        current_project_id = None

# ✅ Digital Portfolio: Pillars are FIXED and NOT read from DB
pillar_from_db = []  # defined intentionally empty to prevent DB pillar bleed-through
pillar_options = PRESET_PILLARS.copy()
pillar_options = sorted(set(PRESET_PILLARS) | set(pillar_from_db))

# FIX: pass _DB_KEY to cached distinct_values
status_from_db = distinct_values("status", _DB_KEY)
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))
owner_list = distinct_values("owner", _DB_KEY)

bcol1, bcol2 = st.columns([1, 1])
new_clicked = bcol1.button("New", key="btn_new_project")
clear_clicked = bcol2.button("Clear Filters", key="btn_clear_filters")

if new_clicked:
    st.session_state.reset_project_selector = True
    editor_clear_widgets()
    st.rerun()

# FIX: Clear Filters reliably resets filter widgets via reset flag
if clear_clicked:
    st.session_state.reset_filters = True
    try:
        st.toast("Cleared filters.", icon="✅")
    except Exception:
        st.success("Cleared filters.")
    st.rerun()
        if families:
            if family_key(i) not in st.session_state:
                st.session_state[family_key(i)] = families[0]
            chosen_family = st.selectbox("Defect Family", families, key=family_key(i))
            df_cat = df_cat[df_cat["defect_family"] == chosen_family].copy()

# ✅ FIX: When selection changes, repopulate editor widget keys BEFORE the form
if current_project_id != st.session_state.last_loaded_project_id:
    if current_project_id is None:
        editor_clear_widgets()
    else:
        editor_prime_from_loaded(loaded_project, pillar_options, status_list)
    st.session_state.last_loaded_project_id = current_project_id
        defect_options = df_cat["defect"].tolist()
        chosen_defect = st.selectbox("Defect", defect_options, key=defect_key(i))
        c = defect_color_map.get(str(chosen_defect).strip(), "#999999")

# ------------------ Form (Entry) ------------------
st.markdown("---")
st.subheader("Project Editor Form")

with st.form("project_form"):
    c1, c2 = st.columns(2)

    # Preserved variables from your original code (not deleted).
    # Note: editor fields now come from st.session_state keys.
    name_val = loaded_project.get("name") if loaded_project else ""
    pillar_val = loaded_project.get("pillar") if loaded_project else (pillar_options[0] if pillar_options else "")
    priority_val = int(loaded_project.get("priority", 5)) if loaded_project else 5
    owner_val = loaded_project.get("owner") if loaded_project else ""
    status_val = loaded_project.get("status") if loaded_project else ""
    start_val = try_date(loaded_project.get("start_date")) if loaded_project else date.today()
    due_val = try_date(loaded_project.get("due_date")) if loaded_project else date.today()
    desc_val = loaded_project.get("description") if loaded_project else ""
    pw_val = loaded_project.get("plainsware_project", "No") if loaded_project else "No"
    pw_num_val = loaded_project.get("plainsware_number") if loaded_project else None

    with c1:
        project_name = st.text_input("Name*", key="editor_name")

        pillar_index = pillar_options.index(st.session_state.get("editor_pillar", pillar_options[0] if pillar_options else "")) \
            if (pillar_options and st.session_state.get("editor_pillar") in pillar_options) else 0
        project_pillar = st.selectbox(
            "Pillar*",
            options=pillar_options,
            index=pillar_index,
            key="editor_pillar",
        st.markdown(
            f"""
            <div style="display:flex;align-items:center;gap:10px;margin-top:4px;margin-bottom:10px;">
              <div style="width:18px;height:18px;border-radius:4px;background:{c};border:1px solid #333;"></div>
              <div><b>Defect color:</b> <code>{c}</code></div>
            </div>
            """,
            unsafe_allow_html=True
        )

        project_priority = st.number_input(
            "Priority",
            min_value=1,
            max_value=99,
            value=int(st.session_state.get("editor_priority", 5)),
            step=1,
            format="%d",
            key="editor_priority",
        )
        meta = df_cat[df_cat["defect"] == chosen_defect].head(1)
        if not meta.empty and str(meta.iloc[0].get("test_dependent", "No")).lower() == "yes":
            st.warning("⚠️ Test-dependent defect (not image-only).")

        description = st.text_area("Description", height=120, key="editor_desc")
        raw = str(meta.iloc[0].get("classification_options", "Critical\nClass I\nClass II\nClass III")) if not meta.empty else "Critical\nClass I\nClass II\nClass III"
        class_opts = parse_classification_options(raw)

    with c2:
        project_owner = st.text_input(
            "Owner*",
            key="editor_owner",
        )
        # Original selectbox preserved but disabled
        if False:
            st.selectbox("Classification", class_opts, key=class_key(i))

        project_status = st.selectbox(
            "Status",
            [""] + status_list,
            index=safe_index([""] + status_list, st.session_state.get("editor_status", "")),
            key="editor_status",
        )
        crit = [x for x in class_opts if x.lower() == "critical"]
        rest = [x for x in class_opts if x.lower() != "critical"]
        ordered = crit + rest

        start_date = st.date_input("Start Date", value=st.session_state.get("editor_start", date.today()), key="editor_start")
        due_date = st.date_input("Due Date", value=st.session_state.get("editor_due", date.today()), key="editor_due")
        display_map = {}
        display_opts = []
        for v in ordered:
            d = "🛑 Critical" if v.lower() == "critical" else v
            display_map[d] = v
            display_opts.append(d)

        plainsware_project = st.selectbox(
            "Plainsware Project?",
            ["No", "Yes"],
            index=1 if str(st.session_state.get("editor_plainsware_project", "No")).strip() == "Yes" else 0,
            key="editor_plainsware_project",
        chosen_display = st.radio(
            "Classification (select one)",
            display_opts,
            key=f"{class_key(i)}__display"
        )

        plainsware_number = None
        if plainsware_project == "Yes":
            plainsware_number = st.text_input(
                "Planisware Project Number (JJMD-0079575)*",
                placeholder="JJMD-0079575",
                key="editor_plainsware_number",
            )
            if plainsware_number.strip() and not JJMD_PATTERN.fullmatch(plainsware_number.strip()):
                st.warning("Format must be JJMD-0079575 (JJMD- + 7 digits).")
        else:
            plainsware_number = None

    col_a, col_b, col_c = st.columns(3)
    submitted_new = col_a.form_submit_button("Save New")
    submitted_update = col_b.form_submit_button("Update")
    submitted_delete = col_c.form_submit_button("Delete")

# ------------------ CRUD Actions ------------------
if submitted_new:
    errors = []
    project_name_clean = _clean(project_name)
    project_pillar_clean = _clean(project_pillar)
    project_owner_clean = _clean(project_owner)
    project_status_clean = _clean(project_status)
    safe_priority_val = safe_int(project_priority, default=5)

    if not project_name_clean:
        errors.append("Name is required.")
    if not project_pillar_clean:
        errors.append("Pillar is required.")
    if not project_owner_clean:
        errors.append("Owner is required.")

    pw_number_db = None
    if plainsware_project == "Yes":
        try:
            pw_number_db = validate_plainsware(plainsware_project, plainsware_number)
        except Exception as e:
            errors.append(str(e))
        st.session_state[class_key(i)] = display_map[chosen_display]

    if errors:
        st.error(" ".join(errors))
    else:
        ts = now_ts()
        try:
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
                        project_name_clean,
                        project_pillar_clean,
                        safe_priority_val,
                        _clean(description),
                        project_owner_clean,
                        project_status_clean,
                        to_iso(start_date),
                        to_iso(due_date),
                        plainsware_project,
                        pw_number_db,
                        ts,
                        ts,
                    ),
                )

            clear_cache()
            st.success("✅ Project created successfully!")
            st.session_state.reset_project_selector = True
            st.rerun()

        except Exception as e:
            st.error(f"Save error: {e}")
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
        safe_priority_val = safe_int(project_priority, default=5)

        if not project_name_clean:
            errors.append("Name is required.")
        if not project_pillar_clean:
            errors.append("Pillar is required.")
        if not project_owner_clean:
            errors.append("Owner is required.")

        pw_number_db = None
        if plainsware_project == "Yes":
            try:
                pw_number_db = validate_plainsware(plainsware_project, plainsware_number)
            except Exception as e:
                errors.append(str(e))

        if errors:
            st.error(" ".join(errors))
        if str(st.session_state.get(class_key(i), "")).strip().lower() == "critical":
            st.error("🛑 Critical selected — confirmation required.")
            st.checkbox("I confirm this defect is CRITICAL", key=crit_confirm_key(i))
        else:
            ts = now_ts()
            try:
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
                            project_name_clean,
                            project_pillar_clean,
                            safe_priority_val,
                            _clean(description),
                            project_owner_clean,
                            project_status_clean,
                            to_iso(start_date),
                            to_iso(due_date),
                            plainsware_project,
                            pw_number_db,
                            ts,
                            int(loaded_project["id"]),
                        ),
                    )

                clear_cache()
                st.success("✅ Project updated!")
                st.rerun()

            except Exception as e:
                st.error(f"Update error: {e}")
                st.stop()

if submitted_delete:
    if not loaded_project:
        st.warning("Select an existing project to delete.")
    else:
        try:
            with conn() as c:
                c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded_project["id"]),))
            clear_cache()
            st.warning("Project deleted.")
            st.session_state.reset_project_selector = True
            editor_clear_widgets()
            st.rerun()
        except Exception as e:
            st.error(f"Delete error: {e}")
            st.stop()

# ------------------ Global Filters ------------------
st.markdown("---")
st.subheader("Filters")

# ✅ FIX: Apply reset BEFORE creating filter widgets
if st.session_state.reset_filters:
    st.session_state["pillar_f"] = ALL_LABEL
    st.session_state["status_f"] = ALL_LABEL
    st.session_state["owner_f"] = ALL_LABEL
    st.session_state["priority_f"] = ALL_LABEL
    st.session_state["plainsware_f"] = ALL_LABEL
    st.session_state["search_f"] = ""
    st.session_state.reset_filters = False

# Ensure filter keys exist (prevents missing-key surprises)
for k, v in {
    "pillar_f": ALL_LABEL,
    "status_f": ALL_LABEL,
    "owner_f": ALL_LABEL,
    "priority_f": ALL_LABEL,
    "plainsware_f": ALL_LABEL,
    "search_f": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + PRESET_PILLARS.copy()

# FIX: pass _DB_KEY to prevent cached bleed
statuses = [ALL_LABEL] + distinct_values("status", _DB_KEY)
owners = [ALL_LABEL] + distinct_values("owner", _DB_KEY)

priority_vals: List[int] = []
try:
    pv = distinct_values("priority", _DB_KEY)
    priority_vals = sorted({int(x) for x in pv if str(x).strip().isdigit()})
except Exception:
    pass
priority_opts = [ALL_LABEL] + [str(x) for x in priority_vals]
plainsware_opts = [ALL_LABEL, "Yes", "No"]

pillar_f = colF1.selectbox("Pillar", pillars, key="pillar_f")
status_f = colF2.selectbox("Status", statuses, key="status_f")
owner_f = colF3.selectbox("Owner", owners, key="owner_f")
priority_f = colF4.selectbox("Priority", priority_opts, key="priority_f")
plainsware_f = colF5.selectbox("Plainsware", plainsware_opts, key="plainsware_f")
search_f = colF6.text_input("Search", key="search_f")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    plainsware=plainsware_f,
    search=search_f,
)

data = fetch_df(filters)

# ------------------ Derived Years ------------------
data["start_year"] = pd.to_datetime(data.get("start_date", ""), errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data.get("due_date", ""), errors="coerce").dt.year

# ------------------ Report Controls ------------------
st.markdown("---")
st.subheader("Report Controls")
            st.session_state[crit_confirm_key(i)] = False

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"], key="year_mode")
year_col = "start_year" if year_mode == "Start Year" else "due_year"
        st.text_area("Comment (optional)", key=comment_key(i), height=90)

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
b1, b2, b3 = st.columns(3)

with b1:
    if st.button("⬅️ Previous"):
        go_prev()
        safe_rerun()

with b2:
    if st.button("✅ Save & Next"):
        save_and_next()
        safe_rerun()

with b3:
    if st.button("➡️ Next (no save)"):
        go_next()
        safe_rerun()

st.progress((i + 1) / len(images))

# -----------------------
# PARETO
# -----------------------
master_df = load_existing_csv(master_results_path)
src = master_df if not master_df.empty else pd.DataFrame(st.session_state.results)

if not src.empty:
    bad = src[(src["Decision"] == "Bad") & (src["Defect"].notna()) & (src["Defect"] != "")].copy()
    if not bad.empty:
        meta_map = defects_df[["defect", "category", "defect_family"]].drop_duplicates().copy()
        bad = bad.merge(meta_map, how="left", left_on="Defect", right_on="defect")

        st.markdown("## 📊 Pareto")
        if hasattr(st, "tabs"):
            tabs = st.tabs(["By Defect", "By Category", "By Family"])
            tab_targets = [
                (tabs[0], "Defect", "Pareto by Defect"),
                (tabs[1], "category", "Pareto by Category"),
                (tabs[2], "defect_family", "Pareto by Defect Family"),
            ]
            for tab_obj, col, title in tab_targets:
                with tab_obj:
                    if col not in bad.columns:
                        st.info(f"No {col} mapping available.")
                        continue
                    tmp = bad.copy()
                    tmp[col] = tmp[col].fillna("(Unknown)")
                    p = build_pareto(tmp, col)
                    ch = pareto_chart(p, col, title)
                    if ch is not None:
                        safe_altair(ch)
                    else:
                        st.bar_chart(p.set_index(col)["Count"])
    else:
        st.info("No BAD defects recorded yet (Pareto will appear after at least one BAD save).")
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
    st.info("No saved results yet.")

# -----------------------
# REPORT DOWNLOAD
# -----------------------
with st.sidebar.expander("📄 Reports", expanded=False):
    if not master_df.empty:
        z = export_zip_from_master(master_df)
        st.download_button(
            "Download MASTER results (CSV + Snapshots in ZIP)",
            data=z,
            file_name="MASTER_image_review_results_with_snapshots.zip",
            mime="application/zip"
        )
        roadmap_fig.update_yaxes(autorange="reversed")
        st.plotly_chart(roadmap_fig, use_container_width=True)
        st.caption("ZIP includes MASTER CSV + snapshot PNGs (for BAD decisions with ROI).")
    else:
        st.info("No valid date ranges to draw the roadmap.")
        st.caption("No master results yet. Save at least one review.")

# ------------------ Projects Table ------------------
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    st.dataframe(data, use_container_width=True)

# ------------------ Export Options ------------------
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

"""
Preserved (from your screenshot / paste) — not executed:

Digital Portfolio — Web Version
Database unavailable.
SQLiteCloudException: An error occurred while initializing the socket.
...
"""
