#!/usr/bin/env python3
"""
User management CLI for Cognitia.

Provides commands to manage users, roles, and permissions.

v2.1+: RBAC user management
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitia.auth import UserManager, RoleEnum
from cognitia.auth.permissions import ROLE_PERMISSIONS, Permission
from loguru import logger


def setup_user_manager() -> UserManager:
    """Initialize user manager with default database path."""
    db_path = Path("data/users.db")
    secret_path = Path("data/.jwt_secret")

    # Read JWT secret
    if not secret_path.exists():
        print("Error: JWT secret not found. Run scripts/create_admin.py first.")
        sys.exit(1)

    secret_key = secret_path.read_text().strip()

    # Create user manager
    user_manager = UserManager(db_path=db_path, secret_key=secret_key)
    return user_manager


def list_users(args):
    """List all users."""
    user_manager = setup_user_manager()

    # Get all users (this would require adding a list_users method to UserManager)
    # For now, we'll need to query the database directly
    import sqlite3

    with sqlite3.connect(str(user_manager.db.db_path)) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        SELECT user_id, username, email, is_active, is_admin, role, created_at
        FROM users
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()

    if not rows:
        print("No users found.")
        return

    print(f"\n{'Username':<20} {'Email':<30} {'Role':<12} {'Active':<8} {'Created':<20}")
    print("-" * 100)

    for row in rows:
        user_id, username, email, is_active, is_admin, role, created_at = row
        active_str = "Yes" if is_active else "No"
        print(f"{username:<20} {email:<30} {role:<12} {active_str:<8} {created_at:<20}")

    print(f"\nTotal: {len(rows)} users")


def create_user(args):
    """Create a new user."""
    user_manager = setup_user_manager()

    # Get password
    import getpass

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        print("Error: Passwords don't match")
        sys.exit(1)

    # Validate role
    valid_roles = [r.value for r in RoleEnum]
    if args.role not in valid_roles:
        print(f"Error: Invalid role. Must be one of: {', '.join(valid_roles)}")
        sys.exit(1)

    try:
        # Create user
        user = user_manager.db.create_user(
            username=args.username,
            email=args.email,
            password=password,
            is_admin=(args.role == "admin"),
            role=args.role,
        )

        print(f"\n✓ User created successfully!")
        print(f"  Username: {user.username}")
        print(f"  Email: {user.email}")
        print(f"  Role: {user.role}")
        print(f"  User ID: {user.user_id}")

    except Exception as e:
        print(f"Error creating user: {e}")
        sys.exit(1)


def change_role(args):
    """Change a user's role."""
    user_manager = setup_user_manager()

    # Validate role
    valid_roles = [r.value for r in RoleEnum]
    if args.role not in valid_roles:
        print(f"Error: Invalid role. Must be one of: {', '.join(valid_roles)}")
        sys.exit(1)

    # Get user
    user = user_manager.db.get_user_by_username(args.username)
    if not user:
        print(f"Error: User '{args.username}' not found")
        sys.exit(1)

    # Update role in database
    import sqlite3

    with sqlite3.connect(str(user_manager.db.db_path)) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE users
        SET role = ?, is_admin = ?
        WHERE username = ?
    """, (args.role, 1 if args.role == "admin" else 0, args.username))

    conn.commit()

    print(f"\n✓ Role updated successfully!")
    print(f"  Username: {args.username}")
    print(f"  New role: {args.role}")


def set_active(args):
    """Activate or deactivate a user."""
    user_manager = setup_user_manager()

    # Get user
    user = user_manager.db.get_user_by_username(args.username)
    if not user:
        print(f"Error: User '{args.username}' not found")
        sys.exit(1)

    # Update active status
    import sqlite3

    with sqlite3.connect(str(user_manager.db.db_path)) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE users
        SET is_active = ?
        WHERE username = ?
    """, (1 if args.active else 0, args.username))

    conn.commit()

    status = "activated" if args.active else "deactivated"
    print(f"\n✓ User {status} successfully!")
    print(f"  Username: {args.username}")


