"""Vercel entrypoint for FastAPI app."""

from __future__ import annotations

import os
import sys

# Ensure the src/ layout is importable when running directly in Vercel.
PROJECT_ROOT = os.path.dirname(__file__)
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from claude_db_agent.api import app

__all__ = ["app"]
