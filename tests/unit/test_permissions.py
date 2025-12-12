#!/usr/bin/env python3
"""
Unit tests for RBAC permission system.

Tests permission checking, role permissions, and function access control.
"""

import pytest
from cognitia.auth.permissions import (
    Permission,
    Role,
    PermissionChecker,
    PermissionDeniedError,
    check_permission,
    check_function_permission,
    require_permission,
    require_function_permission,
    ROLE_PERMISSIONS,
    FUNCTION_PERMISSIONS,
)


def test_role_permissions():
    """Test that role permissions are correctly defined."""
    # Admin should have all permissions
    admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.CHAT in admin_perms
    assert Permission.MANAGE_USERS in admin_perms
    assert Permission.CREATE_CALENDAR_EVENT in admin_perms

    # User should have most permissions except admin functions
    user_perms = ROLE_PERMISSIONS[Role.USER]
    assert Permission.CHAT in user_perms
    assert Permission.CREATE_CALENDAR_EVENT in user_perms
    assert Permission.MANAGE_USERS not in user_perms

    # Guest should have read-only permissions
    guest_perms = ROLE_PERMISSIONS[Role.GUEST]
    assert Permission.CHAT in guest_perms
    assert Permission.VIEW_CALENDAR_EVENTS in guest_perms
    assert Permission.CREATE_CALENDAR_EVENT not in guest_perms

    # Restricted should have minimal permissions
    restricted_perms = ROLE_PERMISSIONS[Role.RESTRICTED]
    assert Permission.CHAT in restricted_perms
    assert Permission.GET_TIME in restricted_perms
    assert Permission.CREATE_CALENDAR_EVENT not in restricted_perms


def test_permission_checker_has_permission():
    """Test PermissionChecker.has_permission()."""
    checker = PermissionChecker()

    # Admin has all permissions
    assert checker.has_permission("admin", Permission.CHAT)
    assert checker.has_permission("admin", Permission.MANAGE_USERS)
    assert checker.has_permission("admin", Permission.CREATE_CALENDAR_EVENT)

    # User has most permissions
    assert checker.has_permission("user", Permission.CHAT)
    assert checker.has_permission("user", Permission.CREATE_CALENDAR_EVENT)
    assert not checker.has_permission("user", Permission.MANAGE_USERS)

    # Guest has limited permissions
    assert checker.has_permission("guest", Permission.CHAT)
    assert not checker.has_permission("guest", Permission.CREATE_CALENDAR_EVENT)

    # Restricted has minimal permissions
    assert checker.has_permission("restricted", Permission.CHAT)
    assert not checker.has_permission("restricted", Permission.CREATE_CALENDAR_EVENT)

    # Unknown role has no permissions
    assert not checker.has_permission("unknown", Permission.CHAT)


def test_permission_checker_can_call_function():
    """Test PermissionChecker.can_call_function()."""
    checker = PermissionChecker()

    # Admin can call all functions
    assert checker.can_call_function("admin", "create_calendar_event")
    assert checker.can_call_function("admin", "search_memories")

    # User can call most functions
    assert checker.can_call_function("user", "create_calendar_event")
    assert checker.can_call_function("user", "search_memories")

    # Guest can only call view functions
    assert not checker.can_call_function("guest", "create_calendar_event")
    assert not checker.can_call_function("guest", "search_memories")
    assert checker.can_call_function("guest", "list_calendar_events")

    # Restricted has very limited function access
    assert not checker.can_call_function("restricted", "create_calendar_event")
    assert checker.can_call_function("restricted", "get_current_time")


def test_permission_checker_get_role_permissions():
    """Test PermissionChecker.get_role_permissions()."""
    checker = PermissionChecker()

    admin_perms = checker.get_role_permissions("admin")
    assert len(admin_perms) > 10  # Admin has many permissions

    user_perms = checker.get_role_permissions("user")
    assert len(user_perms) > 5  # User has several permissions
    assert len(user_perms) < len(admin_perms)  # But fewer than admin

    guest_perms = checker.get_role_permissions("guest")
    assert len(guest_perms) < len(user_perms)  # Guest has fewer than user

    unknown_perms = checker.get_role_permissions("unknown")
    assert len(unknown_perms) == 0  # Unknown role has no permissions


