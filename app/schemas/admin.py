"""User authentication schemas"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """User role enum"""
    ADMIN = "admin"
    NUTRITIONIST = "nutritionist"
    MANAGER = "manager"
    EDITOR = "editor"


class UserBase(BaseModel):
    """Base user schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=255)
    full_name: Optional[str] = None
    role: UserRole = UserRole.EDITOR


class UserCreate(UserBase):
    """Create user schema"""
    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    """Update user schema"""
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    """User response schema"""
    email: str
    id: int
    is_active: bool
    role: UserRole
    created_at: datetime
    last_login: Optional[datetime] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Login request"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response"""
    access_token: str
    token_type: str
    user: UserResponse
