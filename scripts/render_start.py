#!/usr/bin/env python3
"""
Render-friendly backend entrypoint.

Runs SQL migrations first, then starts Uvicorn on Render's assigned port.
This keeps a fresh Supabase database from failing on the first deploy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_migrations() -> int:
    migration_runner = ROOT / "migrations" / "run_migrations.py"
    print("Running database migrations before starting the API...")
    result = subprocess.run([sys.executable, str(migration_runner)], cwd=str(ROOT))
    return result.returncode


def start_server() -> int:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = os.getenv("PORT", "10000")
    return subprocess.call(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", port],
        cwd=str(ROOT),
    )


def main() -> int:
    migration_status = run_migrations()
    if migration_status != 0:
        print("Migration step failed. Aborting startup.")
        return migration_status
    return start_server()


if __name__ == "__main__":
    raise SystemExit(main())
