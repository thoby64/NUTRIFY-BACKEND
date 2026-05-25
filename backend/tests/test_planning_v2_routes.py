import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SKIP_STARTUP_CHECKS", "true")
os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_URL", "postgresql://thobbs:thobby@localhost:5432/nutrition_db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base
from app.models.models import (
    ClientPlanningProfile,
    Food,
    FoodGroup,
    FoodNutrient,
    Nutrient,
    NutrientType,
    PlanningClient,
    PlanningMealFood,
    PlanningNutrientTarget,
    PlanningPlan,
    PlanningPlanDay,
    PlanningPlanMeal,
    PlanningPlanType,
    PlanningRule,
    User,
    UserRole,
)
from app.routes.planning_v2 import (
    PlanningCustomMealFoodCreateRequest,
    PlanningDayDuplicateRequest,
    add_custom_food_to_meal,
    duplicate_plan_day,
    finalize_planning_plan,
    search_catalog_foods,
)
from app.utils.condition_parser import parse_conditions
from app.utils.planning_v2 import serialize_plan


class PlanningV2RouteTests(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_file.close()
        self.engine = create_engine(
            f"sqlite:///{self.db_file.name}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        with self.SessionLocal() as session:
            self.user = User(
                username="nutritionist1",
                email="nutritionist@example.com",
                password_hash="hashed",
                full_name="Nutritionist One",
                role=UserRole.NUTRITIONIST,
                is_active=True,
            )
            session.add(self.user)

            self.food_group = FoodGroup(name="Test Foods", description="Test")
            session.add(self.food_group)

            macro_type = NutrientType(name="macronutrients", category="macro")
            mineral_type = NutrientType(name="minerals", category="micro")
            session.add_all([macro_type, mineral_type])
            session.flush()

            self.protein = Nutrient(nutrient_type_id=macro_type.id, name="PROCNT", abbreviation="Protein", unit="g")
            self.fiber = Nutrient(nutrient_type_id=macro_type.id, name="FIBTG", abbreviation="Fiber", unit="g")
            self.carbs = Nutrient(nutrient_type_id=macro_type.id, name="CHOCDF", abbreviation="Carbohydrates", unit="g")
            self.sodium = Nutrient(nutrient_type_id=mineral_type.id, name="NA", abbreviation="Sodium", unit="mg")
            self.calcium = Nutrient(nutrient_type_id=mineral_type.id, name="CA", abbreviation="Calcium", unit="mg")
            self.energy = Nutrient(nutrient_type_id=macro_type.id, name="ENERGY_KC", abbreviation="Energy", unit=None)
            session.add_all([self.protein, self.fiber, self.carbs, self.sodium, self.calcium, self.energy])
            session.flush()

            self.food_match = Food(food_group_id=self.food_group.id, name="Power Porridge", code="FOOD-1")
            self.food_block = Food(food_group_id=self.food_group.id, name="Salty Snack", code="FOOD-2")
            session.add_all([self.food_match, self.food_block])
            session.flush()

            session.add_all(
                [
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.protein.id, nutrient_type_id=macro_type.id, value=25, per_unit="100g"),
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.fiber.id, nutrient_type_id=macro_type.id, value=6, per_unit="100g"),
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.carbs.id, nutrient_type_id=macro_type.id, value=45, per_unit="100g"),
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.sodium.id, nutrient_type_id=mineral_type.id, value=180, per_unit="100g"),
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.calcium.id, nutrient_type_id=mineral_type.id, value=120, per_unit="100g"),
                    FoodNutrient(food_id=self.food_match.id, nutrient_id=self.energy.id, nutrient_type_id=macro_type.id, value=100, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.protein.id, nutrient_type_id=macro_type.id, value=10, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.fiber.id, nutrient_type_id=macro_type.id, value=1, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.carbs.id, nutrient_type_id=macro_type.id, value=30, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.sodium.id, nutrient_type_id=mineral_type.id, value=600, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.calcium.id, nutrient_type_id=mineral_type.id, value=40, per_unit="100g"),
                    FoodNutrient(food_id=self.food_block.id, nutrient_id=self.energy.id, nutrient_type_id=macro_type.id, value=150, per_unit="100g"),
                ]
            )

            self.planning_client = PlanningClient(
                client_code="CL-100",
                display_label="Client A",
                assigned_nutritionist_id=self.user.id,
                created_by_id=self.user.id,
                status="active",
            )
            session.add(self.planning_client)
            session.flush()
            session.add(
                ClientPlanningProfile(
                    client_id=self.planning_client.id,
                    dietary_pattern="low sodium",
                    clinical_summary="Type 2 diabetes and osteoporosis follow-up",
                    allergies="peanut",
                    exclusions="shellfish",
                )
            )

            self.plan = PlanningPlan(
                client_id=self.planning_client.id,
                created_by_id=self.user.id,
                assigned_nutritionist_id=self.user.id,
                title="Route Test Plan",
                plan_type=PlanningPlanType.MULTI_DAY,
                days_count=1,
            )
            session.add(self.plan)
            session.flush()

            self.day = PlanningPlanDay(plan_id=self.plan.id, day_index=1, day_name="Day 1")
            session.add(self.day)
            session.flush()

            self.meal = PlanningPlanMeal(day_id=self.day.id, meal_name="Breakfast", meal_order=1, meal_type="breakfast")
            session.add(self.meal)
            session.flush()

            session.add(
                PlanningMealFood(
                    meal_id=self.meal.id,
                    food_id=self.food_match.id,
                    food_name=self.food_match.name,
                    food_code=self.food_match.code,
                    food_group_name=self.food_group.name,
                    portion_grams=100,
                    portion_description="1 bowl",
                    sort_order=1,
                    nutrient_snapshot={
                        "macronutrients": {
                            "ENERGY_KC": {"value": 100, "unit": "kcal", "label": "Energy"},
                            "PROCNT": {"value": 25, "unit": "g", "label": "Protein"},
                            "CHOCDF": {"value": 90, "unit": "g", "label": "Carbohydrates"},
                            "FIBTG": {"value": 2, "unit": "g", "label": "Fiber"},
                        },
                        "vitamins": {},
                        "minerals": {
                            "NA": {"value": 2500, "unit": "mg", "label": "Sodium"},
                            "CA": {"value": 100, "unit": "mg", "label": "Calcium"},
                        },
                        "amino_acids": {},
                    },
                    calculated_nutrients={"ENERGY_KC": 100, "PROCNT": 25, "CHOCDF": 90, "FIBTG": 2, "NA": 2500, "CA": 100},
                )
            )
            session.add(PlanningRule(plan_id=self.plan.id, day_id=self.day.id, scope="day", rule_type="clinical", severity="soft", title="Avoid peanuts", details="peanut"))
            session.add(PlanningNutrientTarget(plan_id=self.plan.id, day_id=self.day.id, nutrient_code="PROCNT", unit="g", min_value=20))
            session.add(PlanningRule(plan_id=self.plan.id, day_id=self.day.id, meal_id=self.meal.id, scope="meal", rule_type="preference", severity="soft", title="Prefer warm foods", details="porridge"))
            session.add(PlanningNutrientTarget(plan_id=self.plan.id, day_id=self.day.id, meal_id=self.meal.id, nutrient_code="ENERGY_KC", unit="kcal", target_value=100))
            session.commit()
            self.user_id = self.user.id
            self.plan_id = self.plan.id
            self.day_id = self.day.id
            self.meal_id = self.meal.id

    def tearDown(self):
        self.engine.dispose()
        Path(self.db_file.name).unlink(missing_ok=True)

    def _current_user(self, session):
        return session.query(User).filter(User.id == self.user_id).first()

    def test_catalog_food_search_supports_condition_string_and_units(self):
        with self.SessionLocal() as session:
            payload = search_catalog_foods(
                search=None,
                conditions="protein >= 20g, fiber >= 5g, sodium <= 300mg",
                food_group_id=None,
                meal_id=None,
                respect_rules=True,
                limit=10,
                db=session,
                current_user=self._current_user(session),
            )
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["data"][0]["name"], "Power Porridge")
        self.assertEqual(len(payload["applied_conditions"]), 3)
        energy_highlight = next(item for item in payload["data"][0]["summary"]["highlights"] if item["code"] == "ENERGY_KC")
        self.assertEqual(energy_highlight["unit"], "kcal")

    def test_condition_parser_supports_exact_codes_and_aliases(self):
        with self.SessionLocal() as session:
            parsed = parse_conditions("ENERGY_KC >= 80, energy >= 80, PROCNT >= 20g, sodium <= 300mg", db=session)

        self.assertEqual(parsed[0].nutrient_code, "ENERGY_KC")
        self.assertEqual(parsed[1].nutrient_code, "ENERGY_KC")
        self.assertEqual(parsed[2].nutrient_code, "PROCNT")
        self.assertEqual(parsed[3].nutrient_code, "NA")

    def test_catalog_food_search_supports_match_any_mode(self):
        with self.SessionLocal() as session:
            payload = search_catalog_foods(
                search=None,
                conditions="PROCNT >= 20g, NA >= 500mg",
                condition_mode="any",
                food_group_id=None,
                meal_id=None,
                respect_rules=True,
                limit=10,
                db=session,
                current_user=self._current_user(session),
            )

        self.assertEqual(payload["condition_mode"], "any")
        self.assertEqual(payload["total"], 2)
        self.assertEqual({row["name"] for row in payload["data"]}, {"Power Porridge", "Salty Snack"})

    def test_duplicate_day_copies_rules_targets_and_foods(self):
        with self.SessionLocal() as session:
            payload = duplicate_plan_day(
                self.day_id,
                request=PlanningDayDuplicateRequest(),
                db=session,
                current_user=self._current_user(session),
            )
        self.assertEqual(payload["days_count"], 2)

        copied_day = next(day for day in payload["days"] if day["day_index"] == 2)
        day_rules = [rule for rule in copied_day["rules"] if rule["scope"] == "day"]
        day_targets = [target for target in copied_day["nutrient_targets"] if target["meal_id"] is None]
        self.assertGreaterEqual(len(day_rules), 1)
        self.assertGreaterEqual(len(day_targets), 1)
        self.assertEqual(len(copied_day["meals"]), 1)
        meal_rules = [rule for rule in copied_day["meals"][0]["rules"] if rule["scope"] == "meal"]
        meal_targets = [target for target in copied_day["meals"][0]["nutrient_targets"] if target["meal_id"] is not None]
        self.assertGreaterEqual(len(meal_rules), 1)
        self.assertGreaterEqual(len(meal_targets), 1)
        self.assertEqual(len(copied_day["meals"][0]["foods"]), 1)

    def test_add_custom_food_supports_weight_unit_conversion(self):
        with self.SessionLocal() as session:
            payload = add_custom_food_to_meal(
                self.meal_id,
                request=PlanningCustomMealFoodCreateRequest(
                    food_name="Clinic Smoothie",
                    food_group_name="Custom recipe",
                    portion_grams=0.5,
                    unit_label="kg",
                    portion_description="1 bottle",
                    nutrients_per_100g=[
                        {"nutrient_code": "ENERGY_KC", "value": 100, "unit": "kcal", "label": "Energy"},
                        {"nutrient_code": "PROCNT", "value": 10, "unit": "g", "label": "Protein"},
                    ],
                ),
                db=session,
                current_user=self._current_user(session),
            )
        meal = payload["days"][0]["meals"][0]
        custom_food = next(food for food in meal["foods"] if food["food_name"] == "Clinic Smoothie")
        self.assertEqual(custom_food["portion_grams"], 500.0)
        self.assertEqual(custom_food["calculated_nutrients"]["ENERGY_KC"], 500.0)

    def test_finalize_plan_creates_version_snapshot(self):
        with self.SessionLocal() as session:
            payload = finalize_planning_plan(
                self.plan_id,
                db=session,
                current_user=self._current_user(session),
            )
        self.assertEqual(payload["version_number"], 1)
        self.assertEqual(payload["status"], "finalized")

    def test_effective_validation_adds_profile_guardrail_warnings(self):
        with self.SessionLocal() as session:
            plan = session.query(PlanningPlan).filter(PlanningPlan.id == self.plan_id).first()
            payload = serialize_plan(plan, include_days=True, include_versions=True)

        checks = payload["effective_validation"]["checks"]
        guardrail_statuses = {(check.get("guardrail_id"), check.get("status")) for check in checks if check.get("kind") == "guardrail"}

        self.assertIn(("low_sodium_support", "above_guardrail_max"), guardrail_statuses)
        self.assertIn(("glycemic_balance_support", "above_guardrail_max"), guardrail_statuses)
        self.assertIn(("glycemic_balance_support", "below_guardrail_min"), guardrail_statuses)
        self.assertIn(("bone_support", "below_guardrail_min"), guardrail_statuses)


if __name__ == "__main__":
    unittest.main()
