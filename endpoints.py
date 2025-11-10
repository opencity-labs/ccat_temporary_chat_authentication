"""
FastAPI endpoints for session management.

This module contains all the REST API endpoints for creating, managing,
and monitoring temporary sessions.
"""

import jwt
from datetime import datetime

from pytz import utc
from fastapi import HTTPException, Request

from cat.mad_hatter.decorators import endpoint
from cat.env import get_env
from cat.log import log

from .auth_handler import (
    SessionCreateResponse, 
    SessionStatusResponse, 
    temp_auth_handler
)
from .utils import (
    session_registry,
    rate_limit_tracker,
    check_rate_limit,
    cleanup_expired_sessions,
    cleanup_session_episodic_memory,
    get_plugin_settings
)


@endpoint.post("/sessions/create", tags=["Session Manager"])
def create_temporary_session(request: Request) -> SessionCreateResponse:
    """
    Create a temporary session for anonymous users.
    
    Returns a JWT token that can be used for WebSocket authentication.
    Sessions automatically expire after the configured duration.
    """
    
    # Get client IP for rate limiting
    client_ip = request.client.host if hasattr(request, 'client') else "unknown"
    # Check rate limits
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded. Too many session requests."
        )
    
    # Clean up expired sessions
    cleanup_expired_sessions()
    
    # Create new temporary session
    session_data = temp_auth_handler.issue_temporary_jwt()
    
    # Build WebSocket URL
    websocket_url = f"/ws?token={session_data['session_token']}"
    
    return SessionCreateResponse(
        session_token=session_data["session_token"],
        websocket_url=websocket_url,
        user_id=session_data["user_id"],
        expires_at=session_data["expires_at"],
        session_duration_minutes=session_data["session_duration_minutes"]
    )


@endpoint.get("/sessions/{session_id}/status", tags=["Session Manager"])
def get_session_status(session_id: str) -> SessionStatusResponse:
    """
    Check the status of a temporary session.
    
    Returns whether the session is valid and when it expires.
    """
    
    # Clean up expired sessions first
    cleanup_expired_sessions()
    
    # Check if session exists
    if session_id not in session_registry:
        return SessionStatusResponse(
            user_id=session_id,
            is_valid=False
        )
    
    session_data = session_registry[session_id]
    current_time = datetime.now(utc)
    
    # Calculate remaining time
    remaining_time = session_data["expires_at"] - current_time
    remaining_minutes = max(0, int(remaining_time.total_seconds() / 60))
    
    return SessionStatusResponse(
        user_id=session_id,
        is_valid=True,
        expires_at=session_data["expires_at"].isoformat(),
        remaining_minutes=remaining_minutes
    )


@endpoint.delete("/sessions/{session_id}", tags=["Session Manager"])
def cleanup_session(session_id: str, request: Request) -> dict:
    """
    Manually cleanup a temporary session.
    
    This can be called by the session owner to immediately invalidate their session.
    Accepts both JWT token authentication and direct session validation.
    Also cleans up associated episodic memories.
    """
    
    # Try to authenticate with JWT token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
    
    # Validate the token if provided
    authenticated_user_id = None
    if token:
        try:
            payload = jwt.decode(
                token,
                get_env("CCAT_JWT_SECRET"),
                algorithms=[get_env("CCAT_JWT_ALGORITHM")],
            )
            authenticated_user_id = payload.get("sub")
            
            # Check if token is for this session and hasn't expired
            exp_timestamp = payload.get("exp")
            if (authenticated_user_id == session_id and 
                exp_timestamp and 
                datetime.now(utc).timestamp() <= exp_timestamp):
                # Valid token for this session
                pass
            else:
                authenticated_user_id = None
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            authenticated_user_id = None
    
    # Allow cleanup if:
    # 1. Valid JWT token for this session, OR
    # 2. Session exists in registry (for cleanup on disconnect)
    if authenticated_user_id == session_id or session_id in session_registry:
        # Clean up episodic memory first
        try:
            from cat.looking_glass.cheshire_cat import CheshireCat
            
            # Create a temporary cat instance for memory cleanup
            ccat = CheshireCat()
            memory_cleaned = cleanup_session_episodic_memory(session_id, ccat)
            settings = get_plugin_settings()
            if settings.verbose_logging:
                log.info(f"Memory cleanup result for session {session_id}: {memory_cleaned}")
        except Exception as e:
            log.error(f"Error during memory cleanup for session {session_id}: {e}")
        
        # Remove from registry
        if session_id in session_registry:
            del session_registry[session_id]
            settings = get_plugin_settings()
            if settings.verbose_logging:
                log.info(f"Manual cleanup of session: {session_id}")
            return {
                "message": "Session cleaned up successfully", 
                "session_id": session_id,
                "memory_cleaned": True
            }
        else:
            return {
                "message": "Session not found or already expired", 
                "session_id": session_id,
                "memory_cleaned": False
            }
    else:
        raise HTTPException(
            status_code=403,
            detail="Invalid authentication for session cleanup"
        )


@endpoint.get("/sessions/stats", tags=["Session Manager"])
def get_session_stats() -> dict:
    """
    Get statistics about temporary sessions.
    
    This endpoint is open and provides general statistics without exposing sensitive data.
    """
    
    # Clean up expired sessions first
    expired_count = cleanup_expired_sessions()
    
    current_time = datetime.now(utc)
    active_sessions = len(session_registry)
    
    # Calculate average session age
    if active_sessions > 0:
        total_age_minutes = sum(
            (current_time - session_data["created_at"]).total_seconds() / 60
            for session_data in session_registry.values()
        )
        avg_age_minutes = total_age_minutes / active_sessions
    else:
        avg_age_minutes = 0
    
    return {
        "active_sessions": active_sessions,
        "expired_sessions_cleaned": expired_count,
        "average_session_age_minutes": round(avg_age_minutes, 2),
        "rate_limit_ips": len(rate_limit_tracker)
    }
