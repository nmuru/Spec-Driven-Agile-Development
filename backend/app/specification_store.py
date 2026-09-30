"""Durable storage for approved sprint specifications."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlparse

from .config import settings

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
    """Store project artifacts under <project-folder>/<product>/spec_output."""

    def __init__(
        self,
        project_folder: str | Path | None = None,
        product_name: str | None = None,
        root: Path | None = None,
    ) -> None:
        if root is not None:
            self.root = root
        elif project_folder and product_name:
            self.root = Path(project_folder).expanduser().resolve() / _safe_slug(product_name) / "spec_output"
        else:
            configured = Path(settings.spec_output_dir)
            self.root = configured if configured.is_absolute() else Path(__file__).resolve().parents[2] / configured
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "repository" / "document").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def project_id(product_name: str | None, repo_url: str | None = None, intent: str | None = None) -> str:
        if product_name and product_name.strip():
            return _safe_slug(product_name)
        if repo_url and repo_url.strip():
            parsed = urlparse(repo_url.strip())
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(parts) >= 2:
                return _safe_slug(f"{parts[0]}-{parts[1].removesuffix('.git')}")
        digest = hashlib.sha256((intent or "").strip().encode("utf-8")).hexdigest()[:12]
        return f"intent-{digest}"

    def project_dir(self, project_id: str) -> Path:
        return self.root

    def _sprint_dir(self, project_id: str, sprint_id: str) -> Path:
        return self.root / _safe_slug(sprint_id)

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
        numbers: list[int] = []
        for path in self.root.iterdir():
            match = re.fullmatch(r"sprint-(\d+)", path.name)
            if match and path.is_dir():
                numbers.append(int(match.group(1)))
        return sorted(numbers)

    def get_or_create_active_sprint(
        self,
        repo_url: str | None,
        intent: str,
        product_name: str | None = None,
    ) -> dict:
        project_id = self.project_id(product_name, repo_url, intent)
        with _store_lock:
            for number in reversed(self._sprint_numbers(project_id)):
                sprint_id = f"sprint-{number:03d}"
                try:
                    state = self._read_state(project_id, sprint_id)
                except (OSError, json.JSONDecodeError):
                    continue
                if state.get("status") == "active":
                    existing_intent = self._sprint_dir(project_id, sprint_id) / "intent.md"
                    if existing_intent.is_file():
                        current_intent = existing_intent.read_text(encoding="utf-8").strip()
                        if current_intent != intent.strip():
                            raise ValueError(
                                f"An active sprint already exists for {project_id}/{sprint_id} with a different Intent. "
                                "Complete or close that sprint before starting a new Intent."
                            )
                    return state

            next_number = (self._sprint_numbers(project_id) or [0])[-1] + 1
            sprint_id = f"sprint-{next_number:03d}"
            sprint_dir = self._sprint_dir(project_id, sprint_id)
            sprint_dir.mkdir(parents=True, exist_ok=False)
            state = {
                "project_id": project_id,
                "sprint_id": sprint_id,
                "product_name": product_name or project_id,
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
            target = self._sprint_dir(project_id, sprint_id) / SPECIFICATION_PHASE_FILES[phase]
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
        return [self.root.parent.name]

    def list_sprints(self, project_id: str) -> list[dict]:
        result: list[dict] = []
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
            missing = [
                phase for phase in SPECIFICATION_PHASES
                if phase not in state.get("approved_phases", [])
            ]
            if missing:
                raise ValueError(
                    "All specification phases must be approved before closing the sprint: "
                    + ", ".join(missing)
                )
            state["status"] = "closed"
            state["closed_at"] = _utc_now()
            state["specification_version"] = 1
            self._write_state(project_id, sprint_id, state)
            return state

    def read_phase(self, project_id: str, sprint_id: str, phase: str) -> str | None:
        filename = "intent.md" if phase == "intent" else SPECIFICATION_PHASE_FILES.get(phase)
        if not filename:
            return None
        path = self._sprint_dir(project_id, sprint_id) / filename
        return path.read_text(encoding="utf-8") if path.is_file() else None
