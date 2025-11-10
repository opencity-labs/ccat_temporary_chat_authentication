from pydantic import BaseModel, Field
from cat.mad_hatter.decorators import plugin


# Plugin settings
class SessionManagerSettings(BaseModel):
    default_session_duration_minutes: int = Field(
        default=60,
        title="Default Session Duration (minutes)",
        description="How long temporary sessions should last by default"
    )
    rate_limit_sessions_per_ip: int = Field(
        default=100,
        title="Rate Limit per IP",
        description="Maximum number of sessions that can be created per IP address"
    )
    rate_limit_window_minutes: int = Field(
        default=60,
        title="Rate Limit Window (minutes)",
        description="Time window for rate limiting session creation"
    )
    session_prefix: str = Field(
        default="temp_session_",
        title="Session ID Prefix",
        description="Prefix used for temporary session IDs"
    )
    cleanup_on_startup: bool = Field(
        default=True,
        title="Cleanup on Startup",
        description="Whether to clean up all episodic memories from temporary sessions when the Cat starts"
    )
    auto_configure_auth: bool = Field(
        default=True,
        title="Auto Configure Authentication",
        description="Whether to automatically configure the Cat to use the temporary session auth handler"
    )
    episodic_memory_for_tmp: bool = Field(
        default=False,
        title="Episodic Memory for Temporary Sessions",
        description="Whether to enable episodic memory for temporary sessions"
    )
    verbose_logging: bool = Field(
        default=True,
        title="Verbose Logging",
        description="Enable detailed logging for debugging and monitoring"
    )


# hook to give the cat settings
@plugin
def settings_model():
    return SessionManagerSettings