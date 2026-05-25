-- Rename client_name to plan_name for nutrition_plans
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'nutrition_plans' AND column_name = 'client_name'
    ) THEN
        ALTER TABLE nutrition_plans
            RENAME COLUMN client_name TO plan_name;
    ELSE
        RAISE NOTICE 'Column client_name does not exist on nutrition_plans — skipping rename';
    END IF;
END $$;