def test_permission_checker_get_allowed_functions():
    """Test PermissionChecker.get_allowed_functions()."""
    checker = PermissionChecker()

    admin_funcs = checker.get_allowed_functions("admin")
    assert "create_calendar_event" in admin_funcs
    assert "search_memories" in admin_funcs
    assert "create_reminder" in admin_funcs

    user_funcs = checker.get_allowed_functions("user")
    assert "create_calendar_event" in user_funcs
    assert "search_memories" in user_funcs

    guest_funcs = checker.get_allowed_functions("guest")
    assert "create_calendar_event" not in guest_funcs
    assert "list_calendar_events" in guest_funcs

    restricted_funcs = checker.get_allowed_functions("restricted")
    assert "create_calendar_event" not in restricted_funcs
    assert "get_current_time" in restricted_funcs


def test_check_permission_helper():
    """Test global check_permission() helper."""
    # Admin has all permissions
    assert check_permission("admin", Permission.CHAT)
    assert check_permission("admin", Permission.MANAGE_USERS)

    # User has most permissions
    assert check_permission("user", Permission.CHAT)
    assert not check_permission("user", Permission.MANAGE_USERS)

    # Guest has limited permissions
    assert check_permission("guest", Permission.CHAT)
    assert not check_permission("guest", Permission.CREATE_CALENDAR_EVENT)


def test_check_function_permission_helper():
    """Test global check_function_permission() helper."""
    # Admin can call all functions
    assert check_function_permission("admin", "create_calendar_event")
    assert check_function_permission("admin", "search_memories")

    # User can call most functions
    assert check_function_permission("user", "create_calendar_event")
    assert not check_function_permission("guest", "create_calendar_event")


def test_require_permission():
    """Test require_permission() raises error when permission denied."""
    # Should succeed for admin
    require_permission("user-123", "admin", Permission.MANAGE_USERS)

    # Should fail for user
    with pytest.raises(PermissionDeniedError) as exc_info:
        require_permission("user-456", "user", Permission.MANAGE_USERS)

    assert "user-456" in str(exc_info.value)
    assert "manage_users" in str(exc_info.value)


def test_require_function_permission():
    """Test require_function_permission() raises error when permission denied."""
    # Should succeed for user
    require_function_permission("user-123", "user", "create_calendar_event")

    # Should fail for guest
    with pytest.raises(PermissionDeniedError) as exc_info:
        require_function_permission("user-456", "guest", "create_calendar_event")

    assert "user-456" in str(exc_info.value)
    assert "create_calendar_event" in str(exc_info.value)


def test_permission_denied_error():
    """Test PermissionDeniedError exception."""
    error = PermissionDeniedError(
        user_id="user-123",
        action="test_action",
        required_permission=Permission.MANAGE_USERS,
    )

    assert error.user_id == "user-123"
    assert error.action == "test_action"
    assert error.required_permission == Permission.MANAGE_USERS
    assert "user-123" in str(error)
    assert "test_action" in str(error)
    assert "manage_users" in str(error)


def test_function_permissions_mapping():
    """Test that all function permissions are correctly mapped."""
    # Verify some key function mappings
    assert FUNCTION_PERMISSIONS["create_calendar_event"] == Permission.CREATE_CALENDAR_EVENT
    assert FUNCTION_PERMISSIONS["list_calendar_events"] == Permission.VIEW_CALENDAR_EVENTS
    assert FUNCTION_PERMISSIONS["create_reminder"] == Permission.CREATE_REMINDER
    assert FUNCTION_PERMISSIONS["list_reminders"] == Permission.VIEW_REMINDERS
    assert FUNCTION_PERMISSIONS["create_todo"] == Permission.CREATE_TODO
    assert FUNCTION_PERMISSIONS["list_todos"] == Permission.VIEW_TODOS
    assert FUNCTION_PERMISSIONS["search_memories"] == Permission.SEARCH_MEMORY
    assert FUNCTION_PERMISSIONS["get_current_time"] == Permission.GET_TIME
    assert FUNCTION_PERMISSIONS["get_weather"] == Permission.GET_WEATHER


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