def delete_user(args):
    """Delete a user."""
    user_manager = setup_user_manager()

    # Get user
    user = user_manager.db.get_user_by_username(args.username)
    if not user:
        print(f"Error: User '{args.username}' not found")
        sys.exit(1)

    # Confirm deletion
    if not args.force:
        response = input(f"Are you sure you want to delete user '{args.username}'? (yes/no): ")
        if response.lower() != "yes":
            print("Deletion cancelled.")
            return

    # Delete user
    import sqlite3

    with sqlite3.connect(str(user_manager.db.db_path)) as conn:
        cursor = conn.cursor()

        # Delete user and related data
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user.user_id,))
        cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user.user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user.user_id,))

        conn.commit()

    print(f"\n✓ User deleted successfully!")
    print(f"  Username: {args.username}")


def revoke_tokens(args):
    """Revoke all tokens for a user."""
    user_manager = setup_user_manager()

    # Get user
    user = user_manager.db.get_user_by_username(args.username)
    if not user:
        print(f"Error: User '{args.username}' not found")
        sys.exit(1)

    # Delete all sessions for user
    import sqlite3

    with sqlite3.connect(str(user_manager.db.db_path)) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user.user_id,))
        count = cursor.fetchone()[0]

        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user.user_id,))
        conn.commit()

    print(f"\n✓ Tokens revoked successfully!")
    print(f"  Username: {args.username}")
    print(f"  Sessions deleted: {count}")


def show_permissions(args):
    """Show permissions for a role."""
    # Validate role
    valid_roles = [r.value for r in RoleEnum]
    if args.role not in valid_roles:
        print(f"Error: Invalid role. Must be one of: {', '.join(valid_roles)}")
        sys.exit(1)

    role_enum = RoleEnum(args.role)
    permissions = ROLE_PERMISSIONS.get(role_enum, set())

    print(f"\nPermissions for role '{args.role}':")
    print("-" * 50)

    if not permissions:
        print("  (no permissions)")
    else:
        for perm in sorted(permissions, key=lambda p: p.value):
            print(f"  • {perm.value}")

    print(f"\nTotal: {len(permissions)} permissions")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Cognitia User Management CLI (v2.1+)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List users
    list_parser = subparsers.add_parser("list", help="List all users")
    list_parser.set_defaults(func=list_users)

    # Create user
    create_parser = subparsers.add_parser("create", help="Create a new user")
    create_parser.add_argument("username", help="Username")
    create_parser.add_argument("email", help="Email address")
    create_parser.add_argument(
        "--role",
        default="user",
        choices=["admin", "user", "guest", "restricted"],
        help="User role (default: user)",
    )
    create_parser.set_defaults(func=create_user)

    # Change role
    role_parser = subparsers.add_parser("set-role", help="Change a user's role")
    role_parser.add_argument("username", help="Username")
    role_parser.add_argument(
        "role",
        choices=["admin", "user", "guest", "restricted"],
        help="New role",
    )
    role_parser.set_defaults(func=change_role)

    # Activate/deactivate
    active_parser = subparsers.add_parser("set-active", help="Activate or deactivate a user")
    active_parser.add_argument("username", help="Username")
    active_parser.add_argument(
        "active",
        type=lambda x: x.lower() in ["true", "1", "yes"],
        help="Active status (true/false)",
    )
    active_parser.set_defaults(func=set_active)

    # Delete user
    delete_parser = subparsers.add_parser("delete", help="Delete a user")
    delete_parser.add_argument("username", help="Username")
    delete_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    delete_parser.set_defaults(func=delete_user)

    # Revoke tokens
    revoke_parser = subparsers.add_parser("revoke-tokens", help="Revoke all tokens for a user")
    revoke_parser.add_argument("username", help="Username")
    revoke_parser.set_defaults(func=revoke_tokens)

    # Show permissions
    perms_parser = subparsers.add_parser("permissions", help="Show permissions for a role")
    perms_parser.add_argument(
        "role",
        choices=["admin", "user", "guest", "restricted"],
        help="Role to show permissions for",
    )
    perms_parser.set_defaults(func=show_permissions)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    args.func(args)


if __name__ == "__main__":
    main()
