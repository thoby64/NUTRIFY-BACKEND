# Pydantic BaseModel must be imported before use
from pydantic import BaseModel
# List plans endpoint (GET /api/v1/plans)
from sqlalchemy import or_, and_, func

from app.models.models import User

from fastapi import Query, APIRouter, Depends 
from typing import Dict, Any, Optional, List
from app.core.database import get_db
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.utils.condition_parser import (
    ConditionParseError,
    validate_conditions,
    parse_conditions,
    filter_foods_by_conditions,
)
from app.core.auth import get_current_user
from app.core.auth import require_manager_or_admin
from app.models.models import NutritionPlan
from datetime import datetime, timezone
from app.models.models import Meal, Food, FoodNutrient, FoodGroup, MealFood
from app.utils.planning_v2 import infer_default_nutrient_unit

class MealResponse(BaseModel):
    """Single meal response"""
    id: int
    plan_id: int
    meal_name: str
    meal_order: int
    condition_string: Optional[str] = None
    total_energy_kc: Optional[float] = None
    total_procnt: Optional[float] = None
    total_fat: Optional[float] = None
    total_chocdf: Optional[float] = None
    total_fiber: Optional[float] = None
    created_at: datetime


class PlanResponse(BaseModel):
    """Nutrition plan response"""
    id: int
    plan_name: str
    plan_date: datetime
    daily_targets: Optional[str] = None
    status: str
    notes: Optional[str] = None
    meals: Optional[List[MealResponse]] = None
    created_at: datetime

router = APIRouter(prefix="/api/v1", tags=["meal-planning"])

@router.get("/plans", response_model=Dict[str, Any])
def list_plans(
    nutritionist_id: Optional[int] = Query(None, description="Filter by nutritionist ID"),
    status: Optional[str] = Query(None, description="Filter by plan status (draft, finalized, archived)"),
    created_after: Optional[str] = Query(None, description="Filter by creation date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search by plan name or nutritionist username"),
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """List nutrition plans with optional filters (admin/manager only)"""
    query = db.query(NutritionPlan)
    if nutritionist_id:
        query = query.filter(NutritionPlan.nutritionist_id == nutritionist_id)
    if status:
        query = query.filter(NutritionPlan.status.ilike(status))
    if created_after:
        try:
            dt = datetime.strptime(created_after, "%Y-%m-%d")
            query = query.filter(NutritionPlan.created_at >= dt)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid created_after date format. Use YYYY-MM-DD.")
    if search:
        # Join with User for nutritionist username
        query = query.join(User, NutritionPlan.nutritionist_id == User.id)
        search_term = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(NutritionPlan.plan_name).like(search_term),
                func.lower(User.username).like(search_term)
            )
        )
    query = query.order_by(NutritionPlan.created_at.desc())
    plans = query.all()
    # Serialize plans (minimal fields for listing)
    result = []
    for plan in plans:
        nutritionist = plan.nutritionist
        result.append({
            "id": plan.id,
            "plan_name": plan.plan_name,
            "nutritionist_id": plan.nutritionist_id,
            "nutritionist_username": nutritionist.username if nutritionist else None,
            "status": plan.status,
            "created_at": plan.created_at,
        })
    return {"data": result, "total": len(result)}
"""
Meal Planning Routes
API endpoints for creating and managing nutrition plans and meals
All endpoints require admin role
"""



# ============ PYDANTIC SCHEMAS ============

class CreatePlanRequest(BaseModel):
    """Request to create a new nutrition plan"""
    plan_name: str
    daily_targets: Optional[str] = None
    notes: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    """Request to update an existing nutrition plan"""
    plan_name: Optional[str] = None
    daily_targets: Optional[str] = None
    notes: Optional[str] = None


class CreateMealRequest(BaseModel):
    """Request to create a meal in a plan"""
    meal_name: str
    meal_order: int
    condition_string: str


class UpdateMealRequest(BaseModel):
    """Request to update an existing meal"""
    meal_name: Optional[str] = None
    meal_order: Optional[int] = None
    condition_string: Optional[str] = None


class NutrientValue(BaseModel):
    """Single nutrient value"""
    value: float
    unit: str


