# Digital Portfolio — Web HMI + Report & Roadmap (Streamlit)
# ----------------------------------------------------------
import os
import io
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = "portfolio.db"
TABLE = "projects"

# Default lists used to seed the dropdowns (merged with values found in DB)
PILLAR_CHOICES_DEFAULT = [
    "Digital Mindset",
    "Automation",
    "Data & Analytics",
    "Enablement",
    "Infrastructure",
]
STATUS_CHOICES = ["Idea", "In Progress", "Blocked", "Done"]

# ---------- Utilities ----------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db() -> None:
    """Create the projects table if it doesn't exist."""
    with conn() as c:
        c.execute(
            f"""
