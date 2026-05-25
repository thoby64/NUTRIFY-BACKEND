"""
Planning V2 helpers
Shared nutrient snapshot, total aggregation, and serialization utilities.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from app.models.models import (
    PlanningClient,
    PlanningMealFood,
    PlanningNutrientTarget,
    PlanningPlan,
    PlanningPlanDay,
    PlanningPlanMeal,
    PlanningPlanVersion,
    PlanningRule,
)
from app.utils.planning_validation import build_client_profile_rules, build_effective_plan_validation, build_scope_validation


KEY_NUTRIENTS = [
    {"code": "ENERGY_KC", "label": "Energy", "unit": "kcal"},
    {"code": "PROCNT", "label": "Protein", "unit": "g"},
    {"code": "FAT", "label": "Fat", "unit": "g"},
    {"code": "CHOCDF", "label": "Carbohydrates", "unit": "g"},
    {"code": "FIBTG", "label": "Fiber", "unit": "g"},
]

KEY_NUTRIENT_LABELS = {item["code"]: item["label"] for item in KEY_NUTRIENTS}
KEY_NUTRIENT_UNITS = {item["code"]: item["unit"] for item in KEY_NUTRIENTS}


def infer_default_nutrient_unit(nutrient_code: Optional[str]) -> str:
    """Best-effort default unit when the source nutrient record has no unit."""
    code = str(nutrient_code or "").strip().upper()
    if code in KEY_NUTRIENT_UNITS:
        return KEY_NUTRIENT_UNITS[code]
    if code in {"NA", "K", "CA", "P", "MG", "FE", "ZN", "CU", "MN"}:
        return "mg"
    if code in {"SE", "VITA", "FOL", "VIT B12"}:
        return "mcg"
    return "g"

DEFAULT_MEAL_TEMPLATES = [
    {"meal_name": "Breakfast", "meal_type": "breakfast", "meal_time": "07:00"},
    {"meal_name": "Morning Snack", "meal_type": "snack", "meal_time": "10:00"},
    {"meal_name": "Lunch", "meal_type": "lunch", "meal_time": "13:00"},
    {"meal_name": "Afternoon Snack", "meal_type": "snack", "meal_time": "16:00"},
    {"meal_name": "Dinner", "meal_type": "dinner", "meal_time": "19:00"},
]

RULE_TYPE_OPTIONS = [
    "clinical",
    "allergy",
    "preference",
    "timing",
    "budget",
    "texture",
    "ingredient",
    "hydration",
    "supplement",
]

RULE_SEVERITY_OPTIONS = ["hard", "soft", "info"]


def isoformat_or_none(value: Optional[datetime | date]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def get_nutrient_category(nutrient_type_name: Optional[str]) -> str:
    """Map nutrient type names into stable snapshot categories."""
    name_lower = (nutrient_type_name or "").lower()

    if "amino" in name_lower:
        return "amino_acids"
    if "vitamin" in name_lower:
        return "vitamins"
    if "mineral" in name_lower:
        return "minerals"
    return "macronutrients"


def build_nutrient_snapshot(food_nutrients: Iterable[Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Build a categorized nutrient snapshot from FoodNutrient rows."""
    snapshot = {
        "macronutrients": {},
        "vitamins": {},
        "minerals": {},
        "amino_acids": {},
    }

    for food_nutrient in food_nutrients:
        nutrient = getattr(food_nutrient, "nutrient", None)
        nutrient_type = getattr(food_nutrient, "nutrient_type_rel", None)
        nutrient_code = getattr(nutrient, "name", None) or getattr(nutrient, "abbreviation", None) or str(food_nutrient.nutrient_id)
        category = get_nutrient_category(getattr(nutrient_type, "name", None))
        snapshot[category][nutrient_code] = {
            "value": round(float(food_nutrient.value or 0), 4),
            "unit": getattr(nutrient, "unit", None) or infer_default_nutrient_unit(nutrient_code),
            "label": getattr(nutrient, "abbreviation", None) or nutrient_code,
        }

    return snapshot


