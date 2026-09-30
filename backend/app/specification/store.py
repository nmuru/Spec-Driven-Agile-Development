"""Durable storage for approved sprint specifications.

The active analysis workspace remains transient under output-content/. This
store contains only human-approved specification artifacts and their lifecycle
state. Approved files are overwritten in place during an active sprint; once
closed, they are immutable.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlparse

from ..config import settings


SPECIFICATION_PHASE_FILES = {
    "scope": "scope.md",
    "business-requirements": "business-requirements.md",
    "software-requirements": "software-requirements.md",
    "design": "design.md",
    "tasks": "tasks.md",
    "review": "specification.md",
}

SPECIFICATION_PHASES = tuple(SPECIFICATION_PHASE_FILES)
_store_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return value[:120] or "project"


class SpecificationStore:
    def __init__(self, root: Path | None = None) -> None:
        configured = root or Path(settings.spec_output_dir)
        self.root = configured if configured.is_absolute() else Path(__file__).resolve().parents[2] / configured
        self.root.mkdir(parents=True, exist_ok=True)

    def project_id(self, repo_url: str) -> str:
        parsed = urlparse(repo_url.strip())
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            owner = parts[0]
            repo = parts[1].removesuffix(".git")
            return _safe_slug(f"{owner}-{repo}")
        host = parsed.hostname or "repository"
        return _safe_slug(host)

    def project_dir(self, project_id: str) -> Path:
        return self.root / _safe_slug(project_id)

    def _sprint_dir(self, project_id: str, sprint_id: str) -> Path:
        return self.project_dir(project_id) / _safe_slug(sprint_id)

    def _state_path(self, project_id: str, sprint_id: str) -> Path:
        return self._sprint_dir(project_id, sprint_id) / "sprint-state.json"

    def _read_state(self, project_id: str, sprint_id: str) -> dict:
        path = self._state_path(project_id, sprint_id)
        if not path.is_file():
            raise FileNotFoundError(f"Sprint does not exist: {project_id}/{sprint_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_state(self, project_id: str, sprint_id: str, state: dict) -> None:
        path = self._state_path(project_id, sprint_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(path)

    def _sprint_numbers(self, project_id: str) -> list[int]:
        project = self.project_dir(project_id)
        if not project.is_dir():
            return []
        numbers: list[int] = []
        for path in project.iterdir():
            match = re.fullmatch(r"sprint-(\d+)", path.name)
            if match and path.is_dir():
                numbers.append(int(match.group(1)))
        return sorted(numbers)

    def get_or_create_active_sprint(self, repo_url: str, intent: str) -> dict:
        project_id = self.project_id(repo_url)
        with _store_lock:
            project = self.project_dir(project_id)
            project.mkdir(parents=True, exist_ok=True)
            (project / "document").mkdir(parents=True, exist_ok=True)

            for number in reversed(self._sprint_numbers(project_id)):
                sprint_id = f"sprint-{number:03d}"
                try:
                    state = self._read_state(project_id, sprint_id)
                except (OSError, json.JSONDecodeError):
                    continue
                if state.get("status") == "active":
                    return state

            next_number = (self._sprint_numbers(project_id) or [0])[-1] + 1
            sprint_id = f"sprint-{next_number:03d}"
            sprint_dir = self._sprint_dir(project_id, sprint_id)
            sprint_dir.mkdir(parents=True, exist_ok=False)
            state = {
                "project_id": project_id,
                "sprint_id": sprint_id,
                "repo_url": repo_url,
                "status": "active",
                "created_at": _utc_now(),
                "closed_at": None,
                "specification_version": 0,
                "approved_phases": [],
            }
            (sprint_dir / "intent.md").write_text(intent.strip() + "\n", encoding="utf-8")
            self._write_state(project_id, sprint_id, state)
            return state

    def approve_phase(self, project_id: str, sprint_id: str, phase: str, content: str) -> dict:
        if phase not in SPECIFICATION_PHASE_FILES:
            raise ValueError(f"Unknown specification phase: {phase}")
        if not content.strip():
            raise ValueError("Approved specification content cannot be empty.")

        with _store_lock:
            state = self._read_state(project_id, sprint_id)
            if state.get("status") != "active":
                raise ValueError("This sprint specification is closed and immutable.")

            sprint_dir = self._sprint_dir(project_id, sprint_id)
            target = sprint_dir / SPECIFICATION_PHASE_FILES[phase]
            temp = target.with_suffix(".tmp")
            temp.write_text(content.strip() + "\n", encoding="utf-8")
            temp.replace(target)

            approved = list(state.get("approved_phases", []))
            if phase not in approved:
                approved.append(phase)
            state["approved_phases"] = [item for item in SPECIFICATION_PHASES if item in approved]
            self._write_state(project_id, sprint_id, state)
            return state

    def get_sprint(self, project_id: str, sprint_id: str, include_content: bool = True) -> dict:
        with _store_lock:
            state = self._read_state(project_id, sprint_id)
            result = dict(state)
            if include_content:
                contents: dict[str, str] = {}
                sprint_dir = self._sprint_dir(project_id, sprint_id)
                intent = sprint_dir / "intent.md"
                if intent.is_file():
                    contents["intent"] = intent.read_text(encoding="utf-8")
                for phase, filename in SPECIFICATION_PHASE_FILES.items():
                    path = sprint_dir / filename
                    if path.is_file():
                        contents[phase] = path.read_text(encoding="utf-8")
                result["contents"] = contents
            return result

    def list_projects(self) -> list[str]:
        return sorted(path.name for path in self.root.iterdir() if path.is_dir())

    def list_sprints(self, project_id: str) -> list[dict]:
        result = []
        for number in self._sprint_numbers(project_id):
            sprint_id = f"sprint-{number:03d}"
            try:
                result.append(self._read_state(project_id, sprint_id))
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def close_sprint(self, project_id: str, sprint_id: str) -> dict:
        with _store_lock:
            state = self._read_state(project_id, sprint_id)
            if state.get("status") != "active":
                return state

            missing = [phase for phase in SPECIFICATION_PHASES if phase not in state.get("approved_phases", [])]
            if missing:
                raise ValueError("All specification phases must be approved before closing the sprint: " + ", ".join(missing))

            state["status"] = "closed"
            state["closed_at"] = _utc_now()
            state["specification_version"] = 1
            self._write_state(project_id, sprint_id, state)
            return state

    def read_phase(self, project_id: str, sprint_id: str, phase: str) -> str | None:
        if phase == "intent":
            filename = "intent.md"
        else:
            filename = SPECIFICATION_PHASE_FILES.get(phase)
        if not filename:
            return None
        path = self._sprint_dir(project_id, sprint_id) / filename
        return path.read_text(encoding="utf-8") if path.is_file() else None
