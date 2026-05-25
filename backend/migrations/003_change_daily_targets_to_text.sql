-- Migration 003: Change daily_targets column from JSON to TEXT
-- Allows free-form text input for nutritional targets instead of strict JSON

DO $$
BEGIN
    -- Check if daily_targets column exists and is JSON type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'nutrition_plans' AND column_name = 'daily_targets'
    ) THEN
        -- Check current data type
        IF (SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'nutrition_plans' AND column_name = 'daily_targets') = 'json' THEN
            
            -- Alter column to TEXT, casting any JSON data to text
            ALTER TABLE nutrition_plans 
            ALTER COLUMN daily_targets DROP DEFAULT,
            ALTER COLUMN daily_targets TYPE TEXT USING daily_targets::text;
            
            RAISE NOTICE 'Changed daily_targets column from JSON to TEXT';
        ELSE
            RAISE NOTICE 'daily_targets is not JSON type, skipping conversion';
        END IF;
    ELSE
        RAISE NOTICE 'Column daily_targets does not exist';
    END IF;
END $$;
