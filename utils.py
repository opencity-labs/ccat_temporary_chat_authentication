"""
Utility functions for session management.

This module contains helper functions for session validation, cleanup, rate limiting,
and memory management for the ccat_temporary_chat_authentication plugin.
"""

from datetime import datetime, timedelta
import json

from pytz import utc
from cat.log import log


# In-memory storage for rate limiting and session tracking
session_registry = {}
rate_limit_tracker = {}


def get_plugin_settings():
    """Get plugin settings from the Cat's mad hatter system."""
    from cat.mad_hatter.mad_hatter import MadHatter

    mad_hatter = MadHatter()
    return mad_hatter.get_plugin().load_settings()


def is_temporary_session(user_id: str) -> bool:
    """
    Check if a user ID represents a temporary session.

    Since we now set both id and name to the session ID in AuthUserInfo,
    this function just needs to check if the user_id starts with SESSION_PREFIX.
    """
    if not user_id:
        return False

    settings = get_plugin_settings()

    # Direct check for session ID format
    if user_id.startswith(settings["session_prefix"]):
        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "session_identified",
                    "data": {"user_id": user_id},
                }
            )
        )
        return True

    return False


def get_session_id_from_user_id(user_id: str) -> str:
    """
    Get the session ID from a user ID.

    Since we now use the session ID directly as the user ID,
    this function just returns the user_id if it's a valid session.
    """
    if not user_id:
        return None

    settings = get_plugin_settings()

    # If it's a session ID, return it
    if user_id.startswith(settings["session_prefix"]):
        return user_id

    # Not a session ID
    return None


def check_rate_limit(client_ip: str) -> bool:
    """Check if client IP is within rate limits"""
    settings = get_plugin_settings()
    current_time = datetime.now(utc)

    # Clean old entries
    cutoff_time = current_time - timedelta(
        minutes=settings["rate_limit_window_minutes"]
    )
    if client_ip in rate_limit_tracker:
        rate_limit_tracker[client_ip] = [
            timestamp
            for timestamp in rate_limit_tracker[client_ip]
            if timestamp > cutoff_time
        ]

    # Check current rate
    if client_ip not in rate_limit_tracker:
        rate_limit_tracker[client_ip] = []

    if len(rate_limit_tracker[client_ip]) >= settings["rate_limit_sessions_per_ip"]:
        return False

    # Record this request
    rate_limit_tracker[client_ip].append(current_time)
    return True


def cleanup_expired_sessions(cat=None):
    """
    Remove expired sessions from registry and clean their episodic memories.

    Args:
        cat: Optional cat instance for memory cleanup
    """
    current_time = datetime.now(utc)
    expired_sessions = [
        session_id
        for session_id, session_data in session_registry.items()
        if session_data["expires_at"] < current_time
    ]

    memory_cleanups = 0
    for session_id in expired_sessions:
        # Clean memory if cat instance is available
        if cat:
            memory_cleanups += cleanup_session_episodic_memory(session_id, cat)

        # Remove from registry
        del session_registry[session_id]
        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "expired_session_cleaned",
                    "data": {"session_id": session_id},
                }
            )
        )

    if memory_cleanups > 0:
        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "expired_memories_cleaned",
                    "data": {"count": memory_cleanups},
                }
            )
        )

    return len(expired_sessions)


def cleanup_session_episodic_memory(session_id: str, cat=None):
    """
    Clean up episodic memories associated with a temporary session.

    This removes all memories that were tagged with the session metadata
    during storage to prevent accumulation of temporary session data.

    Args:
        session_id: The session ID (user_id) to clean memories for
        cat: Cat instance for memory access
    """
    try:
        # If no cat instance is provided, we can't clean memory
        if not cat:
            log.warning(
                json.dumps(
                    {
                        "component": "ccat_temporary_chat_authentication",
                        "event": "memory_cleanup_warning",
                        "data": {"session_id": session_id, "reason": "no_cat_instance"},
                    }
                )
            )
            return 0

        # Filter metadata to find memories from this session
        metadata_filter = {"source": session_id, "session_type": "temporary"}

        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "memory_cleanup_start",
                    "data": {"session_id": session_id, "filter": metadata_filter},
                }
            )
        )

        # Delete points matching the session metadata
        cat.memory.vectors.episodic.delete_points_by_metadata_filter(metadata_filter)

        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "memory_cleanup_success",
                    "data": {"session_id": session_id},
                }
            )
        )
        return 1

    except Exception as e:
        log.error(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "memory_cleanup_error",
                    "data": {"session_id": session_id, "error": str(e)},
                }
            )
        )
        return 0


