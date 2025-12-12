#!/usr/bin/env python3
"""
Standalone unit tests for RBAC permission system.

Tests permission checking, role permissions, and function access control.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

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
    print("Testing role permissions...")

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

    print("  ✓ Role permissions test passed")


def test_permission_checker_has_permission():
    """Test PermissionChecker.has_permission()."""
    print("Testing permission checker has_permission...")

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

    print("  ✓ PermissionChecker.has_permission() test passed")


def test_permission_checker_can_call_function():
    """Test PermissionChecker.can_call_function()."""
    print("Testing permission checker can_call_function...")

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

    print("  ✓ PermissionChecker.can_call_function() test passed")


def test_check_permission_helper():
    """Test global check_permission() helper."""
    print("Testing check_permission helper...")

    # Admin has all permissions
    assert check_permission("admin", Permission.CHAT)
    assert check_permission("admin", Permission.MANAGE_USERS)

    # User has most permissions
    assert check_permission("user", Permission.CHAT)
    assert not check_permission("user", Permission.MANAGE_USERS)

    # Guest has limited permissions
    assert check_permission("guest", Permission.CHAT)
    assert not check_permission("guest", Permission.CREATE_CALENDAR_EVENT)

    print("  ✓ check_permission() helper test passed")


def test_check_function_permission_helper():
    """Test global check_function_permission() helper."""
    print("Testing check_function_permission helper...")

    # Admin can call all functions
    assert check_function_permission("admin", "create_calendar_event")
    assert check_function_permission("admin", "search_memories")

    # User can call most functions
    assert check_function_permission("user", "create_calendar_event")
    assert not check_function_permission("guest", "create_calendar_event")

    print("  ✓ check_function_permission() helper test passed")


def test_require_permission():
    """Test require_permission() raises error when permission denied."""
    print("Testing require_permission...")

    # Should succeed for admin
    require_permission("user-123", "admin", Permission.MANAGE_USERS)

    # Should fail for user
    try:
        require_permission("user-456", "user", Permission.MANAGE_USERS)
        assert False, "Should have raised PermissionDeniedError"
    except PermissionDeniedError as e:
        assert "user-456" in str(e)
        assert "manage_users" in str(e)

    print("  ✓ require_permission() test passed")


def test_require_function_permission():
    """Test require_function_permission() raises error when permission denied."""
    print("Testing require_function_permission...")

    # Should succeed for user
    require_function_permission("user-123", "user", "create_calendar_event")

    # Should fail for guest
    try:
        require_function_permission("user-456", "guest", "create_calendar_event")
        assert False, "Should have raised PermissionDeniedError"
    except PermissionDeniedError as e:
        assert "user-456" in str(e)
        assert "create_calendar_event" in str(e)

    print("  ✓ require_function_permission() test passed")


def test_function_permissions_mapping():
    """Test that all function permissions are correctly mapped."""
    print("Testing function permissions mapping...")

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

    print("  ✓ Function permissions mapping test passed")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("RBAC PERMISSION SYSTEM TESTS")
    print("=" * 60 + "\n")

    try:
        test_role_permissions()
        test_permission_checker_has_permission()
        test_permission_checker_can_call_function()
        test_check_permission_helper()
        test_check_function_permission_helper()
        test_require_permission()
        test_require_function_permission()
        test_function_permissions_mapping()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60 + "\n")

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