def calculate_portion_nutrients(
    nutrient_snapshot: Dict[str, Dict[str, Dict[str, Any]]],
    portion_grams: float,
) -> Dict[str, float]:
    """Scale per-100g nutrient snapshot into the requested portion."""
    multiplier = float(portion_grams or 0) / 100.0
    totals: Dict[str, float] = {}

    for nutrients in nutrient_snapshot.values():
        for nutrient_code, nutrient_data in nutrients.items():
            totals[nutrient_code] = round(float(nutrient_data.get("value") or 0) * multiplier, 2)

    return totals


def _collect_units_and_labels(
    nutrient_snapshot: Optional[Dict[str, Dict[str, Dict[str, Any]]]],
    units: Dict[str, str],
    labels: Dict[str, str],
) -> None:
    if not nutrient_snapshot:
        return

    for nutrients in nutrient_snapshot.values():
        for nutrient_code, nutrient_data in nutrients.items():
            units.setdefault(nutrient_code, nutrient_data.get("unit") or KEY_NUTRIENT_UNITS.get(nutrient_code) or "")
            labels.setdefault(nutrient_code, nutrient_data.get("label") or KEY_NUTRIENT_LABELS.get(nutrient_code) or nutrient_code)


def aggregate_nutrients_from_foods(foods: Iterable[PlanningMealFood]) -> Dict[str, Any]:
    """Aggregate nutrient totals for a list of V2 meal foods."""
    totals: Dict[str, float] = {}
    units: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    food_count = 0

    for food in foods:
        food_count += 1
        _collect_units_and_labels(food.nutrient_snapshot or {}, units, labels)
        for nutrient_code, nutrient_value in (food.calculated_nutrients or {}).items():
            totals[nutrient_code] = round(totals.get(nutrient_code, 0.0) + float(nutrient_value or 0.0), 2)

    ordered_codes = [
        item["code"] for item in KEY_NUTRIENTS if item["code"] in totals
    ] + sorted(code for code in totals.keys() if code not in KEY_NUTRIENT_LABELS)

    return {
        "foods_count": food_count,
        "totals": [
            {
                "code": nutrient_code,
                "label": labels.get(nutrient_code) or KEY_NUTRIENT_LABELS.get(nutrient_code) or nutrient_code,
                "unit": units.get(nutrient_code) or KEY_NUTRIENT_UNITS.get(nutrient_code) or "",
                "value": round(totals.get(nutrient_code, 0.0), 2),
            }
            for nutrient_code in ordered_codes
        ],
        "highlights": [
            {
                "code": nutrient_code,
                "label": KEY_NUTRIENT_LABELS[nutrient_code],
                "unit": units.get(nutrient_code) or KEY_NUTRIENT_UNITS.get(nutrient_code) or "",
                "value": round(totals.get(nutrient_code, 0.0), 2),
            }
            for nutrient_code in KEY_NUTRIENT_LABELS
        ],
    }


def aggregate_nutrients_from_meals(meals: Iterable[PlanningPlanMeal]) -> Dict[str, Any]:
    """Aggregate nutrient totals from a set of plan meals."""
    meal_foods: List[PlanningMealFood] = []
    meal_count = 0

    for meal in meals:
        meal_count += 1
        meal_foods.extend(sorted(meal.foods, key=lambda item: (item.sort_order, item.id)))

    summary = aggregate_nutrients_from_foods(meal_foods)
    summary["meal_count"] = meal_count
    return summary


def serialize_client(client: PlanningClient) -> Dict[str, Any]:
    """Serialize a privacy-safe planning client."""
    profile = client.planning_profile
    assigned_name = None
    if client.assigned_nutritionist:
        assigned_name = client.assigned_nutritionist.full_name or client.assigned_nutritionist.username

    return {
        "id": client.id,
        "client_code": client.client_code,
        "display_label": client.display_label,
        "privacy_tier": client.privacy_tier,
        "status": client.status,
        "notes": client.notes,
        "assigned_nutritionist_id": client.assigned_nutritionist_id,
        "assigned_nutritionist_name": assigned_name,
        "created_by_id": client.created_by_id,
        "created_at": isoformat_or_none(client.created_at),
        "updated_at": isoformat_or_none(client.updated_at),
        "profile": {
            "age_group": profile.age_group if profile else None,
            "sex": profile.sex if profile else None,
            "goal_summary": profile.goal_summary if profile else None,
            "clinical_summary": profile.clinical_summary if profile else None,
            "dietary_pattern": profile.dietary_pattern if profile else None,
            "allergies": profile.allergies if profile else None,
            "exclusions": profile.exclusions if profile else None,
            "preferences": profile.preferences if profile else None,
            "cultural_notes": profile.cultural_notes if profile else None,
            "planning_notes": profile.planning_notes if profile else None,
        },
    }


