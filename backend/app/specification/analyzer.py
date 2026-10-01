"""Orchestration for the phase-based Specify workflow.

Intent is a human-authored root artifact. The specification is progressively
derived through editable communication phases that mirror the SDLC engine pattern.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Optional

from ..agent_runner import run_specification_agent
from ..cancellable_clone import clone_repository
from ..repository_intelligence import collect_repository_intelligence
from ..run_control import RunControl
from ..specification_store import SpecificationStore


SPECIFICATION_PHASES = [
    ("scope", "Scope"),
    ("business-requirements", "Business Requirements"),
    ("software-requirements", "Software Requirements"),
    ("technology", "Technology Architecture"),
    ("design", "Design"),
    ("tasks", "Implementation Tasks"),
]


def analyze_specification(
    *,
    intent: str,
    repo_url: str | None,
    output_run_dir: Path,
    product_name: str | None = None,
    project_folder: str | None = None,
    provider: str,
    model: str,
    api_key: str,
    run_control: Optional[RunControl] = None,
    on_phase_complete=None,
    phase_key: str | None = None,
    existing_project_id: str | None = None,
    existing_sprint_id: str | None = None,
    sprint_mode: str = "new",
) -> dict:
    """Turn technical intent into a human-editable, implementation-ready specification."""
    if not intent or not intent.strip():
        raise ValueError("intent cannot be empty")

    run_id = output_run_dir.name or uuid.uuid4().hex
    output_run_dir.mkdir(parents=True, exist_ok=True)
    (output_run_dir / "intent.md").write_text(intent.strip(), encoding="utf-8")

    # Durable sprint state is separate from the transient run workspace.
    store = SpecificationStore(project_folder=project_folder, product_name=product_name) if (project_folder and product_name) else SpecificationStore()
    if existing_project_id and existing_sprint_id:
        sprint_state = store.get_sprint(existing_project_id, existing_sprint_id, include_content=True)
        if sprint_state.get("status") != "active":
            raise ValueError("This sprint specification is closed and immutable.")
        project_id = existing_project_id
        sprint_id = existing_sprint_id
    elif sprint_mode == "existing":
        project_id = store.project_id(repo_url, intent, product_name)
        sprint_state = store.get_latest_sprint(project_id)
        if sprint_state is None:
            raise ValueError("No existing sprint was found for this product. Select New Sprint.")
        if sprint_state.get("status") != "active":
            raise ValueError("The latest sprint is already closed. Select New Sprint.")
        sprint_id = sprint_state["sprint_id"]
    elif sprint_mode == "new":
        sprint_state = store.get_or_create_active_sprint(repo_url, intent, product_name=product_name)
        project_id = sprint_state["project_id"]
        sprint_id = sprint_state["sprint_id"]
    else:
        raise ValueError("sprint_mode must be 'existing' or 'new'")
    (store._sprint_dir(project_id, sprint_id) / "intent.md").write_text(intent.strip() + "\n", encoding="utf-8")
    sprint_state = store.get_sprint(project_id, sprint_id, include_content=True)
    (output_run_dir / "specification-context.json").write_text(
        __import__("json").dumps({"project_id": project_id, "sprint_id": sprint_id}, indent=2),
        encoding="utf-8",
    )

    with tempfile.TemporaryDirectory(prefix="specification-") as tmp:
        repository = Path(tmp)
        project_context = store.read_project_document() if (project_folder and product_name) else "NO project.md context was supplied by the direct test/in-process caller."
        if repo_url:
            repository = clone_repository(repo_url, repository, run_control=run_control)
            intelligence = collect_repository_intelligence(repository)
            repository_context = (
                "DETERMINISTIC REPOSITORY CONTEXT\n\n" + intelligence.to_json()
            )
        else:
            repository_context = (
                "NO REPOSITORY WAS PROVIDED. Derive the specification from project.md, Intent, "
                "and prior specification outputs only. Do not invent repository-specific "
                "technology or implementation details."
            )

        outputs: dict[str, str] = {}
        phases_to_run = SPECIFICATION_PHASES
        if phase_key:
            matching = [item for item in SPECIFICATION_PHASES if item[0] == phase_key]
            if not matching:
                raise ValueError(f"Unknown specification phase: {phase_key}")
            phases_to_run = matching

        prior_contents = sprint_state.get("contents", {})
        if phase_key:
            phase_keys = [item[0] for item in SPECIFICATION_PHASES]
            phase_index = phase_keys.index(phase_key)
            approved = set(sprint_state.get("approved_phases", []))
            if phase_index > 0 and phase_keys[phase_index - 1] not in approved:
                raise ValueError(f"Approve '{phase_keys[phase_index - 1]}' before generating '{phase_key}'.")
            if phase_key in approved:
                raise ValueError(f"Specification phase '{phase_key}' is already approved.")
        previous_parts = []
        for prior_key, _ in SPECIFICATION_PHASES:
            if prior_key == phase_key:
                break
            if prior_key in prior_contents:
                previous_parts.append(f"APPROVED {prior_key.upper()}\n\n{prior_contents[prior_key]}")
        previous = "\n\n".join(previous_parts) or None

        for phase_key, phase_name in phases_to_run:
            if run_control is not None:
                run_control.phase_started(phase_key)
            result, actual_model = run_specification_agent(
                agent=phase_key,
                agent_name=phase_name,
                repository=repository,
                intent=intent.strip(),
                repository_context=(
                    "PROJECT CONTEXT FROM project.md\n\n"
                    + project_context
                    + "\n\n"
                    + repository_context
                ),
                previous_output=previous,
                provider=provider,
                model=model,
                api_key=api_key,
                output_run_dir=output_run_dir,
                run_control=run_control,
            )
            outputs[phase_key] = result
            previous = result

            phase_dir = output_run_dir / phase_key
            phase_dir.mkdir(parents=True, exist_ok=True)
            (phase_dir / "output.md").write_text(result, encoding="utf-8")
            (phase_dir / "model.txt").write_text(actual_model, encoding="utf-8")
            if run_control is not None:
                run_control.phase_completed(phase_key)

            if on_phase_complete is not None:
                on_phase_complete({
                    "phase": phase_key,
                    "phase_name": phase_name,
                    "raw_analysis": result,
                    "raw_path": str(phase_dir / "output.md"),
                    "run_id": run_id,
                    "project_id": project_id,
                    "sprint_id": sprint_id,
                    "provenance": {
                        "workflow": "specification",
                        "intent": intent.strip(),
                        "project_id": project_id,
                        "sprint_id": sprint_id,
                    },
                })

        return {
            "run_id": run_id,
            "project_id": project_id,
            "sprint_id": sprint_id,
            "intent": intent.strip(),
            "scope": outputs.get("scope", ""),
            "business_requirements": outputs.get("business-requirements", ""),
            "software_requirements": outputs.get("software-requirements", ""),
            "technology": outputs.get("technology", ""),
            "design": outputs.get("design", ""),
            "tasks": outputs.get("tasks", ""),
            "specification": outputs.get("tasks", ""),
        }
