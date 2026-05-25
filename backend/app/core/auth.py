"""Authentication utilities"""
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import get_settings

# Password hashing with argon2
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# JWT settings
settings = get_settings()
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes


def hash_password(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ============ Role-Based Access Control ============

def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Extract and verify user from JWT token"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Import here to avoid circular imports
    from app.models.models import User
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    return user


def require_admin(user = Depends(get_current_user)):
    """Dependency to require admin role"""
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation",
        )
    return user


def require_manager(user = Depends(get_current_user)):
    """Dependency to require manager role"""
    if user.role.value != "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager role required for this operation",
        )
    return user


def require_nutritionist(user = Depends(get_current_user)):
    """Dependency to require nutritionist role"""
    if user.role.value != "nutritionist":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nutritionist role required for this operation",
        )
    return user


def require_manager_or_admin(user = Depends(get_current_user)):
    """Dependency to require manager or admin role"""
    if user.role.value not in ["manager", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or Admin role required for this operation",
        )
    return user


def require_any_of_roles(allowed_roles: list):
    """
    Factory function to create a dependency that requires one of the specified roles
    
    Usage:
        @router.get("/endpoint")
        def get_endpoint(user = Depends(require_any_of_roles(["admin", "manager"]))):
            ...
    """
    def check_role(user = Depends(get_current_user)):
        if user.role.value not in allowed_roles:
            allowed_str = ", ".join(allowed_roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these roles required: {allowed_str}",
            )
        return user
    
    return check_role


def require_not_same_user(target_user_id: int, current_user = Depends(get_current_user)):
    """
    Verify that the current user is not the target user
    Useful for operations like "edit another user" or "delete another user"
    
    Returns:
        current_user: The authenticated user
        
    Raises:
        HTTPException: If trying to modify self
    """
    if current_user.id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot perform this operation on yourself",
        )
    return current_user
