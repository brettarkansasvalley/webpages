#!/usr/bin/env python3
#config.py
"""
Configuration constants for the Restaurant Tip Distribution System
"""

# --- TOUCHSCREEN FRIENDLY MODIFICATIONS (COMPACT) ---
UNIFORM_FONT = ("Helvetica", 12)
UNIFORM_BOLD = ("Helvetica", 12, "bold")
TREEVIEW_HEADING_FONT = ("Helvetica", 20)
TREEVIEW_ROW_HEIGHT = 30
SCROLLBAR_WIDTH = 60
PAD_X = 6
PAD_Y = 3
# --- END MODIFICATIONS ---

# Application settings
ADMIN_PASSWORD = "071925"
MAX_LOGIN_ATTEMPTS = 5
WINDOW_GEOMETRY = "1024x600"

# Database file
DATABASE_FILE = 'tip_distribution.db'

# Bucket configuration
BUCKETS = {
    "am_bar": {"tips": {"bartips": 0.0, "servertips": 0.0, "expotips": 0.0, "runnertips": 0.0}},
    "eastwing": {"tips": {"bartips": 0.0, "servertips": 0.0, "expotips": 0.0, "runnertips": 0.0}},
    "westwing": {"tips": {"bartips": 0.0, "servertips": 0.0, "expotips": 0.0, "runnertips": 0.0}},
    "sunset": {"tips": {"bartips": 0.0, "servertips": 0.0, "expotips": 0.0, "runnertips": 0.0}},
}

# Cash drawers
CASH_DRAWERS = ["AM Bar", "West Wing Bar", "Sunset Bar", "Office"]

# Bucket display names
BUCKET_DISPLAY_NAMES = [
    ("am_bar", "AM"),
    ("eastwing", "East Wing"),
    ("westwing", "West Wing"),
    ("sunset", "Sunset")
]
