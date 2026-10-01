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
    "technology": "technology.md",
    "design": "design.md",
    "tasks": "tasks.md",
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
        elif project_folder and product_name is None and isinstance(project_folder, Path):
            self.root = project_folder
        elif project_folder and product_name:
            self.root = Path(project_folder).expanduser().resolve() / _safe_slug(product_name) / "spec_output"
        else:
            configured = Path(settings.spec_output_dir)
            self.root = configured if configured.is_absolute() else Path(__file__).resolve().parents[2] / configured
        if project_folder and product_name:
            project_dir = Path(project_folder).expanduser().resolve() / _safe_slug(product_name)
            if not project_dir.is_dir():
                raise ValueError(f"Product directory does not exist: {project_dir}")
            project_md = project_dir / "project.md"
            if not project_md.is_file():
                raise ValueError(f"Required project.md was not found: {project_md}")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "repository" / "document").mkdir(parents=True, exist_ok=True)

    def project_directory(self) -> Path:
        return self.root.parent

    def project_document(self) -> Path:
        return self.project_directory() / "project.md"

    def read_project_document(self, max_chars: int = 60000) -> str:
        path = self.project_document()
        if not path.is_file():
            raise ValueError(f"Required project.md was not found: {path}")
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]

    @staticmethod
    def project_id(repo_url: str | None, intent: str | None = None, product_name: str | None = None) -> str:
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

    def latest_sprint_id(self, project_id: str) -> str | None:
        numbers = self._sprint_numbers(project_id)
        if not numbers:
            return None
        latest_number = numbers[-1]
        candidates = [
            path for path in self.root.iterdir()
            if path.is_dir()
            and re.fullmatch(r"sprint-(\\d+)", path.name)
            and int(re.fullmatch(r"sprint-(\\d+)", path.name).group(1)) == latest_number
        ]
        if not candidates:
            return None
        return candidates[0].name

    def get_latest_sprint(self, project_id: str) -> dict | None:
        sprint_id = self.latest_sprint_id(project_id)
        if not sprint_id:
            return None
        try:
            return self._read_state(project_id, sprint_id)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None

    def reset_active_sprint(self, project_id: str, sprint_id: str, intent: str, repo_url: str | None, product_name: str | None = None) -> dict:
        with _store_lock:
            state = self._read_state(project_id, sprint_id)
            if state.get("status") != "active":
                raise ValueError("The latest sprint is already closed. Select New Sprint.")
            sprint_dir = self._sprint_dir(project_id, sprint_id)
            for path in sprint_dir.iterdir():
                if path.is_file():
                    path.unlink()
            state = {
                "project_id": project_id,
                "sprint_id": sprint_id,
                "product_name": product_name or project_id,
                "repo_url": repo_url,
                "status": "active",
                "created_at": state.get("created_at") or _utc_now(),
                "closed_at": None,
                "specification_version": 0,
                "approved_phases": [],
            }
            (sprint_dir / "intent.md").write_text(intent.strip() + "\n", encoding="utf-8")
            self._write_state(project_id, sprint_id, state)
            return state

    def get_or_create_active_sprint(
        self,
        repo_url: str | None,
        intent: str,
        product_name: str | None = None,
    ) -> dict:
        project_id = self.project_id(repo_url, intent, product_name)
        with _store_lock:
            next_number = (self._sprint_numbers(project_id) or [0])[-1] + 1
            sprint_id = f"sprint-{next_number}"
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
        paths = [
            path for path in self.root.iterdir()
            if path.is_dir() and re.fullmatch(r"sprint-(\\d+)", path.name)
        ]
        for path in sorted(paths, key=lambda item: int(re.fullmatch(r"sprint-(\\d+)", item.name).group(1))):
            try:
                result.append(self._read_state(project_id, path.name))
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
