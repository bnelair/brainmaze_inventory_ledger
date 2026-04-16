"""
User Authentication & Authorization for Brainmaze Inventory Ledger.

Users are stored in ``data/users.yaml`` which lives inside the git-tracked
data directory.  Passwords are stored as **bcrypt** hashes — never in plain
text.  Because the file is committed to git alongside the inventory data, the
entire auth layer is *stateless*: no external database is required, and the
user list survives container restarts automatically.

Roles
-----
admin      Full access: user management, project management, schema editing,
           Git sync, all CRUD operations.
readwrite  Can add items, record stock changes, perform batch ops, view, and
           download reports.
readonly   View-only: current stock, event history, and report downloads.

Registration workflow
---------------------
1. A new user self-registers via the login page → account is created with
   ``active: false`` (pending approval).
2. An admin sees the pending user in the User Management page and either
   approves (sets ``active: true``) or rejects (deletes) the account.
3. Only active accounts can authenticate.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import yaml

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_READWRITE = "readwrite"
ROLE_READONLY = "readonly"
VALID_ROLES = {ROLE_ADMIN, ROLE_READWRITE, ROLE_READONLY}
ROLE_LABELS = {
    ROLE_ADMIN:     "Admin",
    ROLE_READWRITE: "Read & Write",
    ROLE_READONLY:  "Read Only",
}

# Username: alphanumeric + dot / hyphen / underscore, 3–32 chars
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._\-]{3,32}$")

_DEFAULT_USERS_DOC = """\
# Brainmaze Inventory Ledger – User Store
# -----------------------------------------
# Passwords are bcrypt-hashed.  Never store plain-text passwords here.
# Use the Admin → User Management UI to add / edit / remove users.
users: []
"""


class AuthManager:
    """
    Manages users stored in a YAML file inside the data directory.

    Parameters
    ----------
    data_dir : str | Path
        Root data directory (same one that holds ``projects.yaml``).
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users.yaml"
        self._bootstrap()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.users_file.exists():
            self.users_file.write_text(_DEFAULT_USERS_DOC, encoding="utf-8")

    def _load_all(self) -> List[Dict[str, Any]]:
        raw = yaml.safe_load(self.users_file.read_text(encoding="utf-8")) or {}
        return raw.get("users", [])

    def _save_all(self, users: List[Dict[str, Any]]) -> None:
        raw = yaml.safe_load(self.users_file.read_text(encoding="utf-8")) or {}
        raw["users"] = users
        self.users_file.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Password utilities
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_username(username: str) -> Optional[str]:
        """Return an error message, or None if valid."""
        if not username.strip():
            return "Username cannot be empty."
        if not _USERNAME_RE.match(username):
            return "Username must be 3–32 characters: letters, numbers, dot, hyphen, or underscore."
        return None

    @staticmethod
    def _validate_password(password: str) -> Optional[str]:
        if len(password) < 8:
            return "Password must be at least 8 characters."
        return None

    # ------------------------------------------------------------------
    # Bootstrap / state queries
    # ------------------------------------------------------------------

    def has_any_users(self) -> bool:
        return bool(self._load_all())

    def has_active_admin(self) -> bool:
        return any(
            u.get("role") == ROLE_ADMIN and u.get("active", False)
            for u in self._load_all()
        )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Return a session-safe user dict if credentials are valid **and** the
        account is active, else ``None``.

        The returned dict contains: ``username``, ``display_name``, ``role``.
        """
        for user in self._load_all():
            if user.get("username") != username:
                continue
            if not user.get("active", False):
                return None  # pending approval
            if self.verify_password(password, user.get("password_hash", "")):
                return {
                    "username": user["username"],
                    "display_name": user.get("display_name") or user["username"],
                    "role": user.get("role", ROLE_READONLY),
                }
        return None

    # ------------------------------------------------------------------
    # Self-registration (creates PENDING account)
    # ------------------------------------------------------------------

    def register(
        self,
        username: str,
        password: str,
        display_name: str = "",
    ) -> Tuple[bool, str]:
        """
        Create a **pending** (inactive) account.  An admin must approve it.

        Returns ``(success, message)``.
        """
        err = self._validate_username(username)
        if err:
            return False, err
        err = self._validate_password(password)
        if err:
            return False, err
        if self._find(username):
            return False, f"Username '{username}' is already taken."

        users = self._load_all()
        users.append({
            "username": username.strip(),
            "display_name": display_name.strip() or username.strip(),
            "role": ROLE_READONLY,       # lowest privilege by default
            "password_hash": self.hash_password(password),
            "active": False,             # pending admin approval
            "created_at": self._now(),
        })
        self._save_all(users)
        return True, (
            f"Account '{username}' created. "
            "Please wait for an administrator to approve your account before logging in."
        )

    # ------------------------------------------------------------------
    # Admin: user listing & approval
    # ------------------------------------------------------------------

    def list_users(self, include_pending: bool = True) -> List[Dict[str, Any]]:
        """Return public user data (no password hashes)."""
        return [
            {
                "username":     u["username"],
                "display_name": u.get("display_name", u["username"]),
                "role":         u.get("role", ROLE_READONLY),
                "active":       u.get("active", False),
                "created_at":   u.get("created_at", ""),
            }
            for u in self._load_all()
            if include_pending or u.get("active", False)
        ]

    def list_pending(self) -> List[Dict[str, Any]]:
        return [u for u in self.list_users() if not u["active"]]

    def approve_user(self, username: str) -> Tuple[bool, str]:
        """Activate a pending account."""
        users = self._load_all()
        for u in users:
            if u.get("username") == username:
                if u.get("active", False):
                    return False, f"'{username}' is already active."
                u["active"] = True
                self._save_all(users)
                return True, f"Account '{username}' approved."
        return False, f"User '{username}' not found."

    # ------------------------------------------------------------------
    # Admin: create / edit / delete
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        display_name: str = "",
        active: bool = True,
    ) -> Tuple[bool, str]:
        """Create an account directly (admin operation, active by default)."""
        err = self._validate_username(username)
        if err:
            return False, err
        err = self._validate_password(password)
        if err:
            return False, err
        if role not in VALID_ROLES:
            return False, f"Invalid role '{role}'."
        if self._find(username):
            return False, f"User '{username}' already exists."

        users = self._load_all()
        users.append({
            "username":     username.strip(),
            "display_name": display_name.strip() or username.strip(),
            "role":         role,
            "password_hash": self.hash_password(password),
            "active":       active,
            "created_at":   self._now(),
        })
        self._save_all(users)
        return True, f"User '{username}' created."

    def update_password(self, username: str, new_password: str) -> Tuple[bool, str]:
        err = self._validate_password(new_password)
        if err:
            return False, err
        users = self._load_all()
        for u in users:
            if u.get("username") == username:
                u["password_hash"] = self.hash_password(new_password)
                self._save_all(users)
                return True, f"Password updated for '{username}'."
        return False, f"User '{username}' not found."

    def update_role(self, username: str, new_role: str) -> Tuple[bool, str]:
        if new_role not in VALID_ROLES:
            return False, f"Invalid role '{new_role}'."
        users = self._load_all()
        for u in users:
            if u.get("username") == username:
                # Prevent removing the last active admin
                if u.get("role") == ROLE_ADMIN and new_role != ROLE_ADMIN:
                    active_admins = [
                        x for x in users
                        if x.get("role") == ROLE_ADMIN
                        and x.get("active", False)
                        and x.get("username") != username
                    ]
                    if not active_admins:
                        return False, "Cannot demote the only active admin."
                u["role"] = new_role
                self._save_all(users)
                return True, f"Role updated for '{username}'."
        return False, f"User '{username}' not found."

    def update_display_name(self, username: str, display_name: str) -> Tuple[bool, str]:
        users = self._load_all()
        for u in users:
            if u.get("username") == username:
                u["display_name"] = display_name.strip() or username
                self._save_all(users)
                return True, f"Display name updated for '{username}'."
        return False, f"User '{username}' not found."

    def delete_user(self, username: str) -> Tuple[bool, str]:
        users = self._load_all()
        target = self._find(username, users)
        if not target:
            return False, f"User '{username}' not found."
        remaining = [u for u in users if u.get("username") != username]
        # Ensure at least one active admin remains
        if target.get("role") == ROLE_ADMIN and target.get("active", False):
            active_admins_left = [
                u for u in remaining
                if u.get("role") == ROLE_ADMIN and u.get("active", False)
            ]
            if not active_admins_left:
                return False, "Cannot delete the last active admin account."
        self._save_all(remaining)
        return True, f"User '{username}' deleted."

    def set_active(self, username: str, active: bool) -> Tuple[bool, str]:
        users = self._load_all()
        for u in users:
            if u.get("username") == username:
                if not active and u.get("role") == ROLE_ADMIN:
                    others = [
                        x for x in users
                        if x.get("role") == ROLE_ADMIN
                        and x.get("active", False)
                        and x.get("username") != username
                    ]
                    if not others:
                        return False, "Cannot deactivate the only active admin."
                u["active"] = active
                self._save_all(users)
                state = "activated" if active else "deactivated"
                return True, f"User '{username}' {state}."
        return False, f"User '{username}' not found."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find(
        self,
        username: str,
        users: Optional[List[Dict]] = None,
    ) -> Optional[Dict]:
        if users is None:
            users = self._load_all()
        for u in users:
            if u.get("username") == username:
                return u
        return None

    # ------------------------------------------------------------------
    # Permission shortcuts
    # ------------------------------------------------------------------

    @staticmethod
    def can_write(role: str) -> bool:
        return role in (ROLE_ADMIN, ROLE_READWRITE)

    @staticmethod
    def is_admin(role: str) -> bool:
        return role == ROLE_ADMIN
