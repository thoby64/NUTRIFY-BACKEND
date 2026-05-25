"""
Planning V2 Routes
Privacy-safe client planning references and multi-day planning workflows.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.auth import require_any_of_roles
from app.core.database import get_db
from app.models.models import (
    ClientPlanningProfile,
    Food,
    FoodNutrient,
    Nutrient,
    PlanningClient,
    PlanningMealFood,
    PlanningNutrientTarget,
    PlanningPlan,
    PlanningPlanDay,
    PlanningPlanMeal,
    PlanningPlanStatus,
    PlanningPlanType,
    PlanningPlanVersion,
    PlanningRule,
    User,
)
from app.utils.condition_parser import (
    ConditionParseError,
    describe_conditions,
    filter_foods_by_conditions,
    get_condition_alias_reference,
    parse_conditions,
)
from app.utils.planning_v2 import (
    DEFAULT_MEAL_TEMPLATES,
    KEY_NUTRIENT_LABELS,
    KEY_NUTRIENTS,
    RULE_SEVERITY_OPTIONS,
    RULE_TYPE_OPTIONS,
    aggregate_nutrients_from_foods,
    build_nutrient_snapshot,
    calculate_portion_nutrients,
    serialize_client,
    serialize_plan,
)
from app.utils.planning_substitutions import (
    build_nutrient_deltas,
    build_replacement_note,
    build_similarity_summary,
    infer_exchange_category,
    score_substitution,
)
from app.utils.planning_validation import evaluate_food_against_rules, get_effective_context


router = APIRouter(prefix="/api/v2/planning", tags=["planning-v2"])


class PlanningProfileInput(BaseModel):
    age_group: Optional[str] = None
    sex: Optional[str] = None
    goal_summary: Optional[str] = None
    clinical_summary: Optional[str] = None
    dietary_pattern: Optional[str] = None
    allergies: Optional[str] = None
    exclusions: Optional[str] = None
    preferences: Optional[str] = None
    cultural_notes: Optional[str] = None
    planning_notes: Optional[str] = None


class PlanningClientCreateRequest(BaseModel):
    client_code: str = Field(..., min_length=2, max_length=100)
    display_label: str = Field(..., min_length=2, max_length=255)
    privacy_tier: Optional[str] = Field(default="standard", max_length=50)
    assigned_nutritionist_id: Optional[int] = None
    notes: Optional[str] = None
    profile: Optional[PlanningProfileInput] = None


class DefaultMealInput(BaseModel):
    meal_name: str = Field(..., min_length=1, max_length=255)
    meal_type: Optional[str] = Field(None, max_length=100)
    meal_time: Optional[str] = Field(None, max_length=50)


class PlanningPlanCreateRequest(BaseModel):
    client_id: Optional[int] = None
    title: str = Field(..., min_length=2, max_length=255)
    plan_type: PlanningPlanType = PlanningPlanType.MULTI_DAY
    start_date: Optional[date] = None
    days_count: int = Field(default=1, ge=1, le=90)
    cycle_length: Optional[int] = Field(default=None, ge=1, le=90)
    notes: Optional[str] = None
    use_default_meal_template: bool = True
    default_meals: Optional[List[DefaultMealInput]] = None


class PlanningPlanCloneRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    client_id: Optional[int] = None
    start_date: Optional[date] = None
    plan_type: Optional[PlanningPlanType] = None
    notes: Optional[str] = None
    include_foods: bool = True


class PlanningPlanUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=255)
    start_date: Optional[date] = None
    cycle_length: Optional[int] = Field(default=None, ge=1, le=90)
    notes: Optional[str] = None


class PlanningDayCreateRequest(BaseModel):
    day_name: Optional[str] = Field(default=None, max_length=100)
    actual_date: Optional[date] = None
    template_group: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class PlanningDayUpdateRequest(BaseModel):
    day_name: Optional[str] = Field(default=None, max_length=100)
    actual_date: Optional[date] = None
    template_group: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class PlanningDayDuplicateRequest(BaseModel):
    day_name: Optional[str] = Field(default=None, max_length=100)
    actual_date: Optional[date] = None
    template_group: Optional[str] = Field(default=None, max_length=100)


class PlanningMealCreateRequest(BaseModel):
    meal_name: str = Field(..., min_length=1, max_length=255)
    meal_type: Optional[str] = Field(default=None, max_length=100)
    meal_time: Optional[str] = Field(default=None, max_length=50)
    instructions: Optional[str] = None
    target_notes: Optional[str] = None


class PlanningMealUpdateRequest(BaseModel):
    meal_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    meal_type: Optional[str] = Field(default=None, max_length=100)
    meal_time: Optional[str] = Field(default=None, max_length=50)
    meal_order: Optional[int] = Field(default=None, ge=1, le=30)
    instructions: Optional[str] = None
    target_notes: Optional[str] = None


class PlanningMealFoodCreateRequest(BaseModel):
    food_id: int
    portion_grams: float = Field(..., gt=0, le=5000)
    portion_description: Optional[str] = Field(default=None, max_length=120)
    household_measure: Optional[str] = Field(default=None, max_length=120)
    unit_label: Optional[str] = Field(default=None, max_length=50)
    preparation_state: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class PlanningMealFoodUpdateRequest(BaseModel):
    portion_grams: Optional[float] = Field(default=None, gt=0, le=5000)
    portion_description: Optional[str] = Field(default=None, max_length=120)
    household_measure: Optional[str] = Field(default=None, max_length=120)
    unit_label: Optional[str] = Field(default=None, max_length=50)
    preparation_state: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class CustomFoodNutrientInput(BaseModel):
    nutrient_code: str = Field(..., min_length=2, max_length=100)
    value: float = Field(..., ge=0)
    unit: Optional[str] = Field(default=None, max_length=50)
    label: Optional[str] = Field(default=None, max_length=100)


class PlanningCustomMealFoodCreateRequest(BaseModel):
    food_name: str = Field(..., min_length=2, max_length=255)
    food_group_name: Optional[str] = Field(default="Custom recipe", max_length=100)
    portion_grams: float = Field(..., gt=0, le=5000)
    portion_description: Optional[str] = Field(default=None, max_length=120)
    household_measure: Optional[str] = Field(default=None, max_length=120)
    unit_label: Optional[str] = Field(default=None, max_length=50)
    preparation_state: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    nutrients_per_100g: List[CustomFoodNutrientInput] = Field(default_factory=list, min_length=1)


class PlanningMealFoodReplaceRequest(BaseModel):
    food_id: int
    portion_grams: Optional[float] = Field(default=None, gt=0, le=5000)
    portion_description: Optional[str] = Field(default=None, max_length=120)
    household_measure: Optional[str] = Field(default=None, max_length=120)
    unit_label: Optional[str] = Field(default=None, max_length=50)
    preparation_state: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    replacement_reason: Optional[str] = Field(default=None, max_length=255)


class PlanningRuleCreateRequest(BaseModel):
    rule_type: str = Field(..., min_length=2, max_length=100)
    severity: str = Field(default="soft", min_length=2, max_length=50)
    title: str = Field(..., min_length=2, max_length=255)
    details: Optional[str] = None
    is_active: bool = True


class PlanningRuleUpdateRequest(BaseModel):
    rule_type: Optional[str] = Field(default=None, min_length=2, max_length=100)
    severity: Optional[str] = Field(default=None, min_length=2, max_length=50)
    title: Optional[str] = Field(default=None, min_length=2, max_length=255)
    details: Optional[str] = None
    is_active: Optional[bool] = None


class PlanningTargetCreateRequest(BaseModel):
    nutrient_code: str = Field(..., min_length=2, max_length=100)
    unit: Optional[str] = Field(default=None, max_length=50)
    min_value: Optional[float] = None
    target_value: Optional[float] = None
    max_value: Optional[float] = None


class PlanningTargetUpdateRequest(BaseModel):
    nutrient_code: Optional[str] = Field(default=None, min_length=2, max_length=100)
    unit: Optional[str] = Field(default=None, max_length=50)
    min_value: Optional[float] = None
    target_value: Optional[float] = None
    max_value: Optional[float] = None


def _plan_load_options():
    return (
        selectinload(PlanningPlan.client).selectinload(PlanningClient.planning_profile),
        selectinload(PlanningPlan.days)
        .selectinload(PlanningPlanDay.meals)
        .selectinload(PlanningPlanMeal.foods),
        selectinload(PlanningPlan.days).selectinload(PlanningPlanDay.meals).selectinload(PlanningPlanMeal.rules),
        selectinload(PlanningPlan.days).selectinload(PlanningPlanDay.meals).selectinload(PlanningPlanMeal.nutrient_targets),
        selectinload(PlanningPlan.days).selectinload(PlanningPlanDay.rules),
        selectinload(PlanningPlan.days).selectinload(PlanningPlanDay.nutrient_targets),
        selectinload(PlanningPlan.assigned_nutritionist),
        selectinload(PlanningPlan.created_by),
        selectinload(PlanningPlan.versions),
        selectinload(PlanningPlan.rules),
        selectinload(PlanningPlan.nutrient_targets),
    )


def _mark_plan_dirty(plan: PlanningPlan) -> None:
    if plan.status != PlanningPlanStatus.ARCHIVED:
        plan.status = PlanningPlanStatus.DRAFT
    plan.updated_at = datetime.now(timezone.utc)


def _clone_rule(rule: PlanningRule, *, plan_id: int, day_id: Optional[int] = None, meal_id: Optional[int] = None) -> PlanningRule:
    scope = "plan"
    if meal_id:
        scope = "meal"
    elif day_id:
        scope = "day"

    return PlanningRule(
        client_id=rule.client_id,
        plan_id=plan_id,
        day_id=day_id,
        meal_id=meal_id,
        scope=scope,
        rule_type=rule.rule_type,
        severity=rule.severity,
        title=rule.title,
        details=rule.details,
        is_active=rule.is_active,
    )


def _clone_target(
    target: PlanningNutrientTarget,
    *,
    plan_id: int,
    day_id: Optional[int] = None,
    meal_id: Optional[int] = None,
) -> PlanningNutrientTarget:
    return PlanningNutrientTarget(
        plan_id=plan_id,
        day_id=day_id,
        meal_id=meal_id,
        nutrient_code=target.nutrient_code,
        unit=target.unit,
        min_value=target.min_value,
        target_value=target.target_value,
        max_value=target.max_value,
    )


def _custom_snapshot_category(nutrient_code: str) -> str:
    nutrient_code = (nutrient_code or "").upper()
    if nutrient_code in {"FE", "CA", "ZN", "MG", "K", "P", "CU", "MN", "NA", "SE"}:
        return "minerals"
    if nutrient_code.startswith("VIT") or nutrient_code in {"THIA", "RIBF", "NIA", "PANT", "FOL", "BIOTIN", "VITA", "VITC", "VITE"}:
        return "vitamins"
    if nutrient_code in {"TRP", "LYS", "TYR", "THR", "ILE", "LEU", "MET", "CYS", "PHE", "VAL", "ARG", "HIS", "ALA", "ASP", "ASN", "GLU", "GLN", "GLY", "PRO", "SER"}:
        return "amino_acids"
    return "macronutrients"


def _build_custom_snapshot(nutrients: List[CustomFoodNutrientInput]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    snapshot = {
        "macronutrients": {},
        "vitamins": {},
        "minerals": {},
        "amino_acids": {},
    }
    for nutrient in nutrients:
        code = nutrient.nutrient_code.strip().upper()
        category = _custom_snapshot_category(code)
        snapshot[category][code] = {
            "value": round(float(nutrient.value), 4),
            "unit": nutrient.unit or "",
            "label": nutrient.label or code,
        }
    return snapshot


def _normalize_portion_grams(portion_value: float, unit_label: Optional[str]) -> float:
    unit = (unit_label or "").strip().lower()
    if not unit:
        return float(portion_value)

    conversions = {
        "g": 1.0,
        "gram": 1.0,
        "grams": 1.0,
        "kg": 1000.0,
        "kilogram": 1000.0,
        "kilograms": 1000.0,
        "oz": 28.3495,
        "ounce": 28.3495,
        "ounces": 28.3495,
        "lb": 453.592,
        "lbs": 453.592,
        "pound": 453.592,
        "pounds": 453.592,
    }
    return round(float(portion_value) * conversions.get(unit, 1.0), 2)


def _require_visible_client(db: Session, client_id: int, current_user: User) -> PlanningClient:
    client = (
        db.query(PlanningClient)
        .options(
            selectinload(PlanningClient.planning_profile),
            selectinload(PlanningClient.assigned_nutritionist),
        )
        .filter(PlanningClient.id == client_id)
        .first()
    )
    if not client:
        raise HTTPException(status_code=404, detail="Planning client not found")

    if current_user.role.value == "nutritionist":
        allowed = client.assigned_nutritionist_id == current_user.id or client.created_by_id == current_user.id
        if not allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this planning client")

    return client


def _require_visible_plan(db: Session, plan_id: int, current_user: User) -> PlanningPlan:
    plan = db.query(PlanningPlan).options(*_plan_load_options()).filter(PlanningPlan.id == plan_id).first()

    if not plan:
        raise HTTPException(status_code=404, detail="Planning plan not found")

    if current_user.role.value == "nutritionist":
        allowed = plan.assigned_nutritionist_id == current_user.id or plan.created_by_id == current_user.id
        if not allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this planning plan")

    return plan


def _require_visible_day(db: Session, day_id: int, current_user: User) -> PlanningPlanDay:
    day = (
        db.query(PlanningPlanDay)
        .options(
            selectinload(PlanningPlanDay.plan),
            selectinload(PlanningPlanDay.meals).selectinload(PlanningPlanMeal.foods),
            selectinload(PlanningPlanDay.meals).selectinload(PlanningPlanMeal.rules),
            selectinload(PlanningPlanDay.meals).selectinload(PlanningPlanMeal.nutrient_targets),
            selectinload(PlanningPlanDay.rules),
            selectinload(PlanningPlanDay.nutrient_targets),
        )
        .filter(PlanningPlanDay.id == day_id)
        .first()
    )
    if not day:
        raise HTTPException(status_code=404, detail="Planning day not found")

    _require_visible_plan(db, day.plan_id, current_user)
    return day


def _require_visible_meal(db: Session, meal_id: int, current_user: User) -> PlanningPlanMeal:
    meal = (
        db.query(PlanningPlanMeal)
        .options(
            selectinload(PlanningPlanMeal.day).selectinload(PlanningPlanDay.plan),
            selectinload(PlanningPlanMeal.foods),
            selectinload(PlanningPlanMeal.rules),
            selectinload(PlanningPlanMeal.nutrient_targets),
        )
        .filter(PlanningPlanMeal.id == meal_id)
        .first()
    )
    if not meal:
        raise HTTPException(status_code=404, detail="Planning meal not found")

    _require_visible_plan(db, meal.day.plan_id, current_user)
    return meal


def _require_visible_meal_food(db: Session, meal_food_id: int, current_user: User) -> PlanningMealFood:
    meal_food = (
        db.query(PlanningMealFood)
        .options(
            selectinload(PlanningMealFood.meal)
            .selectinload(PlanningPlanMeal.day)
            .selectinload(PlanningPlanDay.plan)
        )
        .filter(PlanningMealFood.id == meal_food_id)
        .first()
    )
    if not meal_food:
        raise HTTPException(status_code=404, detail="Planning meal food not found")

    _require_visible_plan(db, meal_food.meal.day.plan_id, current_user)
    return meal_food


def _require_visible_rule(db: Session, rule_id: int, current_user: User) -> PlanningRule:
    rule = (
        db.query(PlanningRule)
        .options(
            selectinload(PlanningRule.plan),
            selectinload(PlanningRule.day).selectinload(PlanningPlanDay.plan),
            selectinload(PlanningRule.meal).selectinload(PlanningPlanMeal.day).selectinload(PlanningPlanDay.plan),
        )
        .filter(PlanningRule.id == rule_id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Planning rule not found")

    if rule.meal_id and rule.meal and rule.meal.day:
        _require_visible_plan(db, rule.meal.day.plan_id, current_user)
    elif rule.day_id and rule.day:
        _require_visible_plan(db, rule.day.plan_id, current_user)
    elif rule.plan_id:
        _require_visible_plan(db, rule.plan_id, current_user)
    else:
        raise HTTPException(status_code=400, detail="Planning rule is not attached to a valid scope")

    return rule


def _require_visible_target(db: Session, target_id: int, current_user: User) -> PlanningNutrientTarget:
    target = (
        db.query(PlanningNutrientTarget)
        .options(
            selectinload(PlanningNutrientTarget.plan),
            selectinload(PlanningNutrientTarget.day).selectinload(PlanningPlanDay.plan),
            selectinload(PlanningNutrientTarget.meal).selectinload(PlanningPlanMeal.day).selectinload(PlanningPlanDay.plan),
        )
        .filter(PlanningNutrientTarget.id == target_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Planning nutrient target not found")

    if target.meal_id and target.meal and target.meal.day:
        _require_visible_plan(db, target.meal.day.plan_id, current_user)
    elif target.day_id and target.day:
        _require_visible_plan(db, target.day.plan_id, current_user)
    elif target.plan_id:
        _require_visible_plan(db, target.plan_id, current_user)
    else:
        raise HTTPException(status_code=400, detail="Planning nutrient target is not attached to a valid scope")

    return target


def _renumber_plan_days(plan: PlanningPlan) -> None:
    for index, day in enumerate(sorted(plan.days, key=lambda item: item.day_index), start=1):
        day.day_index = index


def _validate_rule_payload(rule_type: str, severity: str) -> None:
    if severity not in RULE_SEVERITY_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid rule severity. Use one of: {', '.join(RULE_SEVERITY_OPTIONS)}")
    if len(rule_type.strip()) < 2:
        raise HTTPException(status_code=400, detail="Rule type is required")


def _validate_target_payload(min_value: Optional[float], target_value: Optional[float], max_value: Optional[float]) -> None:
    if min_value is None and target_value is None and max_value is None:
        raise HTTPException(status_code=400, detail="At least one nutrient target value is required")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise HTTPException(status_code=400, detail="Minimum target cannot be greater than maximum target")


def _serialize_food_catalog_item(food: Food) -> Dict[str, Any]:
    snapshot = build_nutrient_snapshot(food.nutrients)
    calculated = calculate_portion_nutrients(snapshot, 100)
    summary = aggregate_nutrients_from_foods(
        [
            PlanningMealFood(
                food_name=food.name,
                food_code=food.code,
                food_group_name=food.food_group.name if food.food_group else None,
                portion_grams=100,
                nutrient_snapshot=snapshot,
                calculated_nutrients=calculated,
            )
        ]
    )

    return {
        "id": food.id,
        "name": food.name,
        "code": food.code,
        "description": food.description,
        "food_group_id": food.food_group_id,
        "food_group_name": food.food_group.name if food.food_group else None,
        "summary": summary,
    }


def _build_food_target_preview(food_item: Dict[str, Any], targets: List[PlanningNutrientTarget]) -> List[Dict[str, Any]]:
    preview: List[Dict[str, Any]] = []
    totals_index = {item["code"]: item for item in food_item.get("summary", {}).get("totals", [])}
    seen = set()

    for target in targets:
        code = target.nutrient_code
        if code in seen or code not in totals_index:
            continue
        seen.add(code)
        nutrient_item = totals_index[code]
        preview.append(
            {
                "nutrient_code": code,
                "value": nutrient_item.get("value"),
                "unit": nutrient_item.get("unit") or target.unit,
                "min_value": target.min_value,
                "target_value": target.target_value,
                "max_value": target.max_value,
            }
        )
        if len(preview) >= 4:
            break

    return preview


def _build_food_item_for_portion(food: Food, portion_grams: float) -> Dict[str, Any]:
    """Build planner food summary for a specific portion size."""
    snapshot = build_nutrient_snapshot(food.nutrients)
    calculated = calculate_portion_nutrients(snapshot, portion_grams)
    summary = aggregate_nutrients_from_foods(
        [
            PlanningMealFood(
                food_name=food.name,
                food_code=food.code,
                food_group_name=food.food_group.name if food.food_group else None,
                portion_grams=portion_grams,
                nutrient_snapshot=snapshot,
                calculated_nutrients=calculated,
            )
        ]
    )
    return {
        "id": food.id,
        "name": food.name,
        "code": food.code,
        "description": food.description,
        "food_group_id": food.food_group_id,
        "food_group_name": food.food_group.name if food.food_group else None,
        "portion_grams": portion_grams,
        "nutrient_snapshot": snapshot,
        "calculated_nutrients": calculated,
        "summary": summary,
    }


@router.get("/meta")
def get_planning_meta(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Return metadata for the V2 planning workspace."""
    nutrient_catalog = [
        {
            "code": nutrient.name,
            "label": nutrient.abbreviation or nutrient.name,
            "unit": nutrient.unit or "",
        }
        for nutrient in db.query(Nutrient).order_by(Nutrient.name.asc()).all()
    ]
    return {
        "plan_types": [
            {"value": PlanningPlanType.MULTI_DAY.value, "label": "Dated multi-day plan"},
            {"value": PlanningPlanType.WEEKLY_CYCLE.value, "label": "Weekly cycle plan"},
            {"value": PlanningPlanType.TEMPLATE.value, "label": "Reusable template"},
        ],
        "plan_statuses": [
            {"value": PlanningPlanStatus.DRAFT.value, "label": "Draft"},
            {"value": PlanningPlanStatus.REVIEW.value, "label": "In review"},
            {"value": PlanningPlanStatus.FINALIZED.value, "label": "Finalized"},
            {"value": PlanningPlanStatus.ARCHIVED.value, "label": "Archived"},
        ],
        "privacy_principles": [
            "Use client codes and display labels in routine planning screens",
            "Store only derived planning-safe profile details in the planner foundation",
            "Keep deep personal identity data outside the core planning workflow",
        ],
        "key_nutrients": KEY_NUTRIENTS,
        "nutrient_catalog": nutrient_catalog,
        "condition_aliases": get_condition_alias_reference(),
        "default_meal_templates": DEFAULT_MEAL_TEMPLATES,
        "rule_types": RULE_TYPE_OPTIONS,
        "rule_severities": RULE_SEVERITY_OPTIONS,
    }


