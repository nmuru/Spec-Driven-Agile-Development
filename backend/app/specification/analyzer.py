"""Orchestration for the intent-to-build-specification workflow.

This module is deliberately separate from the legacy SDLC analyzer. Specify is not
another SDLC documentation phase: it turns human intent into an implementation
specification through dedicated reasoning roles.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Optional

from ..agent_runner import run_specification_agent
from ..cancellable_clone import clone_repository
from ..repository_intelligence import collect_repository_intelligence
from ..run_control import RunControl


SPECIFICATION_AGENTS = [
    ("intent-analyst", "Intent Analyst"),
    ("specification-architect", "Specification Architect"),
    ("specification-reviewer", "Specification Reviewer"),
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
    """Turn user intent into one coherent specification through dedicated agents."""
    if not intent or not intent.strip():
        raise ValueError("intent cannot be empty")
    if not repo_url or not repo_url.strip():
        raise ValueError("repo_url cannot be empty")

    run_id = output_run_dir.name or uuid.uuid4().hex
    output_run_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="specification-") as tmp:
        repository = clone_repository(repo_url, Path(tmp), run_control=run_control)
        intelligence = collect_repository_intelligence(repository)
        repository_context = (
            "DETERMINISTIC REPOSITORY CONTEXT\\n\\n"
            + intelligence.to_json()
        )

        outputs: dict[str, str] = {}
        previous = None
        for agent_key, agent_name in SPECIFICATION_AGENTS:
            result, actual_model = run_specification_agent(
                agent=agent_key,
                agent_name=agent_name,
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
            outputs[agent_key] = result
            previous = result
            agent_dir = output_run_dir / agent_key
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "output.md").write_text(result, encoding="utf-8")
            (agent_dir / "model.txt").write_text(actual_model, encoding="utf-8")

        return {
            "run_id": run_id,
            "intent_analysis": outputs["intent-analyst"],
            "specification": outputs["specification-architect"],
            "review": outputs["specification-reviewer"],
        }
