-- Migration 005: Add privacy-safe planning V2 foundation
-- Creates dedicated tables for planning clients, multi-day plans, days, meals, versions, rules, and targets.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'planningplantype') THEN
        CREATE TYPE planningplantype AS ENUM ('multi_day', 'weekly_cycle', 'template');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'planningplanstatus') THEN
        CREATE TYPE planningplanstatus AS ENUM ('draft', 'review', 'finalized', 'archived');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS planning_clients (
    id SERIAL PRIMARY KEY,
    client_code VARCHAR(100) NOT NULL UNIQUE,
    display_label VARCHAR(255) NOT NULL,
    privacy_tier VARCHAR(50) NOT NULL DEFAULT 'standard',
    assigned_nutritionist_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planning_clients_client_code ON planning_clients(client_code);
CREATE INDEX IF NOT EXISTS idx_planning_clients_assigned_nutritionist_id ON planning_clients(assigned_nutritionist_id);
CREATE INDEX IF NOT EXISTS idx_planning_clients_created_by_id ON planning_clients(created_by_id);

CREATE TABLE IF NOT EXISTS client_planning_profiles (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL UNIQUE REFERENCES planning_clients(id) ON DELETE CASCADE,
    age_group VARCHAR(100),
    sex VARCHAR(50),
    goal_summary TEXT,
    clinical_summary TEXT,
    dietary_pattern VARCHAR(255),
    allergies TEXT,
    exclusions TEXT,
    preferences TEXT,
    cultural_notes TEXT,
    planning_notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS planning_plans (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES planning_clients(id) ON DELETE SET NULL,
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_nutritionist_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    plan_type planningplantype NOT NULL DEFAULT 'multi_day',
    start_date DATE,
    days_count INTEGER NOT NULL DEFAULT 1,
    cycle_length INTEGER,
    status planningplanstatus NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planning_plans_client_id ON planning_plans(client_id);
CREATE INDEX IF NOT EXISTS idx_planning_plans_created_by_id ON planning_plans(created_by_id);
CREATE INDEX IF NOT EXISTS idx_planning_plans_assigned_nutritionist_id ON planning_plans(assigned_nutritionist_id);
CREATE INDEX IF NOT EXISTS idx_planning_plans_status ON planning_plans(status);

CREATE TABLE IF NOT EXISTS planning_plan_days (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES planning_plans(id) ON DELETE CASCADE,
    day_index INTEGER NOT NULL,
    day_name VARCHAR(100) NOT NULL,
    actual_date DATE,
    template_group VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_planning_plan_day_index UNIQUE (plan_id, day_index)
);

CREATE INDEX IF NOT EXISTS idx_planning_plan_days_plan_id ON planning_plan_days(plan_id);

CREATE TABLE IF NOT EXISTS planning_plan_meals (
    id SERIAL PRIMARY KEY,
    day_id INTEGER NOT NULL REFERENCES planning_plan_days(id) ON DELETE CASCADE,
    meal_name VARCHAR(255) NOT NULL,
    meal_type VARCHAR(100),
    meal_time VARCHAR(50),
    meal_order INTEGER NOT NULL,
    instructions TEXT,
    target_notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_planning_day_meal_order UNIQUE (day_id, meal_order)
);

CREATE INDEX IF NOT EXISTS idx_planning_plan_meals_day_id ON planning_plan_meals(day_id);

CREATE TABLE IF NOT EXISTS planning_plan_versions (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES planning_plans(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status planningplanstatus NOT NULL DEFAULT 'draft',
    snapshot_json JSONB,
    finalized_at TIMESTAMP,
    finalized_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_planning_plan_version_number UNIQUE (plan_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_planning_plan_versions_plan_id ON planning_plan_versions(plan_id);

CREATE TABLE IF NOT EXISTS planning_rules (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES planning_clients(id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES planning_plans(id) ON DELETE CASCADE,
    day_id INTEGER REFERENCES planning_plan_days(id) ON DELETE CASCADE,
    meal_id INTEGER REFERENCES planning_plan_meals(id) ON DELETE CASCADE,
    scope VARCHAR(50) NOT NULL DEFAULT 'plan',
    rule_type VARCHAR(100) NOT NULL,
    severity VARCHAR(50) NOT NULL DEFAULT 'soft',
    title VARCHAR(255) NOT NULL,
    details TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planning_rules_plan_id ON planning_rules(plan_id);
CREATE INDEX IF NOT EXISTS idx_planning_rules_day_id ON planning_rules(day_id);
CREATE INDEX IF NOT EXISTS idx_planning_rules_meal_id ON planning_rules(meal_id);

CREATE TABLE IF NOT EXISTS planning_nutrient_targets (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER REFERENCES planning_plans(id) ON DELETE CASCADE,
    day_id INTEGER REFERENCES planning_plan_days(id) ON DELETE CASCADE,
    meal_id INTEGER REFERENCES planning_plan_meals(id) ON DELETE CASCADE,
    nutrient_code VARCHAR(100) NOT NULL,
    unit VARCHAR(50),
    min_value DOUBLE PRECISION,
    target_value DOUBLE PRECISION,
    max_value DOUBLE PRECISION,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planning_nutrient_targets_plan_id ON planning_nutrient_targets(plan_id);
CREATE INDEX IF NOT EXISTS idx_planning_nutrient_targets_day_id ON planning_nutrient_targets(day_id);
CREATE INDEX IF NOT EXISTS idx_planning_nutrient_targets_meal_id ON planning_nutrient_targets(meal_id);
CREATE INDEX IF NOT EXISTS idx_planning_nutrient_targets_code ON planning_nutrient_targets(nutrient_code);
