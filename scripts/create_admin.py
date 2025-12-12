#!/usr/bin/env python3
"""
Create initial admin user for Cognitia.

Usage:
    python scripts/create_admin.py
"""

import sys
import getpass
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from cognitia.auth.database import UserDatabase
except ImportError as e:
    print(f"Error: Could not import auth module: {e}")
    print("Make sure you've installed dependencies: pip install bcrypt")
    sys.exit(1)


def main():
    """Main entry point."""
    print("=" * 60)
    print("Cognitia Admin User Creation")
    print("=" * 60)
    print()

    # Database path
    db_path = Path("data/users.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize database
    try:
        db = UserDatabase(db_path)
    except Exception as e:
        print(f"Error: Failed to initialize database: {e}")
        sys.exit(1)

    print("Creating admin user...")
    print()

    # Get user input
    username = input("Username: ").strip()
    if not username:
        print("Error: Username cannot be empty")
        sys.exit(1)

    email = input("Email: ").strip()
    if not email:
        print("Error: Email cannot be empty")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: Password cannot be empty")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: Passwords don't match!")
        sys.exit(1)

    # Create user
    print()
    print("Creating admin user...")

    try:
        user = db.create_user(
            username=username,
            email=email,
            password=password,
            is_admin=True
        )

        print()
        print("✓ Admin user created successfully!")
        print()
        print(f"  User ID:  {user.user_id}")
        print(f"  Username: {user.username}")
        print(f"  Email:    {user.email}")
        print(f"  Admin:    Yes")
        print()
        print("You can now login with this account.")

    except Exception as e:
        print()
        print(f"✗ Error creating user: {e}")
        print()
        print("Common issues:")
        print("  - Username or email already exists")
        print("  - bcrypt not installed (run: pip install bcrypt)")
        sys.exit(1)


if __name__ == "__main__":
    main()
