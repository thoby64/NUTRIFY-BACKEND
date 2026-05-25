"""
Manager Routes
Manager-only endpoints for managing nutritionists and viewing team analytics
Managers can manage nutritionists and view their own + nutritionists' analytics
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import logging

from app.core.database import get_db
from app.core.auth import require_manager
from app.models.models import User, UserRole, NutritionPlan, Meal, MealFood
from app.core.auth import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/manager", tags=["manager"])


# ============ PYDANTIC SCHEMAS ============

class NutritionistCreate(BaseModel):
    """Schema for creating a new nutritionist"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = Field(None, max_length=100)
    is_active: bool = True


class NutritionistUpdate(BaseModel):
    """Schema for updating an existing nutritionist"""
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    full_name: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class NutritionistResponse(BaseModel):
    """Schema for nutritionist response"""
    id: int
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]
    updated_at: datetime
    
    class Config:
        from_attributes = True


class NutritionistListResponse(BaseModel):
    """Schema for paginated nutritionist list"""
    total: int
    skip: int
    limit: int
    nutritionists: List[NutritionistResponse]


class PasswordReset(BaseModel):
    """Schema for password reset"""
    new_password: str = Field(..., min_length=8)


class NutritionistDataCheckResponse(BaseModel):
    """Schema for checking if nutritionist has associated data"""
    user_id: int
    username: str
    has_plans: bool
    plans_count: int
    total_meals: int
    can_delete: bool
    reason: Optional[str] = None


class ManagerAnalytics(BaseModel):
    """Manager's own analytics"""
    total_plans_created: int
    total_meals_created: int
    total_foods_used: int


class NutritionistAnalytics(BaseModel):
    """Analytics for a specific nutritionist"""
    nutritionist_username: str
    nutritionist_id: int
    total_plans: int
    total_meals: int
    total_foods_used: int
    average_foods_per_meal: Optional[float] = None


# ============ NUTRITIONIST MANAGEMENT ENDPOINTS ============

@router.get("/nutritionists", response_model=NutritionistListResponse)
def list_nutritionists(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """
    List all nutritionists managed by this manager
    Manager only endpoint
    """
    
    # Build base query - only get nutritionists
    query = db.query(User).filter(User.role == UserRole.NUTRITIONIST)
    
    # Filter by search term (username or email)
    if search:
        search_filter = or_(
            User.username.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%"),
            User.full_name.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    # Include or exclude inactive users
    if not include_inactive:
        query = query.filter(User.is_active == True)
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    nutritionists = query.offset(skip).limit(limit).all()
    
    return NutritionistListResponse(
        total=total,
        skip=skip,
        limit=limit,
        nutritionists=nutritionists
    )


@router.get("/nutritionists/{nutritionist_id}", response_model=NutritionistResponse)
def get_nutritionist(
    nutritionist_id: int,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Get a specific nutritionist by ID"""
    nutritionist = db.query(User).filter(
        and_(User.id == nutritionist_id, User.role == UserRole.NUTRITIONIST)
    ).first()
    
    if not nutritionist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutritionist not found"
        )
    
    return nutritionist


@router.get("/nutritionists/{nutritionist_id}/has-data", response_model=NutritionistDataCheckResponse)
def check_nutritionist_has_data(
    nutritionist_id: int,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Check if a nutritionist has associated plans or data"""
    nutritionist = db.query(User).filter(
        and_(User.id == nutritionist_id, User.role == UserRole.NUTRITIONIST)
    ).first()
    
    if not nutritionist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutritionist not found"
        )
    
    # Count plans created by nutritionist
    plans_count = db.query(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == nutritionist_id
    ).count()
    
    # Count total meals in those plans
    total_meals = db.query(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == nutritionist_id
    ).count()
    
    can_delete = plans_count == 0
    reason = None
    
    if not can_delete:
        reason = f"Nutritionist has {plans_count} plan(s) with {total_meals} meal(s)"
    
    return NutritionistDataCheckResponse(
        user_id=nutritionist_id,
        username=nutritionist.username,
        has_plans=plans_count > 0,
        plans_count=plans_count,
        total_meals=total_meals,
        can_delete=can_delete,
        reason=reason
    )


@router.post("/nutritionists", response_model=NutritionistResponse, status_code=status.HTTP_201_CREATED)
def create_nutritionist(
    nutritionist_data: NutritionistCreate,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Create a new nutritionist"""
    
    # Check if username already exists
    existing_user = db.query(User).filter(User.username == nutritionist_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )
    
    # Check if email already exists
    existing_email = db.query(User).filter(User.email == nutritionist_data.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists"
        )
    
    try:
        # Create new nutritionist
        new_nutritionist = User(
            username=nutritionist_data.username,
            email=nutritionist_data.email,
            password_hash=hash_password(nutritionist_data.password),
            full_name=nutritionist_data.full_name,
            role=UserRole.NUTRITIONIST,
            is_active=nutritionist_data.is_active,
            created_by_id=manager_user.id
        )
        
        db.add(new_nutritionist)
        db.commit()
        db.refresh(new_nutritionist)
        
        logger.info(f"Manager {manager_user.username} created new nutritionist {new_nutritionist.username}")
        
        return new_nutritionist
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating nutritionist: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error creating nutritionist: {str(e)}"
        )


@router.put("/nutritionists/{nutritionist_id}", response_model=NutritionistResponse)
def update_nutritionist(
    nutritionist_id: int,
    nutritionist_data: NutritionistUpdate,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Update a nutritionist's information"""
    
    nutritionist = db.query(User).filter(
        and_(User.id == nutritionist_id, User.role == UserRole.NUTRITIONIST)
    ).first()
    
    if not nutritionist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutritionist not found"
        )
    
    try:
        # Update email if provided
        if nutritionist_data.email:
            existing_email = db.query(User).filter(
                and_(User.email == nutritionist_data.email, User.id != nutritionist_id)
            ).first()
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already exists"
                )
            nutritionist.email = nutritionist_data.email
        
        # Update other fields
        if nutritionist_data.full_name is not None:
            nutritionist.full_name = nutritionist_data.full_name
        
        if nutritionist_data.is_active is not None:
            nutritionist.is_active = nutritionist_data.is_active
        
        nutritionist.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(nutritionist)
        
        logger.info(f"Manager {manager_user.username} updated nutritionist {nutritionist.username}")
        
        return nutritionist
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating nutritionist: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error updating nutritionist: {str(e)}"
        )