def serialize_meal_food(food: PlanningMealFood) -> Dict[str, Any]:
    """Serialize a selected V2 meal food."""
    return {
        "id": food.id,
        "meal_id": food.meal_id,
        "food_id": food.food_id,
        "food_name": food.food_name,
        "food_code": food.food_code,
        "food_group_name": food.food_group_name,
        "portion_grams": food.portion_grams,
        "portion_description": food.portion_description,
        "household_measure": food.household_measure,
        "unit_label": food.unit_label,
        "preparation_state": food.preparation_state,
        "notes": food.notes,
        "sort_order": food.sort_order,
        "nutrient_snapshot": food.nutrient_snapshot,
        "calculated_nutrients": food.calculated_nutrients,
        "created_at": isoformat_or_none(food.created_at),
        "updated_at": isoformat_or_none(food.updated_at),
    }


def serialize_rule(rule: PlanningRule) -> Dict[str, Any]:
    """Serialize a planning rule at plan, day, or meal scope."""
    return {
        "id": rule.id,
        "scope": rule.scope,
        "rule_type": rule.rule_type,
        "severity": rule.severity,
        "title": rule.title,
        "details": rule.details,
        "is_active": rule.is_active,
        "client_id": rule.client_id,
        "plan_id": rule.plan_id,
        "day_id": rule.day_id,
        "meal_id": rule.meal_id,
        "created_at": isoformat_or_none(rule.created_at),
        "updated_at": isoformat_or_none(rule.updated_at),
    }


def serialize_target(target: PlanningNutrientTarget) -> Dict[str, Any]:
    """Serialize a scoped nutrient target."""
    return {
        "id": target.id,
        "plan_id": target.plan_id,
        "day_id": target.day_id,
        "meal_id": target.meal_id,
        "nutrient_code": target.nutrient_code,
        "unit": target.unit,
        "min_value": target.min_value,
        "target_value": target.target_value,
        "max_value": target.max_value,
        "created_at": isoformat_or_none(target.created_at),
        "updated_at": isoformat_or_none(target.updated_at),
    }


def serialize_meal(meal: PlanningPlanMeal, include_foods: bool = True) -> Dict[str, Any]:
    """Serialize a V2 plan meal with nutrient totals."""
    foods = sorted(meal.foods, key=lambda item: (item.sort_order, item.id))
    nutrient_summary = aggregate_nutrients_from_foods(foods)
    rules = sorted(meal.rules, key=lambda item: (item.severity, item.title.lower(), item.id))
    nutrient_targets = sorted(meal.nutrient_targets, key=lambda item: (item.nutrient_code, item.id))
    data = {
        "id": meal.id,
        "meal_name": meal.meal_name,
        "meal_type": meal.meal_type,
        "meal_time": meal.meal_time,
        "meal_order": meal.meal_order,
        "instructions": meal.instructions,
        "target_notes": meal.target_notes,
        "summary": nutrient_summary,
        "validation": build_scope_validation("meal", rules, nutrient_targets, foods, nutrient_summary),
        "rules": [serialize_rule(rule) for rule in rules],
        "nutrient_targets": [serialize_target(target) for target in nutrient_targets],
        "created_at": isoformat_or_none(meal.created_at),
        "updated_at": isoformat_or_none(meal.updated_at),
    }

    if include_foods:
        data["foods"] = [serialize_meal_food(food) for food in foods]

    return data