def cleanup_all_temporary_episodic_memories(cat, purge: bool = False):
    """
    Clean up all episodic memories with session_type=temporary metadata.

    This function is called after Cat bootstrap to clean up temporary session memories
    that may have persisted from previous runs or orphaned sessions.

    Args:
        cat: Cat instance for memory access
        purge: If True, delete ALL temporary episodic memories.
               If False, delete only memories from sessions not in session_registry.

    Returns:
        int: Number of memory cleanup operations performed
    """
    try:
        if not cat:
            log.warning(
                "Cannot clean temporary episodic memories: no cat instance available"
            )
            return 0

        log.info(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "memory_cleanup_all_start",
                    "data": {"purge": purge},
                }
            )
        )

        if purge:
            # Delete ALL temporary episodic memories
            metadata_filter = {"session_type": "temporary"}

            log.info(
                json.dumps(
                    {
                        "component": "ccat_temporary_chat_authentication",
                        "event": "memory_cleanup_all_purge",
                        "data": {},
                    }
                )
            )
            cat.memory.vectors.episodic.delete_points_by_metadata_filter(
                metadata_filter
            )

            log.info(
                json.dumps(
                    {
                        "component": "ccat_temporary_chat_authentication",
                        "event": "memory_cleanup_all_success",
                        "data": {},
                    }
                )
            )
            return 1
        else:
            # Get all memories with temporary session metadata
            # We need to check each memory individually to see if its session is still active
            cleanup_count = 0

            # Get all points with temporary session metadata
            # Note: The exact method to retrieve points by metadata may vary depending on the vector store implementation
            # This is a simplified approach - you might need to adapt based on your vector store
            try:
                # Try to get all temporary session memories for selective cleanup
                # Since we can't easily list all points, we'll iterate through known expired sessions
                # and any sessions that are not in the current session_registry

                # First, clean up any expired sessions we know about
                current_time = datetime.now(utc)
                expired_sessions = [
                    session_id
                    for session_id, session_data in session_registry.items()
                    if session_data["expires_at"] < current_time
                ]

                for session_id in expired_sessions:
                    cleanup_count += cleanup_session_episodic_memory(session_id, cat)

                # For a more thorough cleanup, we could implement a method to scan all memories
                # but that would require more complex vector store operations

                log.info(
                    json.dumps(
                        {
                            "component": "ccat_temporary_chat_authentication",
                            "event": "memory_cleanup_selective_success",
                            "data": {"count": cleanup_count},
                        }
                    )
                )

            except Exception as e:
                log.error(
                    json.dumps(
                        {
                            "component": "ccat_temporary_chat_authentication",
                            "event": "memory_cleanup_selective_error",
                            "data": {"error": str(e)},
                        }
                    )
                )
                # Fallback to purge if selective cleanup fails
                log.info("Falling back to purge mode due to selective cleanup error")
                metadata_filter = {"session_type": "temporary"}
                cat.memory.vectors.episodic.delete_points_by_metadata_filter(
                    metadata_filter
                )
                cleanup_count = 1

            return cleanup_count

    except Exception as e:
        log.error(
            json.dumps(
                {
                    "component": "ccat_temporary_chat_authentication",
                    "event": "memory_cleanup_all_error",
                    "data": {"error": str(e)},
                }
            )
        )
        return 0
