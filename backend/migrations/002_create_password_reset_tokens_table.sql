-- Migration 002: Create password_reset_tokens table
-- Stores secure password reset tokens with expiry times

DO $$
BEGIN
    -- Create table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'password_reset_tokens'
    ) THEN
        CREATE TABLE password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );

        -- Create indexes
        CREATE INDEX idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
        CREATE INDEX idx_password_reset_tokens_token ON password_reset_tokens(token);
        CREATE INDEX idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);
        
        RAISE NOTICE 'Created password_reset_tokens table';
    ELSE
        RAISE NOTICE 'Table password_reset_tokens already exists';
    END IF;
END $$;
