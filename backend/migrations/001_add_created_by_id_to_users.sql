-- Migration 001: Add created_by_id field to users table
-- This tracks which admin/manager created each user

DO $$
BEGIN
    -- Add column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'created_by_id'
    ) THEN
        ALTER TABLE users ADD COLUMN created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
        CREATE INDEX idx_users_created_by_id ON users(created_by_id);
        RAISE NOTICE 'Added created_by_id column to users table';
    ELSE
        RAISE NOTICE 'Column created_by_id already exists';
    END IF;
END $$;
