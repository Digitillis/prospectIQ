#!/usr/bin/env python3
"""Create an admin user in ProspectIQ backend.

Usage:
    python create_admin_user.py <email> <password> <workspace_name>

Example:
    python create_admin_user.py admin@test.com AdminPass2026! "My Workspace"
"""

import sys
import uuid
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, "/Users/avanish/prospectIQ")

from backend.app.core.database import get_supabase_client


def create_admin_user(email: str, password: str, workspace_name: str) -> dict:
    """Create a Supabase user, workspace, and admin workspace member."""
    client = get_supabase_client()
    email = email.lower().strip()
    workspace_id = str(uuid.uuid4())

    print(f"Creating admin user: {email}")
    print(f"Workspace: {workspace_name}")
    print(f"Workspace ID: {workspace_id}\n")

    # 1. Create Supabase auth user via Admin API
    print("Creating Supabase auth user...")
    try:
        auth_response = client.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True, "user_metadata": {"full_name": "Admin User"}}
        )
        user_id = auth_response.user.id
        print(f"✓ User created: {user_id}\n")
    except Exception as e:
        print(f"✗ Error creating Supabase user: {e}")
        return {"error": str(e)}

    # 2. Create workspace
    print("Creating workspace...")
    try:
        # Generate slug from workspace name
        slug = workspace_name.lower().replace(" ", "-").replace("_", "-")
        workspace_data = {
            "id": workspace_id,
            "name": workspace_name,
            "slug": slug,
            "owner_email": email,
            "tier": "professional",  # Give admin full tier access
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        client.table("workspaces").insert(workspace_data).execute()
        print(f"✓ Workspace created: {workspace_id}\n")
    except Exception as e:
        print(f"✗ Error creating workspace: {e}")
        return {"error": str(e)}

    # 3. Add user as admin workspace member
    print("Adding user as admin member...")
    try:
        member_data = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "email": email,
            "role": "admin",
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        client.table("workspace_members").insert(member_data).execute()
        print(f"✓ Admin member added\n")
    except Exception as e:
        print(f"✗ Error adding workspace member: {e}")
        return {"error": str(e)}

    result = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "email": email,
        "role": "admin",
    }

    print("=" * 60)
    print("Admin user created successfully!")
    print("=" * 60)
    print(f"Email:           {email}")
    print(f"Password:        {password}")
    print(f"User ID:         {user_id}")
    print(f"Workspace:       {workspace_name}")
    print(f"Workspace ID:    {workspace_id}")
    print(f"Role:            admin")
    print("=" * 60)
    print("\nYou can now log in at: https://crm.digitillis.com/login")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    workspace_name = sys.argv[3]

    create_admin_user(email, password, workspace_name)
