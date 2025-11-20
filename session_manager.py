"""
Session Manager Plugin for Cheshire Cat

This plugin provides temporary session management for anonymous users.
It creates short-lived JWT tokens for public website visitors who want to chat
without registering. Sessions automatically expire and clean up after themselves.

Features:
- Temporary JWT token generation
- Automatic session cleanup on WebSocket disconnect
- Configurable session duration
- Memory isolation per temporary user
- Rate limiting for session creation

Plugin Structure:
- session_manager.py: Main plugin file with hooks
- auth_handler.py: Authentication handler and JWT logic
- endpoints.py: FastAPI REST endpoints
- utils.py: Utility functions and session management
- settings.py: Plugin configuration
"""

from datetime import datetime

from pytz import utc
from cat.mad_hatter.decorators import hook
from cat.log import log

# Import from plugin modules
from .auth_handler import TemporarySessionAuthConfig
from .utils import (
    session_registry,
    is_temporary_session,
    cleanup_expired_sessions,
    cleanup_all_temporary_episodic_memories,
    get_plugin_settings
)
from .endpoints import *  # This registers all the endpoints


@hook(priority=1)
def before_cat_reads_message(user_message_json, cat):
    """
    Update session activity for temporary sessions.
    Let the message pass through normally - we handle special cases in agent_fast_reply.
    """
    # Update session activity for temporary sessions
    if is_temporary_session(cat.user_id):
        if cat.user_id in session_registry:
            session_registry[cat.user_id]["last_activity"] = datetime.now(utc)
    
    # Pass message through unchanged
    return user_message_json


@hook(priority=1)
def before_cat_sends_message(message, cat):
    """
    Update last activity timestamp for temporary sessions and clean up unwanted episodic memories.
    
    This helps track session usage and removes any episodic memories that shouldn't be stored.
    """
    settings = get_plugin_settings()
    
    # Check if this is a temporary session
    if is_temporary_session(cat.user_id):
        if cat.user_id in session_registry:
            session_registry[cat.user_id]["last_activity"] = datetime.now(utc)
            if settings['verbose_logging']:
                log.info(f"Session {cat.user_id}: About to send message, session active")
        
        # Clean up unwanted episodic memories if episodic memory is disabled for temporary sessions
        if not settings['episodic_memory_for_tmp']:
            try:
                # Remove any episodic memories with our skip markers or from this session
                episodic_collection = cat.memory.vectors.episodic
                
                # Delete points with skip_storage marker
                episodic_collection.delete_points_by_metadata_filter({
                    "skip_storage": True,
                    "source": cat.user_id
                })
                
                # Also delete any regular episodic memories from this temporary session
                # that might have been stored during this message processing
                episodic_collection.delete_points_by_metadata_filter({
                    "source": cat.user_id,
                    "session_type": "temporary"
                })
                
                if settings['verbose_logging']:
                    log.info(f"Session {cat.user_id}: Cleaned up episodic memories for temporary session")
                    
            except Exception as e:
                log.error(f"Session {cat.user_id}: Error cleaning episodic memories: {e}")
    
    if settings['verbose_logging']:
        log.info(f"Session {cat.user_id}: Sending message type: {type(message)}")
    
    # Let the message pass through unchanged - the Cat framework handles the format
    return message


@hook(priority=1)  
def after_cat_sends_message(message, cat):
    """
    Handle any issues after sending messages and ensure session stays active.
    Also ensure proper message cleanup.
    """
    settings = get_plugin_settings()
    
    # Keep temporary sessions active after sending messages
    if is_temporary_session(cat.user_id):
        if cat.user_id in session_registry:
            session_registry[cat.user_id]["last_activity"] = datetime.now(utc)
            if settings['verbose_logging']:
                log.info(f"Session {cat.user_id}: Message sent successfully, session still active")
    
    if settings['verbose_logging']:
        log.info(f"Session {cat.user_id}: After sending message, WebSocket should remain open")
    
    return message


@hook(priority=1)
def before_cat_recalls_episodic_memories(episodic_recall_config, cat):
    """
    Ensure temporary sessions only recall their own memories and handle empty queries.
    
    This adds an extra layer of isolation for temporary sessions.
    """
    settings = get_plugin_settings()
    if settings['verbose_logging']:
        log.warning(f"Session {cat.user_id}: Configuring episodic memory recall")
    
    # Check if this is a temporary session
    if is_temporary_session(cat.user_id):
        if settings['verbose_logging']:
            log.warning(f"Session {cat.user_id}: Configuring episodic memory recall for temporary session")
        # Only recall memories from this specific temporary session
        if "metadata" not in episodic_recall_config:
            episodic_recall_config["metadata"] = {}
        # Use the user_id (which is now the session ID) for memory isolation
        episodic_recall_config["metadata"]["source"] = cat.user_id
        episodic_recall_config["metadata"]["session_type"] = "temporary"
    
    return episodic_recall_config


