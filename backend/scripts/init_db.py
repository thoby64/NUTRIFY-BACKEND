#!/usr/bin/env python3
"""
Legacy entrypoint retained for compatibility.

This project is now migration-driven. Instead of creating tables directly from
SQLAlchemy models, run the SQL migrations:

    python backend/migrations/run_migrations.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    migrations_runner = Path(__file__).resolve().parents[1] / "migrations" / "run_migrations.py"
    print("init_db.py is deprecated. Running SQL migrations instead...")
    return subprocess.call([sys.executable, str(migrations_runner)])


if __name__ == "__main__":
    raise SystemExit(main())