@router.delete("/nutritionists/{nutritionist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_nutritionist(
    nutritionist_id: int,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """
    Delete a nutritionist and all associated plans/meals
    Cascade deletes all plans and meals created by this nutritionist
    """
    
    nutritionist = db.query(User).filter(
        and_(User.id == nutritionist_id, User.role == UserRole.NUTRITIONIST)
    ).first()
    
    if not nutritionist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutritionist not found"
        )
    
    try:
        # Delete nutritionist (cascade will handle plans and meals)
        db.delete(nutritionist)
        db.commit()
        
        logger.info(f"Manager {manager_user.username} deleted nutritionist {nutritionist.username}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting nutritionist: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error deleting nutritionist: {str(e)}"
        )


# ============ ANALYTICS ENDPOINTS ============

@router.get("/analytics", response_model=ManagerAnalytics)
def get_manager_analytics(
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Get manager's own analytics (if manager creates plans)"""
    
    # Count plans created by manager
    plans_count = db.query(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == manager_user.id
    ).count()
    
    # Count total meals
    meals_count = db.query(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == manager_user.id
    ).count()
    
    # Count unique foods used
    foods_count = db.query(MealFood).select_from(MealFood).join(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == manager_user.id
    ).count()
    
    return ManagerAnalytics(
        total_plans_created=plans_count,
        total_meals_created=meals_count,
        total_foods_used=foods_count
    )


@router.get("/analytics/nutritionist/{nutritionist_id}", response_model=NutritionistAnalytics)
def get_nutritionist_analytics(
    nutritionist_id: int,
    db: Session = Depends(get_db),
    manager_user: User = Depends(require_manager)
):
    """Get analytics for a specific nutritionist"""
    
    nutritionist = db.query(User).filter(
        and_(User.id == nutritionist_id, User.role == UserRole.NUTRITIONIST)
    ).first()
    
    if not nutritionist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutritionist not found"
        )
    
    # Count plans
    plans_count = db.query(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == nutritionist_id
    ).count()
    
    # Count meals
    meals_count = db.query(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == nutritionist_id
    ).count()
    
    # Count foods
    foods_count = db.query(MealFood).select_from(MealFood).join(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == nutritionist_id
    ).count()
    
    # Calculate average
    average_foods_per_meal = None
    if meals_count > 0:
        average_foods_per_meal = round(foods_count / meals_count, 2)
    
    return NutritionistAnalytics(
        nutritionist_username=nutritionist.username,
        nutritionist_id=nutritionist_id,
        total_plans=plans_count,
        total_meals=meals_count,
        total_foods_used=foods_count,
        average_foods_per_meal=average_foods_per_meal
    )
