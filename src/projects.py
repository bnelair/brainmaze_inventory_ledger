"""
Multi-Project Registry for Brainmaze Inventory Ledger.

Each project gets its own sub-directory under ``data/projects/<slug>/``
containing an ``events.jsonl`` ledger and a ``schema.yaml`` configuration.

The registry of all projects is kept in ``data/projects.yaml``.

Backward-compatibility
----------------------
If the legacy single-project layout is detected (``data/events.jsonl`` at the
root level), the first call to ``list_projects()`` will automatically migrate
that data into a project called "Default Inventory".
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from ulid import ULID

# ---------------------------------------------------------------------------
# Default schema applied when a new project is created
# ---------------------------------------------------------------------------
_DEFAULT_SCHEMA: Dict[str, Any] = {
    "schema_version": "1.0",
    "category_options": [
        "Reagent",
        "Equipment",
        "Consumable",
        "Chemical",
        "Biological",
        "Safety",
        "Administrative",
        "Other",
    ],
    "location_options": [
        "Freezer -20°C",
        "Freezer -80°C",
        "Fridge 4°C",
        "Room Temperature",
        "Shelf A",
        "Shelf B",
        "Cabinet",
        "Other",
    ],
    # custom_fields is a list of dicts:
    # {name, label, type: text|number|select|checkbox, required, default, options}
    "custom_fields": [],
}

# Slug: lowercase letters, digits, and hyphens; 2-64 chars, must start/end
# with an alphanumeric character
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}[a-z0-9]$")


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"[\s]+", "-", s.strip())
    s = s[:62]
    s = s.strip("-") or "project"
    return s


class ProjectManager:
    """
    Manages the project registry and per-project schema/data directories.

    Parameters
    ----------
    data_dir : str | Path
        Root data directory (the same one AuthManager uses).
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.projects_file = self.data_dir / "projects.yaml"
        self.projects_dir = self.data_dir / "projects"
        self._bootstrap()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        if not self.projects_file.exists():
            self.projects_file.write_text(
                "projects: []\n", encoding="utf-8"
            )
        # Migrate legacy single-project layout if needed
        self._maybe_migrate_legacy()

    def _load_registry(self) -> List[Dict[str, Any]]:
        raw = yaml.safe_load(self.projects_file.read_text(encoding="utf-8")) or {}
        return raw.get("projects", [])

    def _save_registry(self, projects: List[Dict[str, Any]]) -> None:
        raw = yaml.safe_load(self.projects_file.read_text(encoding="utf-8")) or {}
        raw["projects"] = projects
        self.projects_file.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _new_id() -> str:
        return str(ULID())

    def _project_dir(self, project_id: str) -> Path:
        projects = self._load_registry()
        for p in projects:
            if p.get("id") == project_id:
                return self.projects_dir / p["slug"]
        raise KeyError(f"Project '{project_id}' not found.")

    # ------------------------------------------------------------------
    # Legacy migration
    # ------------------------------------------------------------------

    def _maybe_migrate_legacy(self) -> None:
        """
        If ``data/events.jsonl`` exists (old single-project layout) and no
        projects are registered yet, move the data into a "Default Inventory"
        project.
        """
        legacy_events = self.data_dir / "events.jsonl"
        legacy_schema = self.data_dir / "schema.yaml"

        if not legacy_events.exists():
            return
        if self._load_registry():
            return  # already migrated

        proj_id = self._new_id()
        slug = "default-inventory"
        proj_dir = self.projects_dir / slug
        proj_dir.mkdir(parents=True, exist_ok=True)

        # Move events and schema
        shutil.copy2(legacy_events, proj_dir / "events.jsonl")
        legacy_events.rename(legacy_events.with_suffix(".jsonl.migrated"))

        if legacy_schema.exists():
            shutil.copy2(legacy_schema, proj_dir / "schema.yaml")
            legacy_schema.rename(legacy_schema.with_suffix(".yaml.migrated"))

        self._save_registry([{
            "id":          proj_id,
            "name":        "Default Inventory",
            "slug":        slug,
            "description": "Migrated from single-project layout.",
            "created_by":  "system",
            "created_at":  self._now(),
        }])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_projects(self) -> List[Dict[str, Any]]:
        return self._load_registry()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        for p in self._load_registry():
            if p.get("id") == project_id:
                return p
        return None

    def create_project(
        self,
        name: str,
        description: str = "",
        created_by: str = "admin",
    ) -> Tuple[Dict[str, Any], str]:
        """
        Create a new project.  Returns ``(project_dict, error_message)``.
        ``error_message`` is empty on success.
        """
        if not name.strip():
            return {}, "Project name cannot be empty."

        slug = _slugify(name)
        projects = self._load_registry()

        # Ensure unique slug; truncate base to leave room for the numeric suffix
        # so the combined slug never exceeds _SLUG_RE's 64-char limit.
        existing_slugs = {p["slug"] for p in projects}
        base_slug, n = slug, 1
        while slug in existing_slugs:
            suffix = f"-{n}"
            # _SLUG_RE requires ending with alnum, so we truncate at 64 - len(suffix)
            max_base = 64 - len(suffix)
            slug = f"{base_slug[:max_base].rstrip('-')}{suffix}"
            n += 1

        # Validate final slug (guard against edge-case names that produce an invalid slug)
        if not _SLUG_RE.match(slug):
            return {}, (
                f"Could not generate a valid project slug from '{name}'. "
                "Please use a name containing at least two alphanumeric characters."
            )

        proj_id = self._new_id()
        proj_dir = self.projects_dir / slug
        proj_dir.mkdir(parents=True, exist_ok=True)

        # Write default schema
        schema_path = proj_dir / "schema.yaml"
        schema = dict(_DEFAULT_SCHEMA)
        schema["project_name"] = name.strip()
        schema["description"] = description.strip()
        schema_path.write_text(
            yaml.dump(schema, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        record: Dict[str, Any] = {
            "id":          proj_id,
            "name":        name.strip(),
            "slug":        slug,
            "description": description.strip(),
            "created_by":  created_by,
            "created_at":  self._now(),
        }
        projects.append(record)
        self._save_registry(projects)
        return record, ""

    def rename_project(
        self, project_id: str, new_name: str
    ) -> Tuple[bool, str]:
        if not new_name.strip():
            return False, "Name cannot be empty."
        projects = self._load_registry()
        for p in projects:
            if p.get("id") == project_id:
                p["name"] = new_name.strip()
                # Update name in schema too
                schema = self.get_schema(project_id)
                schema["project_name"] = new_name.strip()
                self.save_schema(project_id, schema)
                self._save_registry(projects)
                return True, f"Project renamed to '{new_name}'."
        return False, f"Project '{project_id}' not found."

    def delete_project(self, project_id: str) -> Tuple[bool, str]:
        projects = self._load_registry()
        target = next((p for p in projects if p.get("id") == project_id), None)
        if not target:
            return False, f"Project '{project_id}' not found."
        if len(projects) <= 1:
            return False, "Cannot delete the last project."

        proj_dir = self.projects_dir / target["slug"]
        if proj_dir.exists():
            shutil.rmtree(proj_dir)

        remaining = [p for p in projects if p.get("id") != project_id]
        self._save_registry(remaining)
        return True, f"Project '{target['name']}' deleted."

    # ------------------------------------------------------------------
    # Per-project data helpers
    # ------------------------------------------------------------------

    def get_project_data_dir(self, project_id: str) -> Path:
        """Return the data directory for a specific project."""
        return self._project_dir(project_id)

    def get_schema(self, project_id: str) -> Dict[str, Any]:
        schema_path = self._project_dir(project_id) / "schema.yaml"
        if not schema_path.exists():
            return dict(_DEFAULT_SCHEMA)
        raw = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        # Ensure required keys
        for k, v in _DEFAULT_SCHEMA.items():
            raw.setdefault(k, v)
        return raw

    def save_schema(self, project_id: str, schema: Dict[str, Any]) -> None:
        schema_path = self._project_dir(project_id) / "schema.yaml"
        schema_path.write_text(
            yaml.dump(schema, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