@router.get("/catalog/foods")
def search_catalog_foods(
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    conditions: Optional[str] = Query(None, min_length=3, max_length=500),
    condition_mode: str = Query("all", pattern="^(all|any)$"),
    food_group_id: Optional[int] = Query(None, ge=1),
    meal_id: Optional[int] = Query(None, ge=1),
    respect_rules: bool = Query(True),
    limit: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Search planner-friendly foods with nutrient highlights."""
    normalized_condition_mode = condition_mode if isinstance(condition_mode, str) else getattr(condition_mode, "default", "all")

    query = db.query(Food).options(
        selectinload(Food.food_group),
        selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient),
        selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient_type_rel),
    )

    if search:
        query = query.filter(Food.name.ilike(f"%{search}%"))

    if food_group_id:
        query = query.filter(Food.food_group_id == food_group_id)

    parsed_conditions = []
    if conditions:
        try:
            parsed_conditions = parse_conditions(conditions, db=db)
        except ConditionParseError as error:
            raise HTTPException(status_code=400, detail=str(error))

        matching_food_ids = filter_foods_by_conditions(db, parsed_conditions, mode=normalized_condition_mode)
        if not matching_food_ids:
            return {
                "data": [],
                "total": 0,
                "excluded_count": 0,
                "excluded_examples": [],
                "rule_context": None,
                "condition_mode": normalized_condition_mode,
                "applied_conditions": describe_conditions(parsed_conditions),
            }
        query = query.filter(Food.id.in_(matching_food_ids))

    effective_rules: List[PlanningRule] = []
    effective_targets: List[PlanningNutrientTarget] = []
    rule_context: Optional[Dict[str, Any]] = None
    if meal_id:
        meal = _require_visible_meal(db, meal_id, current_user)
        effective_rules, effective_targets = get_effective_context(meal.day.plan, meal.day, meal)
        rule_context = {
            "meal_id": meal.id,
            "meal_name": meal.meal_name,
            "day_id": meal.day_id,
            "day_name": meal.day.day_name,
            "hard_rules_count": len([rule for rule in effective_rules if rule.severity == "hard"]),
            "rules_count": len(effective_rules),
            "targets_count": len(effective_targets),
        }

    foods = query.order_by(Food.name.asc()).limit(min(max(limit * 4, limit), 100)).all()
    results = []
    excluded = []

    for food in foods:
        food_item = _serialize_food_catalog_item(food)
        if meal_id:
            compatibility = evaluate_food_against_rules(food.name, food.food_group.name if food.food_group else None, effective_rules)
            food_item["compatibility"] = compatibility
            food_item["target_preview"] = _build_food_target_preview(food_item, effective_targets)

            if respect_rules and compatibility["hard_blocked"]:
                excluded.append(
                    {
                        "id": food.id,
                        "name": food.name,
                        "blocked_by": compatibility["blocked_by"],
                    }
                )
                continue

        results.append(food_item)
        if len(results) >= limit:
            break

    return {
        "data": results,
        "total": len(results),
        "condition_mode": normalized_condition_mode,
        "excluded_count": len(excluded),
        "excluded_examples": excluded[:5],
        "rule_context": rule_context,
        "applied_conditions": describe_conditions(parsed_conditions),
    }


@router.get("/clients")
def list_planning_clients(
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """List privacy-safe planning client references."""
    query = db.query(PlanningClient).options(
        selectinload(PlanningClient.planning_profile),
        selectinload(PlanningClient.assigned_nutritionist),
    )

    if current_user.role.value == "nutritionist":
        query = query.filter(
            or_(
                PlanningClient.assigned_nutritionist_id == current_user.id,
                PlanningClient.created_by_id == current_user.id,
            )
        )

    if search:
        query = query.filter(
            or_(
                PlanningClient.client_code.ilike(f"%{search}%"),
                PlanningClient.display_label.ilike(f"%{search}%"),
            )
        )

    clients = query.order_by(PlanningClient.created_at.desc()).all()
    return {"data": [serialize_client(client) for client in clients], "total": len(clients)}


@router.post("/clients")
def create_planning_client(
    request: PlanningClientCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Create a privacy-safe planning client."""
    existing = db.query(PlanningClient).filter(func.lower(PlanningClient.client_code) == request.client_code.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Client code already exists")

    assigned_nutritionist_id = request.assigned_nutritionist_id
    if current_user.role.value == "nutritionist":
        assigned_nutritionist_id = current_user.id

    if assigned_nutritionist_id:
        assigned_user = db.query(User).filter(User.id == assigned_nutritionist_id).first()
        if not assigned_user:
            raise HTTPException(status_code=404, detail="Assigned nutritionist not found")

    try:
        client = PlanningClient(
            client_code=request.client_code,
            display_label=request.display_label,
            privacy_tier=request.privacy_tier or "standard",
            assigned_nutritionist_id=assigned_nutritionist_id,
            created_by_id=current_user.id,
            notes=request.notes,
            status="active",
        )
        db.add(client)
        db.flush()

        if request.profile:
            db.add(
                ClientPlanningProfile(
                    client_id=client.id,
                    age_group=request.profile.age_group,
                    sex=request.profile.sex,
                    goal_summary=request.profile.goal_summary,
                    clinical_summary=request.profile.clinical_summary,
                    dietary_pattern=request.profile.dietary_pattern,
                    allergies=request.profile.allergies,
                    exclusions=request.profile.exclusions,
                    preferences=request.profile.preferences,
                    cultural_notes=request.profile.cultural_notes,
                    planning_notes=request.profile.planning_notes,
                )
            )

        db.commit()
        db.refresh(client)
        return serialize_client(_require_visible_client(db, client.id, current_user))
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create planning client: {error}")


@router.get("/plans")
def list_planning_plans(
    status: Optional[PlanningPlanStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """List V2 planning plans."""
    query = db.query(PlanningPlan).options(*_plan_load_options())

    if current_user.role.value == "nutritionist":
        query = query.filter(
            or_(
                PlanningPlan.assigned_nutritionist_id == current_user.id,
                PlanningPlan.created_by_id == current_user.id,
            )
        )

    if status:
        query = query.filter(PlanningPlan.status == status)

    plans = query.order_by(PlanningPlan.created_at.desc()).all()
    return {"data": [serialize_plan(plan, include_versions=True) for plan in plans], "total": len(plans)}


@router.post("/plans")
def create_planning_plan(
    request: PlanningPlanCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Create a multi-day planning plan draft."""
    assigned_nutritionist_id = current_user.id if current_user.role.value == "nutritionist" else None
    client = None

    if request.client_id:
        client = _require_visible_client(db, request.client_id, current_user)
        if not assigned_nutritionist_id:
            assigned_nutritionist_id = client.assigned_nutritionist_id

    default_meals = request.default_meals
    if not default_meals and request.use_default_meal_template:
        default_meals = [DefaultMealInput(**meal) for meal in DEFAULT_MEAL_TEMPLATES]

    try:
        plan = PlanningPlan(
            client_id=request.client_id,
            created_by_id=current_user.id,
            assigned_nutritionist_id=assigned_nutritionist_id,
            title=request.title,
            plan_type=request.plan_type,
            start_date=request.start_date,
            days_count=request.days_count,
            cycle_length=request.cycle_length,
            notes=request.notes,
            status=PlanningPlanStatus.DRAFT,
        )
        db.add(plan)
        db.flush()

        for day_index in range(request.days_count):
            current_date = request.start_date + timedelta(days=day_index) if request.start_date else None
            day = PlanningPlanDay(
                plan_id=plan.id,
                day_index=day_index + 1,
                day_name=current_date.strftime("%A") if current_date else f"Day {day_index + 1}",
                actual_date=current_date,
            )
            db.add(day)
            db.flush()

            for meal_order, meal in enumerate(default_meals or [], start=1):
                db.add(
                    PlanningPlanMeal(
                        day_id=day.id,
                        meal_name=meal.meal_name,
                        meal_type=meal.meal_type,
                        meal_time=meal.meal_time,
                        meal_order=meal_order,
                    )
                )

        db.commit()
        return serialize_plan(_require_visible_plan(db, plan.id, current_user), include_days=True, include_versions=True)
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create planning plan: {error}")


@router.get("/plans/{plan_id}")
def get_planning_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Get a V2 planning plan with nested days, meals, foods, and versions."""
    plan = _require_visible_plan(db, plan_id, current_user)
    return serialize_plan(plan, include_days=True, include_versions=True)


@router.patch("/plans/{plan_id}")
def update_planning_plan(
    plan_id: int,
    request: PlanningPlanUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update plan metadata."""
    plan = _require_visible_plan(db, plan_id, current_user)

    if request.title is not None:
        plan.title = request.title
    if request.start_date is not None:
        plan.start_date = request.start_date
    if request.cycle_length is not None:
        plan.cycle_length = request.cycle_length
    if request.notes is not None:
        plan.notes = request.notes

    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan_id, current_user), include_days=True, include_versions=True)


@router.post("/plans/{plan_id}/clone")
def clone_planning_plan(
    plan_id: int,
    request: PlanningPlanCloneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Clone a plan so template logic, cycle reuse, and multi-day structures stay intact."""
    source_plan = _require_visible_plan(db, plan_id, current_user)

    client = None
    if request.client_id:
        client = _require_visible_client(db, request.client_id, current_user)

    cloned_plan = PlanningPlan(
        client_id=request.client_id if request.client_id is not None else source_plan.client_id,
        created_by_id=current_user.id,
        assigned_nutritionist_id=(
            current_user.id
            if current_user.role.value == "nutritionist"
            else (client.assigned_nutritionist_id if client else source_plan.assigned_nutritionist_id)
        ),
        title=request.title,
        plan_type=request.plan_type or source_plan.plan_type,
        start_date=request.start_date if request.start_date is not None else source_plan.start_date,
        days_count=source_plan.days_count,
        cycle_length=source_plan.cycle_length,
        notes=request.notes if request.notes is not None else source_plan.notes,
        status=PlanningPlanStatus.DRAFT,
    )
    db.add(cloned_plan)
    db.flush()

    for rule in sorted(source_plan.rules, key=lambda item: item.id):
        db.add(_clone_rule(rule, plan_id=cloned_plan.id))
    for target in sorted(source_plan.nutrient_targets, key=lambda item: item.id):
        db.add(_clone_target(target, plan_id=cloned_plan.id))

    source_start = source_plan.start_date
    for day in sorted(source_plan.days, key=lambda item: item.day_index):
        actual_date = day.actual_date
        if request.start_date and source_start and day.actual_date:
            actual_date = request.start_date + (day.actual_date - source_start)

        cloned_day = PlanningPlanDay(
            plan_id=cloned_plan.id,
            day_index=day.day_index,
            day_name=day.day_name,
            actual_date=actual_date,
            template_group=day.template_group,
            notes=day.notes,
        )
        db.add(cloned_day)
        db.flush()

        for rule in sorted(day.rules, key=lambda item: item.id):
            db.add(_clone_rule(rule, plan_id=cloned_plan.id, day_id=cloned_day.id))
        for target in sorted(day.nutrient_targets, key=lambda item: item.id):
            db.add(_clone_target(target, plan_id=cloned_plan.id, day_id=cloned_day.id))

        for meal in sorted(day.meals, key=lambda item: item.meal_order):
            cloned_meal = PlanningPlanMeal(
                day_id=cloned_day.id,
                meal_name=meal.meal_name,
                meal_type=meal.meal_type,
                meal_time=meal.meal_time,
                meal_order=meal.meal_order,
                instructions=meal.instructions,
                target_notes=meal.target_notes,
            )
            db.add(cloned_meal)
            db.flush()

            for rule in sorted(meal.rules, key=lambda item: item.id):
                db.add(_clone_rule(rule, plan_id=cloned_plan.id, day_id=cloned_day.id, meal_id=cloned_meal.id))
            for target in sorted(meal.nutrient_targets, key=lambda item: item.id):
                db.add(_clone_target(target, plan_id=cloned_plan.id, day_id=cloned_day.id, meal_id=cloned_meal.id))

            if request.include_foods:
                for food in sorted(meal.foods, key=lambda item: (item.sort_order, item.id)):
                    db.add(
                        PlanningMealFood(
                            meal_id=cloned_meal.id,
                            food_id=food.food_id,
                            food_name=food.food_name,
                            food_code=food.food_code,
                            food_group_name=food.food_group_name,
                            portion_grams=food.portion_grams,
                            portion_description=food.portion_description,
                            household_measure=food.household_measure,
                            unit_label=food.unit_label,
                            preparation_state=food.preparation_state,
                            notes=food.notes,
                            sort_order=food.sort_order,
                            nutrient_snapshot=food.nutrient_snapshot,
                            calculated_nutrients=food.calculated_nutrients,
                        )
                    )

    db.commit()
    return serialize_plan(_require_visible_plan(db, cloned_plan.id, current_user), include_days=True, include_versions=True)


@router.post("/plans/{plan_id}/rules")
def add_plan_rule(
    plan_id: int,
    request: PlanningRuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a plan-wide structured rule."""
    plan = _require_visible_plan(db, plan_id, current_user)
    _validate_rule_payload(request.rule_type, request.severity)

    db.add(
        PlanningRule(
            client_id=plan.client_id,
            plan_id=plan.id,
            scope="plan",
            rule_type=request.rule_type.strip(),
            severity=request.severity.strip(),
            title=request.title.strip(),
            details=request.details,
            is_active=request.is_active,
        )
    )
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan.id, current_user), include_days=True, include_versions=True)


@router.post("/days/{day_id}/rules")
def add_day_rule(
    day_id: int,
    request: PlanningRuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a day-scoped structured rule."""
    day = _require_visible_day(db, day_id, current_user)
    _validate_rule_payload(request.rule_type, request.severity)

    db.add(
        PlanningRule(
            client_id=day.plan.client_id,
            plan_id=day.plan_id,
            day_id=day.id,
            scope="day",
            rule_type=request.rule_type.strip(),
            severity=request.severity.strip(),
            title=request.title.strip(),
            details=request.details,
            is_active=request.is_active,
        )
    )
    _mark_plan_dirty(day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, day.plan_id, current_user), include_days=True, include_versions=True)


@router.post("/meals/{meal_id}/rules")
def add_meal_rule(
    meal_id: int,
    request: PlanningRuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a meal-scoped structured rule."""
    meal = _require_visible_meal(db, meal_id, current_user)
    _validate_rule_payload(request.rule_type, request.severity)

    db.add(
        PlanningRule(
            client_id=meal.day.plan.client_id,
            plan_id=meal.day.plan_id,
            day_id=meal.day_id,
            meal_id=meal.id,
            scope="meal",
            rule_type=request.rule_type.strip(),
            severity=request.severity.strip(),
            title=request.title.strip(),
            details=request.details,
            is_active=request.is_active,
        )
    )
    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    request: PlanningRuleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update a structured planning rule."""
    rule = _require_visible_rule(db, rule_id, current_user)

    if request.rule_type is not None:
        rule.rule_type = request.rule_type.strip()
    if request.severity is not None:
        if request.severity.strip() not in RULE_SEVERITY_OPTIONS:
            raise HTTPException(status_code=400, detail=f"Invalid rule severity. Use one of: {', '.join(RULE_SEVERITY_OPTIONS)}")
        rule.severity = request.severity.strip()
    if request.title is not None:
        rule.title = request.title.strip()
    if request.details is not None:
        rule.details = request.details
    if request.is_active is not None:
        rule.is_active = request.is_active

    plan_id = rule.plan_id or (rule.day.plan_id if rule.day else rule.meal.day.plan_id)
    plan = _require_visible_plan(db, plan_id, current_user)
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan_id, current_user), include_days=True, include_versions=True)


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Delete a structured planning rule."""
    rule = _require_visible_rule(db, rule_id, current_user)
    plan_id = rule.plan_id or (rule.day.plan_id if rule.day else rule.meal.day.plan_id)
    plan = _require_visible_plan(db, plan_id, current_user)
    db.delete(rule)
    _mark_plan_dirty(plan)
    db.commit()
    return {"message": "Rule deleted", "plan_id": plan_id}


@router.post("/plans/{plan_id}/targets")
def add_plan_target(
    plan_id: int,
    request: PlanningTargetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a plan-wide nutrient target."""
    plan = _require_visible_plan(db, plan_id, current_user)
    _validate_target_payload(request.min_value, request.target_value, request.max_value)

    db.add(
        PlanningNutrientTarget(
            plan_id=plan.id,
            nutrient_code=request.nutrient_code.strip(),
            unit=request.unit,
            min_value=request.min_value,
            target_value=request.target_value,
            max_value=request.max_value,
        )
    )
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan.id, current_user), include_days=True, include_versions=True)


@router.post("/days/{day_id}/targets")
def add_day_target(
    day_id: int,
    request: PlanningTargetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a day-scoped nutrient target."""
    day = _require_visible_day(db, day_id, current_user)
    _validate_target_payload(request.min_value, request.target_value, request.max_value)

    db.add(
        PlanningNutrientTarget(
            plan_id=day.plan_id,
            day_id=day.id,
            nutrient_code=request.nutrient_code.strip(),
            unit=request.unit,
            min_value=request.min_value,
            target_value=request.target_value,
            max_value=request.max_value,
        )
    )
    _mark_plan_dirty(day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, day.plan_id, current_user), include_days=True, include_versions=True)


@router.post("/meals/{meal_id}/targets")
def add_meal_target(
    meal_id: int,
    request: PlanningTargetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a meal-scoped nutrient target."""
    meal = _require_visible_meal(db, meal_id, current_user)
    _validate_target_payload(request.min_value, request.target_value, request.max_value)

    db.add(
        PlanningNutrientTarget(
            plan_id=meal.day.plan_id,
            day_id=meal.day_id,
            meal_id=meal.id,
            nutrient_code=request.nutrient_code.strip(),
            unit=request.unit,
            min_value=request.min_value,
            target_value=request.target_value,
            max_value=request.max_value,
        )
    )
    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.patch("/targets/{target_id}")
def update_target(
    target_id: int,
    request: PlanningTargetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update a nutrient target."""
    target = _require_visible_target(db, target_id, current_user)

    min_value = request.min_value if request.min_value is not None else target.min_value
    target_value = request.target_value if request.target_value is not None else target.target_value
    max_value = request.max_value if request.max_value is not None else target.max_value
    _validate_target_payload(min_value, target_value, max_value)

    if request.nutrient_code is not None:
        target.nutrient_code = request.nutrient_code.strip()
    if request.unit is not None:
        target.unit = request.unit
    if request.min_value is not None:
        target.min_value = request.min_value
    if request.target_value is not None:
        target.target_value = request.target_value
    if request.max_value is not None:
        target.max_value = request.max_value

    plan_id = target.plan_id or (target.day.plan_id if target.day else target.meal.day.plan_id)
    plan = _require_visible_plan(db, plan_id, current_user)
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan_id, current_user), include_days=True, include_versions=True)


@router.delete("/targets/{target_id}")
def delete_target(
    target_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Delete a nutrient target."""
    target = _require_visible_target(db, target_id, current_user)
    plan_id = target.plan_id or (target.day.plan_id if target.day else target.meal.day.plan_id)
    plan = _require_visible_plan(db, plan_id, current_user)
    db.delete(target)
    _mark_plan_dirty(plan)
    db.commit()
    return {"message": "Target deleted", "plan_id": plan_id}


@router.post("/plans/{plan_id}/days")
def add_day_to_plan(
    plan_id: int,
    request: PlanningDayCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Append a day to the end of a plan."""
    plan = _require_visible_plan(db, plan_id, current_user)
    next_index = len(plan.days) + 1
    actual_date = request.actual_date
    if actual_date is None and plan.start_date:
        actual_date = plan.start_date + timedelta(days=next_index - 1)

    day = PlanningPlanDay(
        plan_id=plan.id,
        day_index=next_index,
        day_name=request.day_name or (actual_date.strftime("%A") if actual_date else f"Day {next_index}"),
        actual_date=actual_date,
        template_group=request.template_group,
        notes=request.notes,
    )
    db.add(day)
    plan.days_count = next_index
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan_id, current_user), include_days=True, include_versions=True)


@router.patch("/days/{day_id}")
def update_plan_day(
    day_id: int,
    request: PlanningDayUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update day-level metadata."""
    day = _require_visible_day(db, day_id, current_user)

    if request.day_name is not None:
        day.day_name = request.day_name
    if request.actual_date is not None:
        day.actual_date = request.actual_date
    if request.template_group is not None:
        day.template_group = request.template_group
    if request.notes is not None:
        day.notes = request.notes

    _mark_plan_dirty(day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, day.plan_id, current_user), include_days=True, include_versions=True)


@router.post("/days/{day_id}/duplicate")
def duplicate_plan_day(
    day_id: int,
    request: PlanningDayDuplicateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Duplicate a whole day including meals and meal foods."""
    day = _require_visible_day(db, day_id, current_user)
    plan = _require_visible_plan(db, day.plan_id, current_user)
    next_index = len(plan.days) + 1
    actual_date = request.actual_date
    if actual_date is None and plan.start_date:
        actual_date = plan.start_date + timedelta(days=next_index - 1)

    cloned_day = PlanningPlanDay(
        plan_id=plan.id,
        day_index=next_index,
        day_name=request.day_name or f"{day.day_name} Copy",
        actual_date=actual_date,
        template_group=request.template_group if request.template_group is not None else day.template_group,
        notes=day.notes,
    )
    db.add(cloned_day)
    db.flush()

    for rule in sorted(day.rules, key=lambda item: item.id):
        db.add(_clone_rule(rule, plan_id=plan.id, day_id=cloned_day.id))
    for target in sorted(day.nutrient_targets, key=lambda item: item.id):
        db.add(_clone_target(target, plan_id=plan.id, day_id=cloned_day.id))

    for meal in sorted(day.meals, key=lambda item: item.meal_order):
        cloned_meal = PlanningPlanMeal(
            day_id=cloned_day.id,
            meal_name=meal.meal_name,
            meal_type=meal.meal_type,
            meal_time=meal.meal_time,
            meal_order=meal.meal_order,
            instructions=meal.instructions,
            target_notes=meal.target_notes,
        )
        db.add(cloned_meal)
        db.flush()

        for rule in sorted(meal.rules, key=lambda item: item.id):
            db.add(_clone_rule(rule, plan_id=plan.id, day_id=cloned_day.id, meal_id=cloned_meal.id))
        for target in sorted(meal.nutrient_targets, key=lambda item: item.id):
            db.add(_clone_target(target, plan_id=plan.id, day_id=cloned_day.id, meal_id=cloned_meal.id))

        for food in sorted(meal.foods, key=lambda item: (item.sort_order, item.id)):
            db.add(
                PlanningMealFood(
                    meal_id=cloned_meal.id,
                    food_id=food.food_id,
                    food_name=food.food_name,
                    food_code=food.food_code,
                    food_group_name=food.food_group_name,
                    portion_grams=food.portion_grams,
                    portion_description=food.portion_description,
                    household_measure=food.household_measure,
                    unit_label=food.unit_label,
                    preparation_state=food.preparation_state,
                    notes=food.notes,
                    sort_order=food.sort_order,
                    nutrient_snapshot=food.nutrient_snapshot,
                    calculated_nutrients=food.calculated_nutrients,
                )
            )

    plan.days_count = next_index
    _mark_plan_dirty(plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, plan.id, current_user), include_days=True, include_versions=True)


@router.delete("/days/{day_id}")
def delete_plan_day(
    day_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Delete a day from a plan and renumber the remaining days."""
    day = _require_visible_day(db, day_id, current_user)
    plan = _require_visible_plan(db, day.plan_id, current_user)

    if len(plan.days) <= 1:
        raise HTTPException(status_code=400, detail="A plan must keep at least one day")

    db.delete(day)
    db.flush()

    refreshed_plan = _require_visible_plan(db, plan.id, current_user)
    _renumber_plan_days(refreshed_plan)
    refreshed_plan.days_count = len(refreshed_plan.days)
    _mark_plan_dirty(refreshed_plan)
    db.commit()
    return {"message": "Day deleted", "plan_id": refreshed_plan.id}


@router.post("/days/{day_id}/meals")
def add_meal_to_day(
    day_id: int,
    request: PlanningMealCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a meal to a V2 plan day."""
    day = _require_visible_day(db, day_id, current_user)
    next_order = (db.query(func.max(PlanningPlanMeal.meal_order)).filter(PlanningPlanMeal.day_id == day_id).scalar() or 0) + 1

    meal = PlanningPlanMeal(
        day_id=day_id,
        meal_name=request.meal_name,
        meal_type=request.meal_type,
        meal_time=request.meal_time,
        meal_order=next_order,
        instructions=request.instructions,
        target_notes=request.target_notes,
    )
    db.add(meal)
    _mark_plan_dirty(day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, day.plan_id, current_user), include_days=True, include_versions=True)


@router.patch("/meals/{meal_id}")
def update_plan_meal(
    meal_id: int,
    request: PlanningMealUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update meal metadata."""
    meal = _require_visible_meal(db, meal_id, current_user)

    if request.meal_name is not None:
        meal.meal_name = request.meal_name
    if request.meal_type is not None:
        meal.meal_type = request.meal_type
    if request.meal_time is not None:
        meal.meal_time = request.meal_time
    if request.meal_order is not None:
        meal.meal_order = request.meal_order
    if request.instructions is not None:
        meal.instructions = request.instructions
    if request.target_notes is not None:
        meal.target_notes = request.target_notes

    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.delete("/meals/{meal_id}")
def delete_plan_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Delete a meal from a day."""
    meal = _require_visible_meal(db, meal_id, current_user)
    plan_id = meal.day.plan_id
    db.delete(meal)
    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return {"message": "Meal deleted", "plan_id": plan_id}


@router.post("/meals/{meal_id}/foods")
def add_food_to_meal(
    meal_id: int,
    request: PlanningMealFoodCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a food snapshot into a V2 meal."""
    meal = _require_visible_meal(db, meal_id, current_user)
    food = (
        db.query(Food)
        .options(
            selectinload(Food.food_group),
            selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient),
            selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient_type_rel),
        )
        .filter(Food.id == request.food_id)
        .first()
    )
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    if not food.nutrients:
        raise HTTPException(status_code=400, detail="Food has no nutrient data")

    normalized_portion_grams = _normalize_portion_grams(request.portion_grams, request.unit_label)
    nutrient_snapshot = build_nutrient_snapshot(food.nutrients)
    calculated_nutrients = calculate_portion_nutrients(nutrient_snapshot, normalized_portion_grams)
    next_order = (db.query(func.max(PlanningMealFood.sort_order)).filter(PlanningMealFood.meal_id == meal_id).scalar() or 0) + 1

    meal_food = PlanningMealFood(
        meal_id=meal.id,
        food_id=food.id,
        food_name=food.name,
        food_code=food.code,
        food_group_name=food.food_group.name if food.food_group else None,
        portion_grams=normalized_portion_grams,
        portion_description=request.portion_description,
        household_measure=request.household_measure,
        unit_label=request.unit_label,
        preparation_state=request.preparation_state,
        notes=request.notes,
        sort_order=next_order,
        nutrient_snapshot=nutrient_snapshot,
        calculated_nutrients=calculated_nutrients,
    )
    db.add(meal_food)
    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.post("/meals/{meal_id}/custom-foods")
def add_custom_food_to_meal(
    meal_id: int,
    request: PlanningCustomMealFoodCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Add a recipe/composite food item by entering its nutrient profile directly."""
    meal = _require_visible_meal(db, meal_id, current_user)
    normalized_portion_grams = _normalize_portion_grams(request.portion_grams, request.unit_label)
    nutrient_snapshot = _build_custom_snapshot(request.nutrients_per_100g)
    calculated_nutrients = calculate_portion_nutrients(nutrient_snapshot, normalized_portion_grams)
    next_order = (db.query(func.max(PlanningMealFood.sort_order)).filter(PlanningMealFood.meal_id == meal_id).scalar() or 0) + 1

    meal_food = PlanningMealFood(
        meal_id=meal.id,
        food_id=None,
        food_name=request.food_name,
        food_code=None,
        food_group_name=request.food_group_name or "Custom recipe",
        portion_grams=normalized_portion_grams,
        portion_description=request.portion_description,
        household_measure=request.household_measure,
        unit_label=request.unit_label,
        preparation_state=request.preparation_state,
        notes=request.notes,
        sort_order=next_order,
        nutrient_snapshot=nutrient_snapshot,
        calculated_nutrients=calculated_nutrients,
    )
    db.add(meal_food)
    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.get("/meal-foods/{meal_food_id}/suggestions")
def get_meal_food_suggestions(
    meal_food_id: int,
    same_group_only: bool = Query(True),
    limit: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Suggest rule-aware substitutions for a selected meal food."""
    meal_food = _require_visible_meal_food(db, meal_food_id, current_user)
    meal = _require_visible_meal(db, meal_food.meal_id, current_user)
    plan = _require_visible_plan(db, meal.day.plan_id, current_user)
    effective_rules, effective_targets = get_effective_context(plan, meal.day, meal)

    current_food_group_id = None
    if meal_food.food_id:
        current_food_group_id = db.query(Food.food_group_id).filter(Food.id == meal_food.food_id).scalar()

    query = db.query(Food).options(
        selectinload(Food.food_group),
        selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient),
        selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient_type_rel),
    )

    if meal_food.food_id:
        query = query.filter(Food.id != meal_food.food_id)
    if same_group_only and current_food_group_id:
        query = query.filter(Food.food_group_id == current_food_group_id)

    candidate_foods = query.order_by(Food.name.asc()).limit(80).all()
    current_summary = aggregate_nutrients_from_foods([meal_food])
    current_exchange_category = infer_exchange_category(meal_food.calculated_nutrients or {}, meal_food.food_group_name)
    suggestions = []

    for candidate in candidate_foods:
        if not candidate.nutrients:
            continue

        candidate_item = _build_food_item_for_portion(candidate, meal_food.portion_grams)
        compatibility = evaluate_food_against_rules(candidate.name, candidate.food_group.name if candidate.food_group else None, effective_rules)
        if compatibility["hard_blocked"]:
            continue

        same_group = False
        if current_food_group_id is not None:
            same_group = candidate.food_group_id == current_food_group_id
        elif meal_food.food_group_name:
            same_group = (candidate.food_group.name if candidate.food_group else None) == meal_food.food_group_name

        exchange_category = infer_exchange_category(
            candidate_item["calculated_nutrients"] or {},
            candidate.food_group.name if candidate.food_group else None,
        )
        same_exchange = exchange_category == current_exchange_category

        deltas = build_nutrient_deltas(meal_food.calculated_nutrients or {}, candidate_item["calculated_nutrients"] or {})
        candidate_item["similarity_score"] = score_substitution(
            meal_food.calculated_nutrients or {},
            candidate_item["calculated_nutrients"] or {},
            same_group=same_group,
            same_exchange=same_exchange,
        )
        candidate_item["similarity_summary"] = build_similarity_summary(deltas)
        candidate_item["same_group"] = same_group
        candidate_item["exchange_category"] = exchange_category
        candidate_item["same_exchange"] = same_exchange
        candidate_item["compatibility"] = compatibility
        candidate_item["nutrient_deltas"] = deltas
        candidate_item["target_preview"] = _build_food_target_preview(candidate_item, effective_targets)
        suggestions.append(candidate_item)

    suggestions.sort(key=lambda item: (item["similarity_score"], 1 if item["same_group"] else 0), reverse=True)
    trimmed = suggestions[:limit]

    return {
        "current_food": {
            "id": meal_food.id,
            "food_id": meal_food.food_id,
            "food_name": meal_food.food_name,
            "food_group_name": meal_food.food_group_name,
            "portion_grams": meal_food.portion_grams,
            "portion_description": meal_food.portion_description,
            "summary": current_summary,
            "exchange_category": current_exchange_category,
        },
        "rule_context": {
            "meal_id": meal.id,
            "meal_name": meal.meal_name,
            "hard_rules_count": len([rule for rule in effective_rules if rule.severity == "hard"]),
            "rules_count": len(effective_rules),
            "targets_count": len(effective_targets),
        },
        "data": trimmed,
        "total": len(trimmed),
    }


@router.post("/meal-foods/{meal_food_id}/replace")
def replace_meal_food(
    meal_food_id: int,
    request: PlanningMealFoodReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Replace a selected meal food with another food while keeping the meal slot intact."""
    meal_food = _require_visible_meal_food(db, meal_food_id, current_user)
    meal = _require_visible_meal(db, meal_food.meal_id, current_user)
    plan = _require_visible_plan(db, meal.day.plan_id, current_user)

    replacement_food = (
        db.query(Food)
        .options(
            selectinload(Food.food_group),
            selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient),
            selectinload(Food.nutrients).selectinload(FoodNutrient.nutrient_type_rel),
        )
        .filter(Food.id == request.food_id)
        .first()
    )
    if not replacement_food:
        raise HTTPException(status_code=404, detail="Replacement food not found")
    if not replacement_food.nutrients:
        raise HTTPException(status_code=400, detail="Replacement food has no nutrient data")

    effective_rules, _effective_targets = get_effective_context(plan, meal.day, meal)
    compatibility = evaluate_food_against_rules(
        replacement_food.name,
        replacement_food.food_group.name if replacement_food.food_group else None,
        effective_rules,
    )
    if compatibility["hard_blocked"]:
        blocked_titles = ", ".join(item["title"] for item in compatibility["blocked_by"][:4])
        raise HTTPException(status_code=400, detail=f"Replacement food violates blocking rules: {blocked_titles}")

    portion_unit = request.unit_label if request.unit_label is not None else meal_food.unit_label
    portion_grams = (
        _normalize_portion_grams(request.portion_grams, portion_unit)
        if request.portion_grams is not None
        else meal_food.portion_grams
    )
    nutrient_snapshot = build_nutrient_snapshot(replacement_food.nutrients)
    calculated_nutrients = calculate_portion_nutrients(nutrient_snapshot, portion_grams)
    previous_food_name = meal_food.food_name

    replacement_log = build_replacement_note(previous_food_name, replacement_food.name, request.replacement_reason)
    notes_parts = []
    if meal_food.notes:
        notes_parts.append(meal_food.notes.strip())
    if request.notes:
        notes_parts.append(request.notes.strip())
    notes_parts.append(replacement_log)

    meal_food.food_id = replacement_food.id
    meal_food.food_name = replacement_food.name
    meal_food.food_code = replacement_food.code
    meal_food.food_group_name = replacement_food.food_group.name if replacement_food.food_group else None
    meal_food.portion_grams = portion_grams
    meal_food.portion_description = request.portion_description if request.portion_description is not None else meal_food.portion_description
    meal_food.household_measure = request.household_measure if request.household_measure is not None else meal_food.household_measure
    meal_food.unit_label = request.unit_label if request.unit_label is not None else meal_food.unit_label
    meal_food.preparation_state = request.preparation_state if request.preparation_state is not None else meal_food.preparation_state
    meal_food.notes = "\n".join(part for part in notes_parts if part)
    meal_food.nutrient_snapshot = nutrient_snapshot
    meal_food.calculated_nutrients = calculated_nutrients

    _mark_plan_dirty(meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.patch("/meal-foods/{meal_food_id}")
def update_meal_food(
    meal_food_id: int,
    request: PlanningMealFoodUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Update portion and serving details for a selected food."""
    meal_food = _require_visible_meal_food(db, meal_food_id, current_user)

    if request.portion_description is not None:
        meal_food.portion_description = request.portion_description
    if request.household_measure is not None:
        meal_food.household_measure = request.household_measure
    if request.unit_label is not None:
        meal_food.unit_label = request.unit_label
    if request.preparation_state is not None:
        meal_food.preparation_state = request.preparation_state
    if request.notes is not None:
        meal_food.notes = request.notes
    if request.portion_grams is not None:
        unit_label = request.unit_label if request.unit_label is not None else meal_food.unit_label
        meal_food.portion_grams = _normalize_portion_grams(request.portion_grams, unit_label)
        meal_food.calculated_nutrients = calculate_portion_nutrients(meal_food.nutrient_snapshot or {}, meal_food.portion_grams)

    _mark_plan_dirty(meal_food.meal.day.plan)
    db.commit()
    return serialize_plan(_require_visible_plan(db, meal_food.meal.day.plan_id, current_user), include_days=True, include_versions=True)


@router.delete("/meal-foods/{meal_food_id}")
def delete_meal_food(
    meal_food_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Remove a selected food from a meal."""
    meal_food = _require_visible_meal_food(db, meal_food_id, current_user)
    plan_id = meal_food.meal.day.plan_id
    db.delete(meal_food)
    _mark_plan_dirty(meal_food.meal.day.plan)
    db.commit()
    return {"message": "Food removed from meal", "plan_id": plan_id}


@router.get("/plans/{plan_id}/report")
def get_planning_plan_report(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Return a full report payload for preview and download."""
    plan = _require_visible_plan(db, plan_id, current_user)
    report = serialize_plan(plan, include_days=True, include_versions=True)
    report["report_generated_at"] = datetime.now(timezone.utc).isoformat()
    report["report_title"] = plan.title
    report["key_nutrient_labels"] = KEY_NUTRIENT_LABELS
    return report


@router.post("/plans/{plan_id}/versions/finalize")
def finalize_planning_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_of_roles(["admin", "manager", "nutritionist"]))
):
    """Create an immutable version snapshot for a V2 plan."""
    plan = _require_visible_plan(db, plan_id, current_user)
    nested_plan = serialize_plan(plan, include_days=True, include_versions=True)

    if not nested_plan["days"]:
        raise HTTPException(status_code=400, detail="Cannot finalize a plan without any days")

    empty_meals = []
    total_foods = 0
    for day in nested_plan["days"]:
        if not day["meals"]:
            empty_meals.append(f"Day {day['day_index']} has no meals")
            continue
        for meal in day["meals"]:
            food_count = meal["summary"]["foods_count"]
            total_foods += food_count
            if food_count == 0:
                empty_meals.append(f"Day {day['day_index']} - {meal['meal_name']} has no foods")

    if total_foods == 0:
        raise HTTPException(status_code=400, detail="Cannot finalize a plan without any selected foods")
    if empty_meals:
        raise HTTPException(status_code=400, detail="Cannot finalize plan because some meals are empty: " + "; ".join(empty_meals))
    if (nested_plan.get("effective_validation") or {}).get("blockers_count", 0) > 0:
        blocker_messages = [
            check.get("message")
            for check in (nested_plan.get("effective_validation") or {}).get("checks", [])
            if check.get("severity") == "blocker"
        ]
        raise HTTPException(
            status_code=400,
            detail="Cannot finalize plan because blocking rule violations were detected: " + "; ".join(blocker_messages[:6]),
        )

    version_number = (db.query(func.max(PlanningPlanVersion.version_number)).filter(PlanningPlanVersion.plan_id == plan_id).scalar() or 0) + 1
    snapshot = nested_plan
    snapshot["finalized_by"] = current_user.full_name or current_user.username

    try:
        version = PlanningPlanVersion(
            plan_id=plan_id,
            version_number=version_number,
            status=PlanningPlanStatus.FINALIZED,
            snapshot_json=snapshot,
            finalized_at=datetime.now(timezone.utc),
            finalized_by_id=current_user.id,
        )
        plan.status = PlanningPlanStatus.FINALIZED
        plan.updated_at = datetime.now(timezone.utc)
        db.add(version)
        db.commit()
        db.refresh(version)
        return {
            "plan_id": plan_id,
            "version_id": version.id,
            "version_number": version.version_number,
            "status": version.status.value if hasattr(version.status, "value") else str(version.status),
            "finalized_at": version.finalized_at,
        }
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to finalize planning plan: {error}")
