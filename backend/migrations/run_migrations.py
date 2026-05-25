#!/usr/bin/env python3
"""
Database Migration Runner
Executes pending migrations on the database
Run this before starting the application
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.core.database import SessionLocal, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_migrations_table():
    """Create schema_migrations table if it doesn't exist"""
    with engine.connect() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(50) UNIQUE NOT NULL,
                description VARCHAR(255),
                installed_on TIMESTAMP DEFAULT NOW()
            )
        """))
        connection.commit()
        logger.info("✓ Migrations table ready")


def get_applied_migrations():
    """Get list of already applied migrations"""
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
        return {row[0] for row in result.fetchall()}


def apply_migration(migration_file: Path):
    """Apply a single SQL migration file"""
    version = migration_file.stem.split('_')[0]
    
    with open(migration_file, 'r') as f:
        sql_content = f.read()
    
    try:
        with engine.connect() as connection:
            # Execute SQL
            connection.execute(text(sql_content))
            connection.commit()
        
        logger.info(f"✓ Applied migration {version}: {migration_file.name}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to apply migration {version}: {str(e)}")
        return False


def run_migrations():
    """Run all pending migrations"""
    migrations_dir = Path(__file__).parent
    migration_files = sorted([f for f in migrations_dir.glob("*.sql")])
    
    if not migration_files:
        logger.info("No migration files found")
        return True
    
    # Create migrations table
    create_migrations_table()
    
    # Get already applied migrations
    applied = get_applied_migrations()
    logger.info(f"Already applied migrations: {', '.join(sorted(applied)) or 'None'}")

    # If no applied migrations are recorded but the schema appears present, backfill migration history
    if not applied:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        # If at least the users table exists, assume migrations were applied and backfill
        if 'users' in existing_tables:
            logger.info("No migration history found but schema exists. Backfilling migration history...")
            with engine.connect() as connection:
                for migration_file in migration_files:
                    version = migration_file.stem.split('_')[0]
                    description = migration_file.stem
                    connection.execute(text(
                        "INSERT INTO schema_migrations(version, description, installed_on) VALUES (:version, :desc, NOW()) ON CONFLICT (version) DO NOTHING",
                    ), {"version": version, "desc": description})
                connection.commit()
            applied = get_applied_migrations()
            logger.info(f"Backfilled applied migrations: {', '.join(sorted(applied))}")

    # Run pending migrations
    pending_migrations = [m for m in migration_files if m.stem.split('_')[0] not in applied]
    
    if not pending_migrations:
        logger.info("✓ All migrations already applied")
        return True
    
    logger.info(f"Running {len(pending_migrations)} pending migration(s)...")
    
    for migration_file in pending_migrations:
        if not apply_migration(migration_file):
            logger.error("Migration failed!")
            return False
        # record migration as applied
        version = migration_file.stem.split('_')[0]
        description = migration_file.stem
        with engine.connect() as connection:
            connection.execute(text(
                "INSERT INTO schema_migrations(version, description, installed_on) VALUES (:version, :desc) ON CONFLICT (version) DO NOTHING",
            ), {"version": version, "desc": description})
            connection.commit()
    
    logger.info(f"✓ All {len(pending_migrations)} migration(s) applied successfully")
    return True


if __name__ == "__main__":
    try:
        success = run_migrations()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)
