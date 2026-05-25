"""
Password Reset Token Utility
Handles secure token generation, validation, and expiry for password resets
"""

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Token expiry time in seconds (1 hour)
PASSWORD_RESET_TOKEN_EXPIRY = 3600


def generate_reset_token() -> str:
    """
    Generate a secure random token for password reset
    
    Returns:
        str: A secure random token (URL-safe)
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256
    Never store plain tokens in database - always store hashed versions
    
    Args:
        token: Plain text token
    
    Returns:
        str: Hashed token (hex)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_password_reset_token(user_id: int, expiry_hours: int = 1) -> Tuple[str, datetime]:
    """
    Create a password reset token and calculate its expiry time
    
    Args:
        user_id: The user ID this token is for
        expiry_hours: How many hours until token expires (default 1)
    
    Returns:
        Tuple[str, datetime]: (token, expires_at)
    """
    token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
    
    logger.info(f"Generated password reset token for user {user_id}, expires at {expires_at}")
    return token, expires_at


def verify_reset_token(
    plain_token: str, 
    stored_hash: str,
    expires_at: datetime,
    already_used: bool
) -> Tuple[bool, Optional[str]]:
    """
    Verify a password reset token
    
    Args:
        plain_token: The plain text token from user (from email link)
        stored_hash: The hashed token stored in database
        expires_at: The expiry datetime stored in database
        already_used: Whether token has already been used
    
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
                                     - (True, None) if valid
                                     - (False, error_msg) if invalid
    """
    
    # Check if token has been used
    if already_used:
        return False, "This password reset link has already been used"
    
    # Check if token has expired
    if datetime.now(timezone.utc) > expires_at:
        return False, "This password reset link has expired. Please request a new one."
    
    # Verify token hash matches
    token_hash = hash_token(plain_token)
    if token_hash != stored_hash:
        return False, "Invalid password reset token"
    
    return True, None


def is_token_expired(expires_at: datetime) -> bool:
    """
    Check if a token has expired
    
    Args:
        expires_at: The expiry datetime
    
    Returns:
        bool: True if expired, False otherwise
    """
    return datetime.now(timezone.utc) > expires_at


def get_token_expiry_hours() -> int:
    """Get token expiry time in hours"""
    return PASSWORD_RESET_TOKEN_EXPIRY // 3600
