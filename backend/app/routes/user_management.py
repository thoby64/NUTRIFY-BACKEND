"""
User Management Routes  
Admin-only endpoints for managing all users (create, read, update, delete)
Only accessible by users with admin role
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import logging

from app.core.database import get_db
from app.core.auth import require_admin, get_current_user
from app.models.models import User, UserRole, NutritionPlan, Meal
from app.core.auth import hash_password, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ============ PYDANTIC SCHEMAS ============

class UserCreate(BaseModel):
    """Schema for creating a new user"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = Field(None, max_length=100)
    role: UserRole = Field(default=UserRole.NUTRITIONIST)
    is_active: bool = True


class UserUpdate(BaseModel):
    """Schema for updating an existing user"""
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """Schema for user response"""
    id: int
    username: str
    email: str
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]
    updated_at: datetime
    created_by_id: Optional[int]
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Schema for paginated user list"""
    total: int
    skip: int
    limit: int
    users: List[UserResponse]


class PasswordReset(BaseModel):
    """Schema for admin password reset"""
    new_password: str = Field(..., min_length=8)


class UserDataCheckResponse(BaseModel):
    """Schema for checking if user has associated data"""
    user_id: int
    username: str
    has_plans: bool
    plans_count: int
    total_meals: int
    can_delete: bool
    reason: Optional[str] = None


# ============ USER MANAGEMENT ENDPOINTS ============

@router.get("/users", response_model=UserListResponse)
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    role: Optional[UserRole] = None,
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    List all users with optional filtering
    Admin only endpoint
    """
    
    # Build base query
    query = db.query(User)
    
    # Filter by role if specified
    if role:
        query = query.filter(User.role == role)
    
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
    users = query.offset(skip).limit(limit).all()
    
    return UserListResponse(
        total=total,
        skip=skip,
        limit=limit,
        users=users
    )


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Get a specific user by ID"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user


@router.get("/users/{user_id}/has-data", response_model=UserDataCheckResponse)
def check_user_has_data(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Check if a user has associated plans or data
    Used to determine if user can be safely deleted
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Count plans created by user
    plans_count = db.query(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == user_id
    ).count()
    
    # Count total meals in those plans
    total_meals = db.query(Meal).join(NutritionPlan).filter(
        NutritionPlan.nutritionist_id == user_id
    ).count()
    
    can_delete = plans_count == 0
    reason = None
    
    if not can_delete:
        reason = f"User has {plans_count} plan(s) with {total_meals} meal(s)"
    
    return UserDataCheckResponse(
        user_id=user_id,
        username=user.username,
        has_plans=plans_count > 0,
        plans_count=plans_count,
        total_meals=total_meals,
        can_delete=can_delete,
        reason=reason
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Create a new user (any role: admin, manager, nutritionist)
    Admin only endpoint
    """
    
    # Check if username already exists
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )
    
    # Check if email already exists
    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists"
        )
    
    try:
        # Create new user
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name,
            role=user_data.role,
            is_active=user_data.is_active,
            created_by_id=admin_user.id
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Admin {admin_user.username} created new user {new_user.username} with role {new_user.role}")
        
        return new_user
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error creating user: {str(e)}"
        )


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Update a user's information
    Admin only endpoint
    """
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    try:
        # Update email if provided
        if user_data.email:
            # Check if new email is already taken (by another user)
            existing_email = db.query(User).filter(
                and_(User.email == user_data.email, User.id != user_id)
            ).first()
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already exists"
                )
            user.email = user_data.email
        
        # Update other fields
        if user_data.full_name is not None:
            user.full_name = user_data.full_name
        
        if user_data.role is not None:
            user.role = user_data.role
        
        if user_data.is_active is not None:
            user.is_active = user_data.is_active
        
        user.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"Admin {admin_user.username} updated user {user.username}")
        
        return user
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error updating user: {str(e)}"
        )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Delete a user and all associated data (plans, meals, etc.)
    Admin only endpoint
    
    Note: For nutritionists, cascade deletes all their plans and meals
    """
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent deleting self
    if user.id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself"
        )
    
    try:
        # Delete user (cascade will handle related data)
        db.delete(user)
        db.commit()
        
        logger.info(f"Admin {admin_user.username} deleted user {user.username}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error deleting user: {str(e)}"
        )


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_200_OK)
def reset_user_password(
    user_id: int,
    password_data: PasswordReset,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Admin-initiated password reset for a user
    Sets a new password without requiring the old password
    """
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent resetting own password via this endpoint
    # (user should use their own change password endpoint)
    if user.id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the change password endpoint for your own password"
        )
    
    try:
        user.password_hash = hash_password(password_data.new_password)
        user.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Admin {admin_user.username} reset password for user {user.username}")
        
        return {"message": f"Password reset for user {user.username}"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error resetting password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error resetting password"
        )
