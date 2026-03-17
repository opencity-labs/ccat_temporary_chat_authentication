from pydantic import BaseModel, Field
from cat.mad_hatter.decorators import plugin


# Plugin settings
class SessionManagerSettings(BaseModel):
    default_session_duration_minutes: int = Field(
        default=60,
        title="Default Session Duration (minutes)",
        description="How long temporary sessions should last by default",
    )
    rate_limit_sessions_per_ip: int = Field(
        default=100,
        title="Rate Limit per IP",
        description="Maximum number of sessions that can be created per IP address",
    )
    rate_limit_window_minutes: int = Field(
        default=60,
        title="Rate Limit Window (minutes)",
        description="Time window for rate limiting session creation",
    )
    session_prefix: str = Field(
        default="temp_session_",
        title="Session ID Prefix",
        description="Prefix used for temporary session IDs",
    )
    cleanup_on_startup: bool = Field(
        default=True,
        title="Cleanup on Startup",
        description="Whether to clean up all episodic memories from temporary sessions when the Cat starts",
    )
    auto_configure_auth: bool = Field(
        default=True,
        title="Auto Configure Authentication",
        description="Whether to automatically configure the Cat to use the temporary session auth handler",
    )
    episodic_memory_for_tmp: bool = Field(
        default=False,
        title="Episodic Memory for Temporary Sessions",
        description="Whether to enable episodic memory for temporary sessions",
    )

    # ── Chatbot UI settings ────────────────────────────────────────────────
    chatbot_header_title: str = Field(
        default="AI Assistant",
        title="Chatbot Header Title",
        description="Title shown in the browser tab and the chat header bar",
    )
    chatbot_bot_name: str = Field(
        default="AI Chatbot",
        title="Chatbot Bot Name",
        description="Name shown next to each bot message bubble",
    )
    chatbot_accent_color: str = Field(
        default="#005fff",
        title="Chatbot Accent Color (hex)",
        description="Primary color used for the header, buttons and user bubbles (e.g. #005fff)",
    )
    chatbot_privacy_url: str = Field(
        default="#",
        title="Privacy Policy URL",
        description="Full URL to the privacy policy page shown in the chatbot overlay and footer",
    )
    chatbot_default_questions: str = Field(
        default="",
        title="Default Suggested Questions",
        description="Comma-separated list of suggested questions shown as chips below each bot message (leave empty to hide)",
    )


# hook to give the cat settings
@plugin
def settings_model():
    return SessionManagerSettings
