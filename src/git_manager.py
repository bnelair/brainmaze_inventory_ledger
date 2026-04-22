"""
Git Authentication and Synchronization Manager.

Supports four authentication methods:

PAT   – Personal Access Token embedded in an HTTPS URL
        ``https://<token>@github.com/org/repo.git``

SSH   – Key-based auth; requires ``/root/.ssh`` (or ``~/.ssh``) to be mounted
        read-only in the container.

APP   – GitHub / GitLab App / Bot account using an HTTPS token supplied via
        environment variable (functionally identical to PAT but intended for
        service accounts).

BASIC – Username + password (or project/deploy token used as password).
        Builds ``https://<username>:<password>@host/repo.git``.
        This is the same mechanism used by Wiki.js and works with GitLab
        service accounts without needing a Personal Access Token UI.

git-crypt
---------
If the remote repository uses git-crypt, call ``unlock_git_crypt()`` after
cloning / initialising.  The symmetric key must be supplied as a Base64-
encoded string in the ``GIT_CRYPT_KEY`` environment variable.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

# Git branch names: allow alphanumeric, hyphen, underscore, forward slash, dot
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/\-]{1,255}$")


def _safe_branch(branch: str) -> str:
    """Validate and return a safe git branch name, raising ValueError on bad input."""
    branch = branch.strip()
    if branch.startswith("-"):
        raise ValueError(
            f"Invalid branch name {branch!r}: branch names must not start with a dash."
        )
    if not _BRANCH_RE.match(branch):
        raise ValueError(
            f"Invalid branch name {branch!r}. "
            "Only alphanumeric characters, hyphens, underscores, dots, and slashes are allowed."
        )
    return branch


def _safe_commit_msg(msg: str) -> str:
    """Return a sanitised commit message, replacing unsafe characters."""
    # Strip any leading/trailing whitespace; replace control characters with a space
    msg = re.sub(r"[\x00-\x1f\x7f]", " ", msg.strip())
    # Truncate to a safe length
    return msg[:500] if msg else "Inventory update"


def _safe_git_config_value(value: str, max_len: int = 100) -> str:
    """Strip control characters and NUL from a git config string value."""
    value = re.sub(r"[\x00-\x1f\x7f]", "", value.strip())
    return value[:max_len] if value else "Brainmaze"


_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_SAFE_URL_SCHEMES = frozenset({"https", "http", "git", "ssh"})


def _safe_url(url: str) -> str:
    """
    Validate that a remote URL uses a known safe scheme and does not start with
    a dash (which git would interpret as a flag, enabling argument injection).

    Raises ValueError for unsafe inputs.
    """
    url = url.strip()
    if not url:
        return url
    if url.startswith("-"):
        raise ValueError(
            f"Unsafe repository URL {url!r}: URL must not start with a dash."
        )
    # Allow git@host:path SSH shorthand without a scheme
    if url.startswith("git@"):
        return url
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _SAFE_URL_SCHEMES:
        raise ValueError(
            f"Unsafe repository URL scheme {parsed.scheme!r}. "
            f"Allowed schemes: {sorted(_SAFE_URL_SCHEMES)}."
        )
    return url


class GitManager:
    """
    Manages Git repository operations for inventory-data synchronisation.

    Parameters
    ----------
    data_dir : str | Path
        Directory that IS (or will become) the git repository.
    repo_url : str, optional
        Remote URL.  Falls back to ``GIT_REPO_URL`` env var.
    branch : str
        Branch name.  Falls back to ``GIT_BRANCH`` env var (default ``main``).
    auth_method : str, optional
        ``"PAT"``, ``"SSH"``, ``"APP"``, or ``"BASIC"``.
        Falls back to ``GIT_AUTH_METHOD``.
    token : str, optional
        PAT / App token, or password for BASIC auth.
        Falls back to ``GIT_TOKEN`` env var.
    username : str, optional
        Username for BASIC auth.  Falls back to ``GIT_USERNAME`` env var.
    git_user_name : str
        Name used for git commits (``user.name``).
    git_user_email : str
        Email used for git commits (``user.email``).
    """

    def __init__(
        self,
        data_dir: str | Path,
        repo_url: Optional[str] = None,
        branch: Optional[str] = None,
        auth_method: Optional[str] = None,
        token: Optional[str] = None,
        username: Optional[str] = None,
        git_user_name: Optional[str] = None,
        git_user_email: Optional[str] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.repo_url = repo_url or os.environ.get("GIT_REPO_URL", "")
        self.branch = branch or os.environ.get("GIT_BRANCH", "main")
        self.auth_method = (auth_method or os.environ.get("GIT_AUTH_METHOD", "PAT")).upper()
        self.token = token or os.environ.get("GIT_TOKEN", "")
        self.username = username or os.environ.get("GIT_USERNAME", "")
        self.git_user_name = git_user_name or os.environ.get("GIT_USER_NAME", "Brainmaze Bot")
        self.git_user_email = git_user_email or os.environ.get("GIT_USER_EMAIL", "brainmaze@lab.local")
        self._git_crypt_unlocked = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(
        self,
        cmd: list[str],
        extra_env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
    ) -> Tuple[int, str, str]:
        """Run a subprocess command and return ``(returncode, stdout, stderr)``."""
        env = {**os.environ}
        if self.auth_method == "SSH":
            allow_insecure = os.environ.get("GIT_ALLOW_INSECURE_SSH", "").lower() in _TRUTHY_ENV
            known_hosts = os.environ.get("GIT_SSH_KNOWN_HOSTS", "").strip()
            ssh_cmd = ["ssh", "-o", "BatchMode=yes"]
            if allow_insecure:
                ssh_cmd.extend(["-o", "StrictHostKeyChecking=no"])
            else:
                ssh_cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
                if known_hosts:
                    ssh_cmd.extend(["-o", f"UserKnownHostsFile={known_hosts}"])
            env["GIT_SSH_COMMAND"] = " ".join(ssh_cmd)
        if extra_env:
            env.update(extra_env)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd or self.data_dir),
            env=env,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def _authenticated_url(self) -> str:
        """Build an authenticated remote URL for the current auth method."""
        if not self.repo_url:
            return ""
        if self.auth_method in ("PAT", "APP") and self.token:
            from urllib.parse import quote as _quote
            parsed = urlparse(self.repo_url)
            if parsed.scheme in ("http", "https"):
                token = _quote(self.token, safe="")
                netloc = f"{token}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urlunparse(parsed._replace(netloc=netloc, scheme="https"))
        if self.auth_method == "BASIC" and self.username and self.token:
            from urllib.parse import quote as _quote
            parsed = urlparse(self.repo_url)
            if parsed.scheme in ("http", "https"):
                user = _quote(self.username, safe="")
                pwd  = _quote(self.token,    safe="")
                netloc = f"{user}:{pwd}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urlunparse(parsed._replace(netloc=netloc, scheme="https"))
        # SSH or no credentials → return URL unchanged
        return self.repo_url

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # Repository inspection
    # ------------------------------------------------------------------

    def is_git_repo(self) -> bool:
        """Return True if ``data_dir`` is already a git repository."""
        return (self.data_dir / ".git").exists()

    def get_status(self) -> Dict:
        """
        Return a dictionary describing the current repository state.

        Keys: ``initialized``, ``branch``, ``has_changes``, ``changes``,
              ``recent_commits``, ``remote_url``, ``message``.
        """
        if not self.is_git_repo():
            return {
                "initialized": False,
                "message": "Not a git repository. Use 'Init Repo' to get started.",
            }

        _, short, _ = self._run(["git", "status", "--short"])
        changes = [ln for ln in short.splitlines() if ln.strip()]

        _, branch, _ = self._run(["git", "branch", "--show-current"])
        _, log, _ = self._run(["git", "log", "--oneline", "-7"])
        recent = [ln for ln in log.splitlines() if ln.strip()]

        return {
            "initialized": True,
            "branch": branch or self.branch,
            "has_changes": bool(changes),
            "changes": changes,
            "recent_commits": recent,
            "remote_url": self.repo_url or "Not configured",
            "message": "OK",
        }

    # ------------------------------------------------------------------
    # Repository setup
    # ------------------------------------------------------------------

    def init_repo(self) -> Tuple[bool, str]:
        """Initialise a new git repository in ``data_dir``."""
        if self.is_git_repo():
            return True, "Repository already initialised."

        branch = _safe_branch(self.branch)
        # Try git >= 2.28 (supports --initial-branch)
        code, _, err = self._run(["git", "init", f"--initial-branch={branch}"])
        if code != 0:
            code, _, err = self._run(["git", "init"])
        if code != 0:
            return False, f"git init failed: {err}"

        self._run(["git", "config", "user.name",  _safe_git_config_value(self.git_user_name)])
        self._run(["git", "config", "user.email", _safe_git_config_value(self.git_user_email)])
        self._ensure_gitignore()
        return True, f"Repository initialised at {self.data_dir}"

    def setup_remote(self) -> Tuple[bool, str]:
        """Configure the ``origin`` remote (replaces any existing one)."""
        auth_url = _safe_url(self._authenticated_url())
        if not auth_url:
            return False, "No repository URL configured."

        self._run(["git", "remote", "remove", "origin"])
        code, _, err = self._run(["git", "remote", "add", "origin", auth_url])
        if code == 0:
            return True, "Remote 'origin' configured."
        return False, f"Failed to add remote: {err}"

    def _ensure_gitignore(self) -> None:
        path = self.data_dir / ".gitignore"
        if not path.exists():
            path.write_text("*.tmp\n*.bak\n.DS_Store\n__pycache__/\n")

    # ------------------------------------------------------------------
    # Core git operations
    # ------------------------------------------------------------------

    def commit_all(self, message: Optional[str] = None) -> Tuple[bool, str]:
        """Stage and commit every change inside ``data_dir``."""
        if not self.is_git_repo():
            ok, msg = self.init_repo()
            if not ok:
                return False, msg

        self._ensure_gitignore()
        self._run(["git", "config", "user.name",  _safe_git_config_value(self.git_user_name)])
        self._run(["git", "config", "user.email", _safe_git_config_value(self.git_user_email)])
        self._run(["git", "add", "."])

        commit_msg = _safe_commit_msg(message or f"Inventory update {self._utc_now()}")
        code, out, err = self._run(["git", "commit", "-m", commit_msg])
        if code == 0:
            return True, f"Committed: {commit_msg}"
        combined = (out + err).lower()
        if "nothing to commit" in combined:
            return True, "Working directory clean – nothing to commit."
        return False, f"Commit failed: {err or out}"

    def push(self, force: bool = False) -> Tuple[bool, str]:
        """Push local commits to the remote ``origin``."""
        if not self.repo_url:
            return False, "No remote repository configured."

        auth_url = _safe_url(self._authenticated_url())
        self._run(["git", "remote", "set-url", "origin", auth_url])

        cmd = ["git", "push", "-u", "origin", _safe_branch(self.branch)]
        if force:
            cmd.append("--force")
        code, out, err = self._run(cmd)
        if code == 0:
            return True, f"Pushed to {self.repo_url} on branch '{self.branch}'."
        return False, f"Push failed: {err or out}"

    def pull(self) -> Tuple[bool, str]:
        """Pull and rebase the latest changes from ``origin``."""
        if not self.repo_url:
            return False, "No remote repository configured."

        auth_url = _safe_url(self._authenticated_url())
        self._run(["git", "remote", "set-url", "origin", auth_url])
        code, out, err = self._run(["git", "pull", "--rebase", "origin", _safe_branch(self.branch)])
        if code == 0:
            return True, f"Pulled from '{self.repo_url}'."
        return False, f"Pull failed: {err or out}"

    def sync(self, commit_message: Optional[str] = None) -> Tuple[bool, str]:
        """Commit all local changes, pull (rebase), then push."""
        ok, msg = self.commit_all(commit_message)
        if not ok:
            return False, f"Commit step failed: {msg}"

        ok, msg = self.pull()
        if not ok:
            logger.warning("Pull step failed (may be a brand-new remote branch): %s", msg)

        ok, msg = self.push()
        return ok, msg

    # ------------------------------------------------------------------
    # git-crypt
    # ------------------------------------------------------------------

    def unlock_git_crypt(self, key_b64: Optional[str] = None) -> Tuple[bool, str]:
        """
        Unlock a git-crypt encrypted repository.

        The symmetric key should be supplied as a Base64-encoded string
        either via ``key_b64`` or the ``GIT_CRYPT_KEY`` environment variable.
        """
        b64 = key_b64 or os.environ.get("GIT_CRYPT_KEY", "")
        if not b64:
            return False, "No git-crypt key provided. Set GIT_CRYPT_KEY env var."

        try:
            key_bytes = base64.b64decode(b64)
        except Exception as exc:
            return False, f"Failed to decode Base64 key: {exc}"

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".key")
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(key_bytes)
            code, _, err = self._run(["git-crypt", "unlock", tmp_path])
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if code == 0:
            self._git_crypt_unlocked = True
            return True, "git-crypt unlocked successfully."
        return False, f"git-crypt unlock failed: {err}"
