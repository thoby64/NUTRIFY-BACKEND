#!/usr/bin/env python3
"""
Bootstrap or rotate an administrator account explicitly.

Examples:
  python backend/scripts/bootstrap_admin.py --username admin --password 'ChangeMe123!' --email admin@example.com
  python backend/scripts/bootstrap_admin.py --username admin --password 'NewPassword123!' --email admin@example.com --rotate-password
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.auth import hash_password
from app.core.database import SessionLocal
from app.models.models import User, UserRole


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or rotate an administrator account")
    parser.add_argument("--username", required=True, help="Admin username")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--email", required=True, help="Admin email")
    parser.add_argument("--full-name", default="Administrator", help="Full display name")
    parser.add_argument(
        "--rotate-password",
        action="store_true",
        help="Update the password if the admin already exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = SessionLocal()

    try:
        existing = session.query(User).filter(User.username == args.username).first()
        if existing:
            existing.email = args.email
            existing.full_name = args.full_name
            existing.role = UserRole.ADMIN
            existing.is_active = True
            if args.rotate_password:
                existing.password_hash = hash_password(args.password)
            session.commit()
            print(f"Admin account ready: username={existing.username} email={existing.email}")
            print("Password updated." if args.rotate_password else "Password unchanged.")
            return 0

        session.add(
            User(
                username=args.username,
                email=args.email,
                password_hash=hash_password(args.password),
                full_name=args.full_name,
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        session.commit()
        print(f"Admin account created: username={args.username} email={args.email}")
        return 0
    except IntegrityError as error:
        session.rollback()
        print(f"Unable to bootstrap admin due to a uniqueness conflict: {error}")
        return 1
    except Exception as error:  # pragma: no cover - defensive for CLI usage
        session.rollback()
        print(f"Admin bootstrap failed: {error}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
