"""
Backfill meal_foods (snapshot data) for a target plan.

Usage examples:
  DEBUG=true backend/venv/bin/python backend/scripts/backfill_plan_snapshots.py --plan-name "PLAN A"
  DEBUG=true backend/venv/bin/python backend/scripts/backfill_plan_snapshots.py --plan-id 135 --source-plan-id 2 --execute
"""

from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.models import Meal, MealFood, NutritionPlan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill meal_foods snapshot data for a plan")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--plan-id", type=int, help="Target plan id")
    target.add_argument("--plan-name", type=str, help="Target plan name (case-insensitive)")
    parser.add_argument("--source-plan-id", type=int, help="Source plan id to clone meal_foods from")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry-run)")
    return parser.parse_args()


def find_target_plan(session, plan_id: Optional[int], plan_name: Optional[str]) -> NutritionPlan:
    if plan_id is not None:
        plan = session.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
        if not plan:
            raise ValueError(f"No plan found with id {plan_id}")
        return plan

    assert plan_name is not None
    plans = (
        session.query(NutritionPlan)
        .filter(func.lower(NutritionPlan.plan_name) == plan_name.lower())
        .order_by(NutritionPlan.status.desc(), NutritionPlan.created_at.desc())
        .all()
    )
    if not plans:
        raise ValueError(f"No plan found with plan_name '{plan_name}'")
    return plans[0]


def get_plan_meals(session, plan_id: int) -> List[Meal]:
    return (
        session.query(Meal)
        .filter(Meal.plan_id == plan_id)
        .order_by(Meal.meal_order.asc())
        .all()
    )


def count_meal_foods(session, plan_id: int) -> int:
    return (
        session.query(MealFood)
        .join(Meal, Meal.id == MealFood.meal_id)
        .filter(Meal.plan_id == plan_id)
        .count()
    )


def map_source_meals(source_meals: List[Meal]) -> Tuple[Dict[str, Meal], Dict[int, Meal]]:
    by_name = {meal.meal_name.lower(): meal for meal in source_meals if meal.meal_name}
    by_order = {meal.meal_order: meal for meal in source_meals if meal.meal_order is not None}
    return by_name, by_order


def clone_meal_foods(session, target_meals: List[Meal], source_plan_id: int, execute: bool) -> int:
    source_meals = get_plan_meals(session, source_plan_id)
    if not source_meals:
        raise ValueError(f"Source plan {source_plan_id} has no meals")

    source_by_name, source_by_order = map_source_meals(source_meals)
    created_count = 0

    for target_meal in target_meals:
        source_meal = None
        if target_meal.meal_name:
            source_meal = source_by_name.get(target_meal.meal_name.lower())
        if source_meal is None:
            source_meal = source_by_order.get(target_meal.meal_order)

        if source_meal is None:
            print(f"- No source match for meal '{target_meal.meal_name}' (order {target_meal.meal_order})")
            continue

        source_foods = session.query(MealFood).filter(MealFood.meal_id == source_meal.id).all()
        if not source_foods:
            print(f"- Source meal '{source_meal.meal_name}' has no foods")
            continue

        for mf in source_foods:
            created_count += 1
            if execute:
                session.add(
                    MealFood(
                        meal_id=target_meal.id,
                        food_id=mf.food_id,
                        food_name=mf.food_name,
                        food_group_name=mf.food_group_name,
                        portion_grams=mf.portion_grams,
                        portion_description=mf.portion_description,
                        nutrient_snapshot=mf.nutrient_snapshot,
                        calculated_nutrients=mf.calculated_nutrients,
                    )
                )

    return created_count


def main() -> int:
    args = parse_args()
    session = SessionLocal()
    try:
        target_plan = find_target_plan(session, args.plan_id, args.plan_name)
        target_meals = get_plan_meals(session, target_plan.id)
        existing_foods = count_meal_foods(session, target_plan.id)

        print(f"Target plan: {target_plan.id} | {target_plan.plan_name} | status={target_plan.status}")
        print(f"Meals: {len(target_meals)} | Existing meal_foods: {existing_foods}")

        if existing_foods > 0:
            print("No action taken: target plan already has meal_foods.")
            return 0

        if not args.source_plan_id:
            print("No source plan provided. Use --source-plan-id to clone snapshots.")
            return 2

        created_count = clone_meal_foods(session, target_meals, args.source_plan_id, args.execute)
        print(f"Meal foods to clone: {created_count}")

        if args.execute and created_count > 0:
            session.commit()
            print("✓ Backfill committed")
        elif args.execute:
            print("Nothing to commit")
        else:
            print("Dry-run only. Re-run with --execute to apply changes.")
        return 0
    except Exception as exc:
        session.rollback()
        print(f"Error: {exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