class NutrientSnapshot(BaseModel):
    """Complete nutrient snapshot for a food"""
    macronutrients: Optional[Dict[str, NutrientValue]] = None
    vitamins: Optional[Dict[str, NutrientValue]] = None
    minerals: Optional[Dict[str, NutrientValue]] = None
    amino_acids: Optional[Dict[str, NutrientValue]] = None


class AddFoodToMealRequest(BaseModel):
    """Request to add a food to a meal"""
    food_id: int
    portion_grams: float
    portion_description: Optional[str] = None


# ============ ENDPOINTS ============

@router.post("/plans", response_model=PlanResponse)
def create_plan(
    request: CreatePlanRequest,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Create a new nutrition plan - requires manager or admin role"""
    
    try:
        plan = NutritionPlan(
            nutritionist_id=user.id,
            plan_name=request.plan_name,
            plan_date=datetime.now(timezone.utc),
            daily_targets=request.daily_targets,
            notes=request.notes,
            status="draft"
        )
        
        db.add(plan)
        db.commit()
        db.refresh(plan)
        
        return plan
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create plan: {str(e)}")


@router.get("/plans/{plan_id}", response_model=PlanResponse)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Get a nutrition plan with all meals - requires manager or admin role"""
    
    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
def update_plan(
    plan_id: int,
    request: UpdatePlanRequest,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Update a nutrition plan's basic details - requires manager or admin role"""

    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if request.plan_name is not None:
        plan.plan_name = request.plan_name
    if request.daily_targets is not None:
        plan.daily_targets = request.daily_targets
    if request.notes is not None:
        plan.notes = request.notes

    try:
        plan.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(plan)
        return plan
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to update plan: {str(e)}")


@router.get("/plans/{plan_id}/report")
def get_plan_report(
    plan_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Get a full plan report with meals and foods - requires manager or admin role"""

    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    meals = db.query(Meal).filter(Meal.plan_id == plan_id).order_by(Meal.meal_order.asc()).all()
    meals_data = []
    for meal in meals:
        meal_foods = db.query(MealFood).filter(MealFood.meal_id == meal.id).all()
        foods_data = []
        for meal_food in meal_foods:
            food_details = {
                "id": meal_food.food_id,
                "food_name": meal_food.food_name,
                "code": None,
                "food_group_name": meal_food.food_group_name,
                "description": None,
                "nutrient_snapshot": meal_food.nutrient_snapshot,
            }

            foods_data.append(
                {
                    "id": meal_food.id,
                    "food_id": meal_food.food_id,
                    "portion_grams": meal_food.portion_grams,
                    "portion_description": meal_food.portion_description,
                    "calculated_nutrients": meal_food.calculated_nutrients,
                    "food": food_details,
                }
            )

        meals_data.append(
            {
                "id": meal.id,
                "meal_name": meal.meal_name,
                "meal_order": meal.meal_order,
                "condition_string": meal.condition_string,
                "total_energy_kc": meal.total_energy_kc,
                "total_procnt": meal.total_procnt,
                "total_fat": meal.total_fat,
                "total_chocdf": meal.total_chocdf,
                "total_fiber": meal.total_fiber,
                "foods": foods_data,
            }
        )

    return {
        "plan": {
            "id": plan.id,
            "plan_name": plan.plan_name,
            "plan_date": plan.plan_date,
            "daily_targets": plan.daily_targets,
            "status": plan.status,
            "notes": plan.notes,
            "created_at": plan.created_at,
            "nutritionist_id": plan.nutritionist_id,
        },
        "meals": meals_data,
    }


@router.post("/plans/{plan_id}/meals", response_model=MealResponse)
def create_meal(
    plan_id: int,
    request: CreateMealRequest,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Create a meal in a plan - requires manager or admin role"""
    
    # Check plan exists
    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Validate conditions
    is_valid, error_msg = validate_conditions(request.condition_string, db=db)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid conditions: {error_msg}")
    
    try:
        meal = Meal(
            plan_id=plan_id,
            meal_name=request.meal_name,
            meal_order=request.meal_order,
            condition_string=request.condition_string,
            total_energy_kc=0,
            total_procnt=0,
            total_fat=0,
            total_chocdf=0,
            total_fiber=0
        )
        
        db.add(meal)
        db.commit()
        db.refresh(meal)
        
        return meal
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create meal: {str(e)}")


@router.put("/meals/{meal_id}", response_model=MealResponse)
def update_meal(
    meal_id: int,
    request: UpdateMealRequest,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Update a meal - requires manager or admin role"""
    
    # Check meal exists
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    
    # Validate conditions if provided
    if request.condition_string:
        is_valid, error_msg = validate_conditions(request.condition_string, db=db)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {error_msg}")
    
    try:
        # Update fields if provided
        if request.meal_name is not None:
            meal.meal_name = request.meal_name
        if request.meal_order is not None:
            meal.meal_order = request.meal_order
        if request.condition_string is not None:
            meal.condition_string = request.condition_string
        
        meal.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(meal)
        
        return meal
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to update meal: {str(e)}")


@router.delete("/meals/{meal_id}", response_model=Dict[str, Any])
def delete_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Delete a meal - requires manager or admin role"""
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    try:
        db.delete(meal)
        db.commit()
        return {"message": "Meal deleted", "id": meal_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to delete meal: {str(e)}")


@router.get("/meals/{meal_id}/filter-foods")
def get_foods_for_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Get foods matching the meal's conditions - requires manager or admin role"""
    
    # Get meal
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    
    # Parse conditions
    try:
        conditions = parse_conditions(meal.condition_string, db=db)
    except ConditionParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid meal conditions: {str(e)}")
    
    # Filter foods
    try:
        matching_food_ids = filter_foods_by_conditions(db, conditions)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Filter failed: {str(e)}")
    
    # Get matching foods with their nutrient data
    foods = db.query(Food).filter(Food.id.in_(matching_food_ids)).all()
    
    result = []
    for food in foods:
        food_data = _get_food_details_with_nutrients(db, food)
        result.append(food_data)
    
    return {
        "total": len(result),
        "data": result
    }


@router.post("/meals/{meal_id}/add-food", response_model=Dict[str, Any])
def add_food_to_meal(
    meal_id: int,
    request: AddFoodToMealRequest,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Add a food to a meal with calculated nutrients - requires manager or admin role"""
    
    # Get meal
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    
    # Get food
    food = db.query(Food).filter(Food.id == request.food_id).first()
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    
    # Get all nutrients for this food
    food_nutrients = db.query(FoodNutrient).filter(
        FoodNutrient.food_id == food.id
    ).all()
    
    if not food_nutrients:
        raise HTTPException(status_code=400, detail="Food has no nutrient data")
    
    # Create nutrient snapshot and calculate for portion
    nutrient_snapshot = _build_nutrient_snapshot(db, food_nutrients)
    calculated_nutrients = _calculate_portion_nutrients(nutrient_snapshot, request.portion_grams)
    
    try:
        # Get food group info
        food_group = db.query(FoodGroup).filter(
            FoodGroup.id == food.food_group_id
        ).first()
        
        meal_food = MealFood(
            meal_id=meal_id,
            food_id=food.id,
            food_name=food.name,
            food_group_name=food_group.name if food_group else None,
            portion_grams=request.portion_grams,
            portion_description=request.portion_description,
            nutrient_snapshot=nutrient_snapshot,
            calculated_nutrients=calculated_nutrients
        )
        
        db.add(meal_food)
        db.flush()
        
        # Update meal totals
        _update_meal_totals(db, meal_id)
        
        db.commit()
        db.refresh(meal_food)
        
        return {
            "id": meal_food.id,
            "meal_id": meal_food.meal_id,
            "food_name": meal_food.food_name,
            "portion_grams": meal_food.portion_grams,
            "portion_description": meal_food.portion_description,
            "calculated_nutrients": meal_food.calculated_nutrients
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to add food: {str(e)}")


@router.delete("/meal-foods/{meal_food_id}")
def remove_food_from_meal(
    meal_food_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Remove a food from a meal - requires manager or admin role"""
    
    meal_food = db.query(MealFood).filter(MealFood.id == meal_food_id).first()
    if not meal_food:
        raise HTTPException(status_code=404, detail="Meal food not found")
    
    meal_id = meal_food.meal_id
    
    try:
        db.delete(meal_food)
        db.flush()
        
        # Update meal totals
        _update_meal_totals(db, meal_id)
        
        db.commit()
        
        return {"message": "Food removed from meal"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to remove food: {str(e)}")


@router.put("/plans/{plan_id}")
def finalize_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Finalize a plan (change status from draft to finalized) - requires manager or admin role"""
    
    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    try:
        plan.status = "finalized"
        plan.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(plan)
        
        return {
            "id": plan.id,
            "status": plan.status,
            "message": "Plan finalized successfully"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to finalize plan: {str(e)}")


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_manager_or_admin)
):
    """Delete a plan and all associated data - requires manager or admin role"""

    plan = db.query(NutritionPlan).filter(NutritionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    try:
        db.delete(plan)
        db.commit()
        return {"message": "Plan deleted", "id": plan_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to delete plan: {str(e)}")


# ============ HELPER FUNCTIONS ============

def _get_food_details_with_nutrients(db: Session, food: Food) -> Dict[str, Any]:
    """Get food with all nutrient details"""
    
    food_nutrients = db.query(FoodNutrient).filter(
        FoodNutrient.food_id == food.id
    ).all()
    
    food_group = db.query(FoodGroup).filter(
        FoodGroup.id == food.food_group_id
    ).first()
    
    nutrient_snapshot = _build_nutrient_snapshot(db, food_nutrients)
    
    return {
        "id": food.id,
        "name": food.name,
        "code": food.code,
        "food_group": food_group.name if food_group else None,
        "description": food.description,
        "nutrient_snapshot": nutrient_snapshot
    }


def _build_nutrient_snapshot(db: Session, food_nutrients: List[FoodNutrient]) -> Dict[str, Any]:
    """Build nutrient snapshot from FoodNutrient records, grouped by category"""
    
    snapshot = {
        "macronutrients": {},
        "vitamins": {},
        "minerals": {},
        "amino_acids": {}
    }
    
    for fn in food_nutrients:
        nutrient = fn.nutrient
        nutrient_type = fn.nutrient_type_rel
        
        nutrient_data = {
            "value": fn.value or 0,
            "unit": nutrient.unit or infer_default_nutrient_unit(nutrient.name)
        }
        
        # Categorize by nutrient type
        category = _get_nutrient_category(nutrient_type.name if nutrient_type else "")
        
        if category in snapshot:
            snapshot[category][nutrient.name] = nutrient_data
    
    return snapshot


def _get_nutrient_category(nutrient_type_name: str) -> str:
    """Determine category of nutrient"""
    
    name_lower = nutrient_type_name.lower() if nutrient_type_name else ""
    
    if "amino" in name_lower:
        return "amino_acids"
    elif "vitamin" in name_lower:
        return "vitamins"
    elif "mineral" in name_lower:
        return "minerals"
    else:
        return "macronutrients"


def _calculate_portion_nutrients(
    nutrient_snapshot: Dict[str, Any],
    portion_grams: float
) -> Dict[str, float]:
    """Calculate nutrients for a specific portion"""
    
    # Convert from per 100g to requested portion amount
    multiplier = portion_grams / 100.0
    
    calculated = {}
    
    for category, nutrients in nutrient_snapshot.items():
        for nutrient_name, nutrient_data in nutrients.items():
            value = nutrient_data.get("value", 0) * multiplier
            calculated[nutrient_name] = round(value, 2)
    
    return calculated


def _update_meal_totals(db: Session, meal_id: int):
    """Recalculate meal totals from all foods in the meal"""
    
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        return
    
    meal_foods = db.query(MealFood).filter(MealFood.meal_id == meal_id).all()
    
    # Initialize totals
    totals = {
        "energy_kc": 0,
        "procnt": 0,
        "fat": 0,
        "chocdf": 0,
        "fiber": 0
    }
    
    # Sum nutrients from all foods
    for meal_food in meal_foods:
        calculated = meal_food.calculated_nutrients or {}
        
        totals["energy_kc"] += calculated.get("ENERGY_KC", 0)
        totals["procnt"] += calculated.get("PROCNT", 0)
        totals["fat"] += calculated.get("FAT", 0)
        totals["chocdf"] += calculated.get("CHOCDF", 0)
        totals["fiber"] += calculated.get("FIBTG", 0)
    
    # Update meal
    meal.total_energy_kc = round(totals["energy_kc"], 2)
    meal.total_procnt = round(totals["procnt"], 2)
    meal.total_fat = round(totals["fat"], 2)
    meal.total_chocdf = round(totals["chocdf"], 2)
    meal.total_fiber = round(totals["fiber"], 2)