@hook(priority=1)
def before_cat_stores_episodic_memory(doc, cat):
    """
    Add session metadata to episodic memories for temporary sessions.
    
    This helps with cleanup and identification of temporary session data.
    Note: Actual cleanup happens in before_cat_sends_message hook.
    """
    settings = get_plugin_settings()
    
    # Check if this is a temporary session
    if is_temporary_session(cat.user_id):
        if not hasattr(doc, 'metadata'):
            doc.metadata = {}
        doc.metadata["session_type"] = "temporary"
        doc.metadata["source"] = cat.user_id  # user_id is now the session ID
        
        # Add skip marker if episodic memory is disabled for temporary sessions
        if not settings['episodic_memory_for_tmp']:
            doc.metadata["skip_storage"] = True
            if settings['verbose_logging']:
                log.info(f"Session {cat.user_id}: Marking episodic memory for cleanup (will be removed before response)")
        
        if cat.user_id in session_registry:
            session_data = session_registry[cat.user_id]
            if "created_at" in session_data:
                doc.metadata["session_created"] = session_data["created_at"].isoformat()
    
    return doc


@hook(priority=1)
def factory_allowed_auth_handlers(auth_handlers, cat):
    """
    Register our temporary session auth handler with the Cat's factory system.
    """
    # Add our temporary session auth handler config to the available auth handlers
    auth_handlers.append(TemporarySessionAuthConfig)
    log.info("Session Manager Plugin: Registered TemporarySessionAuthHandler")
    
    return auth_handlers


@hook(priority=1)
def after_cat_bootstrap(cat):
    """
    Initialize session manager and configure the temporary auth handler.
    
    This hook runs once when the Cat starts up.
    """
    from cat.db import crud, models
    
    settings = cat.mad_hatter.get_plugin().load_settings()
    log.warning(settings)
    
    # Initialize session management
    log.info("Session Manager Plugin: Initializing temporary session management")
    log.info(f"Default session duration: {settings['default_session_duration_minutes']} minutes")
    
    # Clean up temporary episodic memories from previous runs
    # Set purge=True to clean ALL temporary memories, or purge=False to clean only orphaned ones
    if settings['cleanup_on_startup']:
        try:
            cleanup_count = cleanup_all_temporary_episodic_memories(cat, purge=True)
            log.info(f"Session Manager Plugin: Purged all {cleanup_count} temporary episodic memories on startup")
        except Exception as e:
            log.error(f"Session Manager Plugin: Error cleaning temporary episodic memories on startup: {e}")
    
    # Check if our auth handler is already selected and auto-configure if enabled
    if settings['auto_configure_auth']:
        try:
            selected_auth = crud.get_setting_by_name(name="auth_handler_selected")
            
            if selected_auth is None or selected_auth.get("value", {}).get("name") != "TemporarySessionAuthConfig":
                # Create the auth settings for our handler
                crud.upsert_setting_by_name(
                    models.Setting(
                        name="TemporarySessionAuthConfig", 
                        category="auth_handler_factory", 
                        value={}
                    )
                )
                
                # Set our handler as the selected one
                crud.upsert_setting_by_name(
                    models.Setting(
                        name="auth_handler_selected",
                        category="auth_handler_factory",
                        value={"name": "TemporarySessionAuthConfig"},
                    )
                )
                
                # Reload auth system to pick up our handler
                cat.load_auth()
                log.info("Session Manager Plugin: Configured Cat to use TemporarySessionAuthHandler")
            else:
                log.info("Session Manager Plugin: TemporarySessionAuthHandler already configured")
        except Exception as e:
            log.warning(f"Session Manager Plugin: Could not configure auth handler: {e}")
    
    return cat


@hook(priority=1) 
def agent_fast_reply(fast_reply, cat):
    """
    Handle fast replies for temporary sessions.
    """
    # Handle special message types for temporary sessions
    if is_temporary_session(cat.user_id):
        # Keep session active
        if cat.user_id in session_registry:
            session_registry[cat.user_id]["last_activity"] = datetime.now(utc)
            session_registry[cat.user_id]["connection_active"] = True
    
    return fast_reply


@hook(priority=1)
def before_cat_bootstrap(cat):
    """
    Handle session cleanup on Cat startup
    """
    log.info("Session Manager Plugin: Cleaning up sessions on startup")
    from .utils import rate_limit_tracker
    
    # Clean up expired sessions instead of clearing all
    try:
        expired_count = cleanup_expired_sessions()
        log.info(f"Session Manager Plugin: Cleaned up {expired_count} expired sessions on startup")
    except Exception as e:
        log.error(f"Session Manager Plugin: Error cleaning expired sessions on startup: {e}")
        # Fallback to clearing all sessions if cleanup fails
        session_registry.clear()
    
    # Clear rate limiting data on startup (this is safe to clear)
    rate_limit_tracker.clear()
    return cat