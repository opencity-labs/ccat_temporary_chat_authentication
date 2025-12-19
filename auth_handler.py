"""
Authentication handler for temporary sessions.

This module contains the TemporarySessionAuthHandler class and related authentication
logic for managing JWT-based temporary sessions for anonymous users.
"""

import uuid
import jwt
import json
from datetime import datetime, timedelta
from typing import Type

from pydantic import BaseModel, ConfigDict
from pytz import utc

from cat.auth.permissions import (
    AuthPermission, 
    AuthResource, 
    AuthUserInfo, 
    get_base_permissions
)
from cat.factory.custom_auth_handler import BaseAuthHandler
from cat.factory.auth_handler import AuthHandlerConfig
from cat.env import get_env
from cat.log import log

from .utils import session_registry, get_plugin_settings


# Pydantic models for request/response
class SessionCreateResponse(BaseModel):
    """Response model for session creation"""
    session_token: str
    websocket_url: str
    user_id: str
    expires_at: str
    session_duration_minutes: int


class SessionStatusResponse(BaseModel):
    """Response model for session status"""
    user_id: str
    is_valid: bool
    expires_at: str = None
    remaining_minutes: int = None





class TemporarySessionAuthHandler(BaseAuthHandler):
    """Custom auth handler for temporary sessions"""
    
    def authorize_user_from_credential(
        self,
        protocol: str,
        credential: str,
        auth_resource: AuthResource,
        auth_permission: AuthPermission,
        user_id: str = "user",
    ) -> AuthUserInfo | None:
        """Main entry point for credential validation"""
        if not credential:
            return None
            
        # Check if it's a JWT token
        if credential.startswith('eyJ'):  # JWT tokens start with 'eyJ'
            return self.authorize_user_from_jwt(credential, auth_resource, auth_permission)
        else:
            # Not a JWT, delegate to key auth (which we don't support for temp sessions)
            return self.authorize_user_from_key(protocol, user_id, credential, auth_resource, auth_permission)
    
    def authorize_user_from_jwt(
        self, 
        token: str, 
        auth_resource: AuthResource, 
        auth_permission: AuthPermission
    ) -> AuthUserInfo | None:
        """Authorize temporary session JWT tokens"""
        try:
            # Decode the JWT
            payload = jwt.decode(
                token,
                get_env("CCAT_JWT_SECRET"),
                algorithms=[get_env("CCAT_JWT_ALGORITHM")],
            )
            
            # Check if this is a temporary session token
            user_id = payload.get("sub")
            settings = get_plugin_settings()
            if not user_id or not user_id.startswith(settings['session_prefix']):
                return None  # Not a temporary session token
            
            # Verify the token hasn't expired
            exp_timestamp = payload.get("exp")
            if not exp_timestamp or datetime.now(utc).timestamp() > exp_timestamp:
                log.info(json.dumps({
                    "component": "ccat_temporary_chat_authentication",
                    "event": "token_expired",
                    "data": {"user_id": user_id}
                }))
                # Clean up expired session from registry
                if user_id in session_registry:
                    del session_registry[user_id]
                return None
            
            # Check if session is still registered
            if user_id not in session_registry:
                # Try to recover session from JWT token if it's still valid
                # This handles cases where the registry was cleared but the JWT is still valid
                try:
                    created_at = datetime.fromtimestamp(payload.get("iat", datetime.now(utc).timestamp()), tz=utc)
                    expires_at = datetime.fromtimestamp(exp_timestamp, tz=utc)
                    
                    # Recreate session in registry
                    session_registry[user_id] = {
                        "created_at": created_at,
                        "expires_at": expires_at,
                        "last_activity": datetime.now(utc),
                        "token": token,
                        "connection_active": True
                    }
                    
                    log.info(json.dumps({
                        "component": "ccat_temporary_chat_authentication",
                        "event": "session_recovered",
                        "data": {"user_id": user_id}
                    }))
                        
                except Exception as e: 
                    log.error(json.dumps({
                        "component": "ccat_temporary_chat_authentication",
                        "event": "session_recovery_failed",
                        "data": {"user_id": user_id, "error": str(e)}
                    }))
                    return None
            
            # Update last activity to keep session alive during conversation
            session_registry[user_id]["last_activity"] = datetime.now(utc)
            session_registry[user_id]["connection_active"] = True
            
            # Create AuthUserInfo for temporary user
            # IMPORTANT: Cat framework uses user_data.name as user_id (see stray_cat.py line 61)
            # So we must set both id and name to the session ID for consistency
            log.info(json.dumps({
                "component": "ccat_temporary_chat_authentication",
                "event": "auth_user_info_created",
                "data": {"user_id": user_id}
            }))
            return AuthUserInfo(
                id=user_id,  # This is the session ID with SESSION_PREFIX
                name=user_id,  # Cat framework uses this as user_id, so set it to session ID too
                permissions=get_base_permissions(),  # Minimal permissions
                extra={
                    "session_type": "temporary", 
                    "created_at": payload.get("iat"),
                    "expires_at": exp_timestamp,
                    "display_name": f"Anonymous_{user_id.replace(settings['session_prefix'], '')[:8]}"
                }
            )
            
        except jwt.ExpiredSignatureError:
            log.info(json.dumps({
                "component": "ccat_temporary_chat_authentication",
                "event": "jwt_expired",
                "data": {}
            }))
            return None
        except jwt.InvalidTokenError as e:
            log.info(json.dumps({
                "component": "ccat_temporary_chat_authentication",
                "event": "jwt_invalid",
                "data": {"error": str(e)}
            }))
            return None
        except Exception as e:
            log.error(json.dumps({
                "component": "ccat_temporary_chat_authentication",
                "event": "jwt_validation_error",
                "data": {"error": str(e)}
            }))
            return None
    
    def authorize_user_from_key(
        self, 
        protocol: str,
        user_id: str,
        api_key: str,
        auth_resource: AuthResource,
        auth_permission: AuthPermission
    ) -> AuthUserInfo | None:
        """Temporary sessions don't support API key auth"""
        return None
    
    def issue_temporary_jwt(self, session_duration_minutes: int = None) -> dict:
        """Issue a temporary JWT token for anonymous session"""
        settings = get_plugin_settings()
        
        if session_duration_minutes is None:
            session_duration_minutes = settings['default_session_duration_minutes']
        
        # Generate unique session ID
        session_id = f"{settings['session_prefix']}{uuid.uuid4().hex}"
        
        # Calculate expiration
        expires_at = datetime.now(utc) + timedelta(minutes=session_duration_minutes)
        
        # Create JWT payload
        jwt_payload = {
            "sub": session_id,
            "iat": datetime.now(utc).timestamp(),
            "exp": expires_at.timestamp(),
            "session_type": "temporary",
            "permissions": get_base_permissions()
        }
        
        # Generate JWT token
        token = jwt.encode(
            jwt_payload,
            get_env("CCAT_JWT_SECRET"),
            algorithm=get_env("CCAT_JWT_ALGORITHM")
        )
        
        # Register session
        session_registry[session_id] = {
            "created_at": datetime.now(utc),
            "expires_at": expires_at,
            "last_activity": datetime.now(utc),
            "token": token,
            "connection_active": False
        }
        
        log.info(json.dumps({
            "component": "ccat_temporary_chat_authentication",
            "event": "session_created",
            "data": {"session_id": session_id}
        }))
        
        return {
            "session_token": token,
            "user_id": session_id,
            "expires_at": expires_at.isoformat(),
            "session_duration_minutes": session_duration_minutes
        }


# Auth Handler Configuration Class
class TemporarySessionAuthConfig(AuthHandlerConfig):
    _pyclass: Type = TemporarySessionAuthHandler

    model_config = ConfigDict(
        json_schema_extra={
            "humanReadableName": "Temporary Session Auth Handler",
            "description": "Provides temporary JWT authentication for anonymous users with automatic session cleanup.",
            "link": "",
        }
    )


# Initialize the temporary session auth handler
temp_auth_handler = TemporarySessionAuthHandler()
