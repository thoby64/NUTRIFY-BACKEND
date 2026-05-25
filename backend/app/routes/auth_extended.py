"""
Extended Authentication Routes
Forgot password and password reset endpoints
Public endpoints (no authentication required for forgot/reset flow)
"""

from fastapi import APIRouter, HTTPException, Query, status, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta, timezone
import logging

from app.core.database import get_db
from app.core.config import get_settings
from app.core.auth import hash_password, get_current_user
from app.models.models import User, PasswordResetToken
from app.utils.email_service import get_email_service
from app.utils.password_reset import (
    generate_reset_token, 
    hash_token, 
    verify_reset_token,
    PASSWORD_RESET_TOKEN_EXPIRY
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ============ PYDANTIC SCHEMAS ============

class ForgotPasswordRequest(BaseModel):
    """User requests password reset via email"""
    email: str = Field(..., min_length=5, max_length=255)


class ForgotPasswordResponse(BaseModel):
    """Response to forgot password request"""
    message: str
    email_sent: bool


class ResetPasswordRequest(BaseModel):
    """User submits new password with reset token"""
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


class ResetPasswordResponse(BaseModel):
    """Response to password reset"""
    message: str
    success: bool


class ChangePasswordRequest(BaseModel):
    """Authenticated user changes their own password"""
    current_password: str = Field(..., min_length=8)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


class ChangePasswordResponse(BaseModel):
    """Response to password change"""
    message: str
    success: bool


# ============ FORGOT PASSWORD ENDPOINTS ============

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Initiate password reset flow via email
    User provides email, we send reset link if email exists
    
    Security note: We don't reveal if email exists (generic response)
    """
    
    # Find user by email
    user = db.query(User).filter(User.email == request.email).first()
    
    # Always return success (don't reveal if email exists)
    # But only send email if user found
    if user and user.is_active:
        try:
            # Generate reset token
            plain_token, expires_at = _create_password_reset_token(user, db)
            
            # Get email service
            email_service = get_email_service()
            
            # Get settings for frontend URL
            settings = get_settings()
            
            # Build reset link (frontend URL from settings)
            reset_link = f"{settings.frontend_url}/reset-password?token={plain_token}"
            
            # Send email
            email_sent = email_service.send_password_reset_email(
                recipient_email=user.email,
                username=user.username,
                reset_link=reset_link,
                expires_in_hours=1
            )
            
            if email_sent:
                logger.info(f"Password reset email sent to {user.email}")
            else:
                logger.warning(f"Failed to send password reset email to {user.email}")
        
        except Exception as e:
            logger.error(f"Error in forgot password: {str(e)}")
    
    # Always return success message (for security)
    return ForgotPasswordResponse(
        message="If an account with this email exists, a password reset link has been sent",
        email_sent=True
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Reset password using token from email
    Validates token, checks expiry, and updates password
    """
    
    # Validate passwords match
    if request.new_password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )
    
    # Find reset token by hash
    token_hash = hash_token(request.token)
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token_hash
    ).first()
    
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password reset token"
        )
    
    # Verify token
    is_valid, error_msg = verify_reset_token(
        plain_token=request.token,
        stored_hash=reset_token.token,
        expires_at=reset_token.expires_at,
        already_used=reset_token.used_at is not None
    )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    try:
        # Get user
        user = db.query(User).filter(User.id == reset_token.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update password
        user.password_hash = hash_password(request.new_password)
        user.updated_at = datetime.now(timezone.utc)
        
        # Mark token as used
        reset_token.used_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Password reset successful for user {user.username}")
        
        return ResetPasswordResponse(
            message="Password has been reset successfully. You can now login with your new password.",
            success=True
        )
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error resetting password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error resetting password"
        )


# ============ CHANGE PASSWORD ENDPOINTS ============

@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Authenticated user changes their own password
    Requires current password verification
    """
    
    # Validate passwords match
    if request.new_password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )
    
    # Verify current password
    from app.core.auth import verify_password
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    
    # New password must be different from current
    if verify_password(request.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )
    
    try:
        # Update password
        current_user.password_hash = hash_password(request.new_password)
        current_user.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"User {current_user.username} changed their password")
        
        return ChangePasswordResponse(
            message="Password changed successfully",
            success=True
        )
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error changing password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error changing password"
        )


# ============ HELPER FUNCTIONS ============

def _create_password_reset_token(user: User, db: Session) -> tuple:
    """
    Create and store a password reset token for a user
    
    Returns:
        tuple: (plain_token, expires_at)
    """
    # Clean up any existing unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at == None
    ).delete()
    db.commit()
    
    # Generate new token
    plain_token = generate_reset_token()
    token_hash = hash_token(plain_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Store in database
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_hash,
        expires_at=expires_at
    )
    
    db.add(reset_token)
    db.commit()
    
    return plain_token, expires_at
