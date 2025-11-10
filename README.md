<p align="center">
    <img src="auth.png" alt="Plugin Logo" width="50" style="border-radius: 50%; vertical-align: middle; margin-right: 10px;" />
    <span style="font-size:2em; vertical-align: middle;"><b>Temporary Chat Auth</b></span>
</p>

[![CheshireCat AI Plugin - Temporary Chat Auth](https://custom-icon-badges.demolab.com/static/v1?label=&message=awesome+plugin&color=F4F4F5&style=for-the-badge&logo=cheshire_cat_black)](https://)

Secure temporary session management for anonymous users with JWT authentication and automatic cleanup.

## Description

**Temporary Chat Auth** is a plugin for Cheshire Cat AI that provides secure temporary session management for anonymous users, enabling them to interact with the Cat without permanent registration.
The plugin implements JWT-based authentication with automatic session cleanup, rate limiting, and episodic memory management for temporary users.

## Features
- JWT-based temporary session authentication
- Automatic session expiration and cleanup
- Rate limiting to prevent abuse
- IP-based session creation limits
- Episodic memory management for temporary sessions
- WebSocket authentication integration
- Comprehensive session statistics and monitoring
- Manual session cleanup capabilities

## Usage

The plugin automatically configures authentication when enabled. It provides several API endpoints for session management:

### API Endpoints

- **POST `/custom/sessions/create`** - Create a new temporary session
  - Returns JWT token and WebSocket URL for immediate connection
  - Implements rate limiting per IP address
  - Automatically cleans up expired sessions

- **GET `/custom/sessions/{session_id}/status`** - Check session status
  - Returns session validity and expiration information
  - Shows remaining session time in minutes

- **DELETE `/custom/sessions/{session_id}`** - Manual session cleanup
  - Allows users to invalidate their session immediately
  - Cleans up associated episodic memories
  - Supports JWT token authentication

- **GET `/custom/sessions/stats`** - Get session statistics
  - Returns active session count and average session age
  - Shows cleanup statistics without exposing sensitive data

### Example Implementation

The repository includes an `example.html` file that demonstrates how to create a widget for your website. This example shows how to:
- Create temporary sessions using the API
- Connect to the Cheshire Cat via WebSocket
- Handle authentication with JWT tokens
- Implement a simple chat interface

### Web Interface Compatibility

This plugin is fully compatible with the standard Cheshire Cat web interface. You can continue using the Cheshire Cat from the web interface as usual - the plugin only adds temporary session capabilities for anonymous users and doesn't interfere with normal authenticated usage.

## Requirements
- Cheshire Cat AI
- Temporary Chat Auth plugin enabled
- Restart required to activate new authentication automatically

## Settings

- `default_session_duration_minutes` *(int, default: 60)*: How long temporary sessions should last by default
- `rate_limit_sessions_per_ip` *(int, default: 100)*: Maximum number of sessions that can be created per IP address
- `rate_limit_window_minutes` *(int, default: 60)*: Time window for rate limiting session creation
- `session_prefix` *(str, default: "temp_session_")*: Prefix used for temporary session IDs
- `cleanup_on_startup` *(bool, default: True)*: Whether to clean up all temporary episodic memories when the Cat starts
- `auto_configure_auth` *(bool, default: True)*: Whether to automatically configure the Cat to use the temporary session auth handler
- `episodic_memory_for_tmp` *(bool, default: False)*: Whether to enable episodic memory for temporary sessions
- `verbose_logging` *(bool, default: True)*: Enable detailed logging for debugging and monitoring

---
Author: OpenCity Labs  
LinkedIn: https://www.linkedin.com/company/opencity-italia/

