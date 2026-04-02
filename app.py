# ----------------------------------------------------------
# Digital Portfolio — Web Version (Portfolio App)
# ✅ Persistent SQLite Cloud version
# - No local DB file (Streamlit Cloud filesystem is ephemeral)
# - Uses sqlitecloud (sqlite3-compatible DB-API style)
# - Uses DB-in-path connection string: ...:8860/Portfolio?apikey=...
# - No local DB file (Streamlit Cloud filesystem is ephemeral)  # see Streamlit docs note [1]( /
# - Uses sqlitecloud (sqlite3-compatible DB-API style)          # [2]( /
# - Uses DB-in-path connection string: ...:8860/Portfolio?apikey=...  # [2]( /
# - Adds PRESET_PILLARS merged with DB values (fixes "only one pillar")
# ----------------------------------------------------------

@@ -38,11 +38,13 @@
# ------------------ Constants ------------------
TABLE = "projects"

# FIX: Use real text, not HTML entities (prevents comparison + UI issues)
# FIX: HTML entity → real text (prevents Python/UI issues)
# You originally had "&lt;New Project&gt;" which can cause comparisons to fail if any decoding happens.
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"

# FIX: Use real text (optional but recommended for readability)
# FIX: HTML entities → real text (keep your labels readable)
# Keeping your original intent but using real ampersands avoids UI oddities.
PRESET_PILLARS = [
    "Digital Mindset",
    "Advanced Analytics",
@@ -81,9 +83,12 @@ def _normalize_sqlitecloud_netloc(netloc: str) -> str:
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
@@ -96,8 +101,10 @@ def _normalize_sqlitecloud_netloc(netloc: str) -> str:

def _swap_port(url: str, new_port: int) -> str:
    u = urlparse(url)
    # Build new netloc with swapped port
    if u.hostname:
        host = u.hostname
        # preserve userinfo if any
        userinfo = ""
        if u.username:
            userinfo = u.username
@@ -137,7 +144,46 @@ def _validate_db_name(db_name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", db_name))


# ------------------ Misc Helpers (needed by editor helpers) ------------------
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

@@ -176,11 +222,11 @@ def _clean(s: Any) -> str:
    return (s or "").strip()


# ------------------ Editor helpers (FIXED + COMPLETE) ------------------
# NOTE: These helpers must be at top-level (not inside another function).
# ------------------ Editor helpers (FIXED placement + COMPLETE) ------------------
# These MUST be top-level functions (not indented inside another function).

def editor_defaults():
    # These keys match YOUR FORM widget keys (editor_*)
    """Defaults for editor widget keys."""
    return {
        "editor_name": "",
        "editor_pillar": PRESET_PILLARS[0] if PRESET_PILLARS else "",
@@ -196,38 +242,38 @@ def editor_defaults():


def editor_clear_widgets():
    # Reset all widget-bound keys
    """Clear EVERYTHING in the editor by resetting widget keys."""
    for k, v in editor_defaults().items():
        st.session_state[k] = v


def editor_prime_from_loaded(loaded_project: Optional[dict], pillar_options: List[str], status_list: List[str]):
    """
    SAFE: Only write to widget keys BEFORE widgets are created.
    We call this BEFORE the st.form() section. We also guard with project-change detection.
    Populate editor widget keys from DB row.
    Must be called BEFORE the form widgets are created on the run.
    """
    if not loaded_project:
        # New / none selected
        editor_clear_widgets()
        return

    # Prime widget keys from DB
    st.session_state["editor_name"] = loaded_project.get("name") or ""
    pillar_val = loaded_project.get("pillar") or (pillar_options[0] if pillar_options else "")
    st.session_state["editor_pillar"] = pillar_val if pillar_val in pillar_options else (pillar_options[0] if pillar_options else "")

    pv = loaded_project.get("pillar") or (pillar_options[0] if pillar_options else "")
    st.session_state["editor_pillar"] = pv if pv in pillar_options else (pillar_options[0] if pillar_options else "")

    st.session_state["editor_priority"] = safe_int(loaded_project.get("priority"), 5)
    st.session_state["editor_desc"] = loaded_project.get("description") or ""
    st.session_state["editor_owner"] = loaded_project.get("owner") or ""

    status_val = loaded_project.get("status") or ""
    # allow blank + values in status_list
    st.session_state["editor_status"] = status_val if (status_val == "" or status_val in status_list) else ""
    sv = loaded_project.get("status") or ""
    st.session_state["editor_status"] = sv if (sv == "" or sv in status_list) else ""

    st.session_state["editor_start"] = try_date(loaded_project.get("start_date")) or date.today()
    st.session_state["editor_due"] = try_date(loaded_project.get("due_date")) or date.today()

    pw_val = loaded_project.get("plainsware_project", "No") or "No"
    st.session_state["editor_plainsware_project"] = "Yes" if str(pw_val).strip().lower() == "yes" else "No"
    pw = loaded_project.get("plainsware_project", "No") or "No"
    st.session_state["editor_plainsware_project"] = "Yes" if str(pw).strip().lower() == "yes" else "No"

    st.session_state["editor_plainsware_number"] = (loaded_project.get("plainsware_number") or "").strip()


@@ -241,10 +287,13 @@ def conn():
    """
    url = _get_sqlitecloud_url()

    # --- Connection attempts (no deletions; just safer behavior) ---
    last_exc = None
    candidates = []

    candidates.append(url)

    # normalize hostname typos
    try:
        u = urlparse(url)
        normalized_netloc = _normalize_sqlitecloud_netloc(u.netloc)
@@ -253,10 +302,12 @@ def conn():
    except Exception:
        pass

    # port fallback 8860 -> 8861
    try:
        u = urlparse(url)
        if u.port == 8860:
            candidates.append(_swap_port(url, 8861))
            # also combine with normalized host + port swap
            try:
                u2 = urlparse(candidates[-1])
                normalized_netloc2 = _normalize_sqlitecloud_netloc(u2.netloc)
@@ -271,7 +322,7 @@ def conn():
    for candidate in candidates:
        try:
            c = sqlitecloud.connect(candidate)
            url = candidate
            url = candidate  # remember the one that worked for masking/debug
            break
        except Exception as e:
            last_exc = e
@@ -285,6 +336,7 @@ def conn():
        st.exception(last_exc)
        st.stop()

    # FIX: Optional but recommended: select DB file after connecting
    db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()
    try:
        if db_name:
@@ -314,44 +366,6 @@ def assert_db_awake():
        st.stop()


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

# ------------------ Schema / Migration Helpers ------------------
def _table_info_df(c) -> pd.DataFrame:
    return pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
@@ -603,8 +617,10 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
st.set_page_config(page_title="Digital Portfolio", layout="wide")
st.title("Digital Portfolio — Web Version")

# Now safe to compute DB key (no Streamlit calls before set_page_config)
_DB_KEY = _mask_url(_get_sqlitecloud_url())

# ✅ APP1 safety lock (must be BEFORE any DB call)
db_name = (st.secrets.get("SQLITECLOUD_DB_PORTFOLIO") or "").strip()

if not db_name:
@@ -615,9 +631,12 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
actual_path = urlparse(_get_sqlitecloud_url()).path or ""

if actual_path != EXPECTED_DB_PATH:
    st.error(f"❌ APP1 wrong DB configured. Expected {EXPECTED_DB_PATH}, got {actual_path}")
    st.error(
        f"❌ APP1 wrong DB configured. Expected {EXPECTED_DB_PATH}, got {actual_path}"
    )
    st.stop()

# ✅ TEMP banner for verification (REMOVE after confirming once)
st.caption("APP1 DB URL → " + _mask_url(_get_sqlitecloud_url()))

assert_db_awake()
@@ -630,14 +649,20 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    st.session_state.project_selector = NEW_LABEL
if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False

# NEW: track last loaded project id to know when to repopulate editor
if "last_loaded_project_id" not in st.session_state:
    st.session_state.last_loaded_project_id = None  # used for change-detection
    st.session_state.last_loaded_project_id = None

# NEW: filter reset flag (fix Clear Filters)
if "reset_filters" not in st.session_state:
    st.session_state.reset_filters = False

if st.session_state.reset_project_selector:
    st.session_state.project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False
    st.session_state.last_loaded_project_id = None
    # ALSO clear editor widget values when reset
    # also clear editor widgets
    editor_clear_widgets()

# ------------------ Project Editor ------------------
@@ -658,7 +683,6 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:

loaded_project = None
current_project_id = None

if selected_project != NEW_LABEL:
    try:
        current_project_id = int(selected_project.split(" — ", 1)[0])
@@ -674,6 +698,7 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
pillar_options = PRESET_PILLARS.copy()
pillar_options = sorted(set(PRESET_PILLARS) | set(pillar_from_db))

# FIX: pass _DB_KEY to cached distinct_values
status_from_db = distinct_values("status", _DB_KEY)
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))
owner_list = distinct_values("owner", _DB_KEY)
@@ -682,29 +707,21 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
new_clicked = bcol1.button("New", key="btn_new_project")
clear_clicked = bcol2.button("Clear Filters", key="btn_clear_filters")

# ✅ FIX: "New" clears editor too (user request)
if new_clicked:
    st.session_state.reset_project_selector = True
    editor_clear_widgets()
    st.session_state.last_loaded_project_id = None
    st.rerun()

# FIX: Clear Filters reliably resets filter widgets via reset flag
if clear_clicked:
    st.session_state.update({
        "pillar_f": ALL_LABEL,
        "status_f": ALL_LABEL,
        "owner_f": ALL_LABEL,
        "priority_f": ALL_LABEL,
        "plainsware_f": ALL_LABEL,
        "search_f": "",
    })
    st.session_state.reset_filters = True
    try:
        st.toast("Cleared filters.", icon="✅")
    except Exception:
        st.success("Cleared filters.")
    st.rerun()

# ✅ FIX: Prime editor widget keys when selection changes (BEFORE form renders)
# ✅ FIX: When selection changes, repopulate editor widget keys BEFORE the form
if current_project_id != st.session_state.last_loaded_project_id:
    if current_project_id is None:
        editor_clear_widgets()
@@ -719,8 +736,8 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
with st.form("project_form"):
    c1, c2 = st.columns(2)

    # NOTE: values are now driven from session_state keys (primed above).
    # Keeping your existing locals (not deleted), but they no longer control widget state.
    # Preserved variables from your original code (not deleted).
    # Note: editor fields now come from st.session_state keys.
    name_val = loaded_project.get("name") if loaded_project else ""
    pillar_val = loaded_project.get("pillar") if loaded_project else (pillar_options[0] if pillar_options else "")
    priority_val = int(loaded_project.get("priority", 5)) if loaded_project else 5
@@ -733,13 +750,14 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    pw_num_val = loaded_project.get("plainsware_number") if loaded_project else None

    with c1:
        # ✅ FIX: remove value=... dependence; use session_state keys
        project_name = st.text_input("Name*", key="editor_name")

        pillar_index = pillar_options.index(st.session_state.get("editor_pillar", pillar_options[0] if pillar_options else "")) \
            if (pillar_options and st.session_state.get("editor_pillar") in pillar_options) else 0
        project_pillar = st.selectbox(
            "Pillar*",
            options=pillar_options,
            index=safe_index(pillar_options, st.session_state.get("editor_pillar", pillar_options[0] if pillar_options else "")),
            index=pillar_index,
            key="editor_pillar",
        )

@@ -756,7 +774,10 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
        description = st.text_area("Description", height=120, key="editor_desc")

    with c2:
        project_owner = st.text_input("Owner*", key="editor_owner")
        project_owner = st.text_input(
            "Owner*",
            key="editor_owner",
        )

        project_status = st.selectbox(
            "Status",
@@ -937,9 +958,33 @@ def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
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
