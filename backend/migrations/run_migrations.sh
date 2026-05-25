#!/bin/bash
# Database Migration Script
# Runs all SQL migration files against the PostgreSQL database

set -e

# Database configuration
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME:-nutrition_db}
DB_USER=${DB_USER:-nutritionuser}
DB_PASSWORD=${DB_PASSWORD:-replace-with-a-strong-password}

export PGPASSWORD="$DB_PASSWORD"

echo "🔄 Running database migrations..."
echo "Database: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""

# Get directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run all SQL files in order
for migration_file in "$SCRIPT_DIR"/*.sql; do
    if [ -f "$migration_file" ]; then
        filename=$(basename "$migration_file")
        echo "▶ Applying: $filename"
        
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$migration_file" > /dev/null 2>&1
        
        if [ $? -eq 0 ]; then
            echo "  ✓ Success"
        else
            echo "  ✗ Failed (may already be applied)"
        fi
    fi
done

echo ""
echo "✓ Migrations complete"
