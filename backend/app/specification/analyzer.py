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


SPECIFICATION_PHASES = [
    ("scope", "Scope"),
    ("business-requirements", "Business Requirements"),
    ("software-requirements", "Software Requirements Specification"),
    ("design", "Design"),
    ("tasks", "Implementation Tasks"),
    ("review", "Specification Review"),
]


def analyze_specification(
    *,
    intent: str,
    repo_url: str,
    output_run_dir: Path,
    provider: str,
    model: str,
    api_key: str,
    run_control: Optional[RunControl] = None,
) -> dict:
    """Turn technical intent into a human-editable, implementation-ready specification."""
    if not intent or not intent.strip():
        raise ValueError("intent cannot be empty")
    if not repo_url or not repo_url.strip():
        raise ValueError("repo_url cannot be empty")

    run_id = output_run_dir.name or uuid.uuid4().hex
    output_run_dir.mkdir(parents=True, exist_ok=True)
    (output_run_dir / "intent.md").write_text(intent.strip(), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="specification-") as tmp:
        repository = clone_repository(repo_url, Path(tmp), run_control=run_control)
        intelligence = collect_repository_intelligence(repository)
        repository_context = (
            "DETERMINISTIC REPOSITORY CONTEXT\n\n" + intelligence.to_json()
        )

        outputs: dict[str, str] = {}
        previous = None

        for phase_key, phase_name in SPECIFICATION_PHASES:
            result, actual_model = run_specification_agent(
                agent=phase_key,
                agent_name=phase_name,
                repository=repository,
                intent=intent.strip(),
                repository_context=repository_context,
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

        return {
            "run_id": run_id,
            "intent": intent.strip(),
            "scope": outputs["scope"],
            "business_requirements": outputs["business-requirements"],
            "software_requirements": outputs["software-requirements"],
            "design": outputs["design"],
            "tasks": outputs["tasks"],
            "specification": outputs["review"],
            "review": outputs["review"],
        }