def serialize_day(day: PlanningPlanDay, include_meals: bool = True, include_foods: bool = True) -> Dict[str, Any]:
    """Serialize a V2 plan day with nested meals."""
    meals = sorted(day.meals, key=lambda item: item.meal_order)
    nutrient_summary = aggregate_nutrients_from_meals(meals)
    rules = sorted(day.rules, key=lambda item: (item.severity, item.title.lower(), item.id))
    nutrient_targets = sorted(day.nutrient_targets, key=lambda item: (item.nutrient_code, item.id))
    data = {
        "id": day.id,
        "day_index": day.day_index,
        "day_name": day.day_name,
        "actual_date": day.actual_date.isoformat() if day.actual_date else None,
        "template_group": day.template_group,
        "notes": day.notes,
        "summary": nutrient_summary,
        "validation": build_scope_validation("day", rules, nutrient_targets, [food for meal in meals for food in meal.foods], nutrient_summary),
        "rules": [serialize_rule(rule) for rule in rules],
        "nutrient_targets": [serialize_target(target) for target in nutrient_targets],
        "created_at": isoformat_or_none(day.created_at),
        "updated_at": isoformat_or_none(day.updated_at),
    }

    if include_meals:
        data["meals"] = [serialize_meal(meal, include_foods=include_foods) for meal in meals]

    return data


def serialize_version(version: PlanningPlanVersion) -> Dict[str, Any]:
    """Serialize a finalized plan version."""
    return {
        "id": version.id,
        "plan_id": version.plan_id,
        "version_number": version.version_number,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
        "finalized_at": isoformat_or_none(version.finalized_at),
        "finalized_by_id": version.finalized_by_id,
        "created_at": isoformat_or_none(version.created_at),
    }


def serialize_plan(
    plan: PlanningPlan,
    include_days: bool = False,
    include_foods: bool = True,
    include_versions: bool = False,
) -> Dict[str, Any]:
    """Serialize a V2 planning plan with optional nested days and versions."""
    assigned_name = None
    if plan.assigned_nutritionist:
        assigned_name = plan.assigned_nutritionist.full_name or plan.assigned_nutritionist.username

    created_by_name = None
    if plan.created_by:
        created_by_name = plan.created_by.full_name or plan.created_by.username

    days = sorted(plan.days, key=lambda item: item.day_index)
    plan_summary = aggregate_nutrients_from_meals([meal for day in days for meal in day.meals])
    rules = sorted(
        build_client_profile_rules(getattr(plan.client, "planning_profile", None)) + list(plan.rules),
        key=lambda item: (item.severity, (item.title or "").lower(), item.id or 0),
    )
    nutrient_targets = sorted(plan.nutrient_targets, key=lambda item: (item.nutrient_code, item.id))

    data = {
        "id": plan.id,
        "title": plan.title,
        "plan_type": plan.plan_type.value if hasattr(plan.plan_type, "value") else str(plan.plan_type),
        "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "days_count": plan.days_count,
        "cycle_length": plan.cycle_length,
        "notes": plan.notes,
        "client_id": plan.client_id,
        "client_display_label": plan.client.display_label if plan.client else None,
        "client_code": plan.client.client_code if plan.client else None,
        "client_profile": serialize_client(plan.client).get("profile") if plan.client else None,
        "assigned_nutritionist_id": plan.assigned_nutritionist_id,
        "assigned_nutritionist_name": assigned_name,
        "created_by_id": plan.created_by_id,
        "created_by_name": created_by_name,
        "summary": plan_summary,
        "validation": build_scope_validation("plan", rules, nutrient_targets, [food for day in days for meal in day.meals for food in meal.foods], plan_summary),
        "effective_validation": build_effective_plan_validation(plan),
        "rules": [serialize_rule(rule) for rule in rules],
        "nutrient_targets": [serialize_target(target) for target in nutrient_targets],
        "created_at": isoformat_or_none(plan.created_at),
        "updated_at": isoformat_or_none(plan.updated_at),
    }

    if include_days:
        data["days"] = [serialize_day(day, include_meals=True, include_foods=include_foods) for day in days]

    if include_versions:
        versions = sorted(plan.versions, key=lambda item: item.version_number, reverse=True)
        data["versions"] = [serialize_version(version) for version in versions]

    return data
