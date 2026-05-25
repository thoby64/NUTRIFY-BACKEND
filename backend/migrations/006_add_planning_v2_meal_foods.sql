-- Migration 006: Add V2 planning meal foods
-- Preserves food snapshots inside the new multi-day planner.

CREATE TABLE IF NOT EXISTS planning_meal_foods (
    id SERIAL PRIMARY KEY,
    meal_id INTEGER NOT NULL REFERENCES planning_plan_meals(id) ON DELETE CASCADE,
    food_id INTEGER REFERENCES foods(id) ON DELETE SET NULL,
    food_name VARCHAR(255) NOT NULL,
    food_code VARCHAR(50),
    food_group_name VARCHAR(100),
    portion_grams DOUBLE PRECISION NOT NULL,
    portion_description VARCHAR(120),
    household_measure VARCHAR(120),
    unit_label VARCHAR(50),
    preparation_state VARCHAR(100),
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 1,
    nutrient_snapshot JSONB NOT NULL,
    calculated_nutrients JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planning_meal_foods_meal_id ON planning_meal_foods(meal_id);
CREATE INDEX IF NOT EXISTS idx_planning_meal_foods_food_id ON planning_meal_foods(food_id);
