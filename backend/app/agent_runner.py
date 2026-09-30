"""OpenAI Agents SDK phase runner for repository reverse engineering."""

import asyncio
import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import os

from agents import Agent, Runner, RunHooks, function_tool, set_tracing_export_api_key
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from .config import settings
from .run_control import RunCancelled, RunControl
from .specification_store import SPECIFICATION_PHASE_FILES, SpecificationStore

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTS_SOURCE = PROJECT_ROOT / ".agents" / "agents"
SKILLS_SOURCE = PROJECT_ROOT / ".agents" / "skills"
COMMON_AGENT_SOURCE = PROJECT_ROOT / ".agents" / "agent.md"

logger.info(
    "OpenAI tracing key loaded: %s",
    bool(settings.openai_api_key),
)

logger.info("PROJECT_ROOT=%s", PROJECT_ROOT)
logger.info("OPENAI_API_KEY loaded=%s", bool(settings.openai_api_key))
logger.info("Current working directory=%s", Path.cwd())

if settings.openai_api_key:
    set_tracing_export_api_key(settings.openai_api_key)
    logger.info("OpenAI Agents tracing export is enabled.")


class AgentRunnerError(RuntimeError):
    """Raised when a repository-analysis phase cannot be completed."""


# def github_repository_size_bytes(repo_url: str) -> int | None:
#     """Return GitHub's repository-size estimate in bytes for a public GitHub URL."""
#     parsed = urlparse(repo_url.strip())
#     if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"github.com", "www.github.com"}:
#         return None
#     parts = [part for part in parsed.path.strip("/").split("/") if part]
#     if len(parts) < 2:
#         return None
#     owner, repository = parts[0], parts[1]
#     if repository.endswith(".git"):
#         repository = repository[:-4]
#     if not owner or not repository:
#         return None
#     api_url = f"https://api.github.com/repos/{owner}/{repository}"
#     request = Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sdlc-reverse-engineer"})
#     try:
#         with urlopen(request, timeout=10) as response:
#             payload = json.loads(response.read().decode("utf-8"))
#     except HTTPError as exc:
#         if exc.code == 404:
#             raise AgentRunnerError("Could not inspect the GitHub repository before cloning. The repository may not exist or may not be publicly accessible.") from exc
#         raise AgentRunnerError(f"Could not inspect the GitHub repository before cloning: HTTP {exc.code}") from exc
#     except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
#         raise AgentRunnerError(f"Could not inspect the GitHub repository before cloning: {exc}") from exc
#     size_kib = payload.get("size")
#     if not isinstance(size_kib, int) or size_kib < 0:
#         return None
#     return size_kib * 1024


def github_repository_size_bytes(repo_url: str) -> int | None:
    """Return GitHub's repository-size estimate in bytes for a public GitHub URL."""
    parsed = urlparse(repo_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"github.com", "www.github.com"}:
        return None

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None

    owner, repository = parts[0], parts[1]

    if repository.endswith(".git"):
        repository = repository[:-4]

    if not owner or not repository:
        return None

    api_url = f"https://api.github.com/repos/{owner}/{repository}"

    logger.warning(
    "GitHub repository inspection request: repo=%s url=%s",
    f"{owner}/{repository}",
    api_url,)

    github_token = os.getenv("GITHUB_TOKEN")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sdlc-reverse-engineer",
    }
    
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    
    request = Request(api_url, headers=headers)
    
    # request = Request(
    #     api_url,
    #     headers={
    #         "Accept": "application/vnd.github+json",
    #         "User-Agent": "sdlc-reverse-engineer",
    #     },
    # )

    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        # Capture the actual response from GitHub so we can see why
        # the API returned 4xx/5xx instead of only "HTTP 403".
        try:
            response_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            response_body = "<unable to read GitHub error response>"

        response_headers = dict(exc.headers) if exc.headers else {}

        logger.error(
            "GitHub repository inspection failed: "
            "url=%s status=%s headers=%s body=%s",
            api_url,
            exc.code,
            response_headers,
            response_body,
        )

        if exc.code == 404:
            raise AgentRunnerError(
                "Could not inspect the GitHub repository before cloning. "
                "The repository may not exist or may not be publicly accessible."
            ) from exc

        raise AgentRunnerError(
            f"Could not inspect the GitHub repository before cloning: HTTP {exc.code}"
        ) from exc

    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.error(
            "GitHub repository inspection failed: url=%s error=%s",
            api_url,
            exc,
        )
        raise AgentRunnerError(
            f"Could not inspect the GitHub repository before cloning: {exc}"
        ) from exc

    size_kib = payload.get("size")

    logger.info(
    "GitHub repository inspection succeeded: repo=%s size_kib=%s",
    f"{owner}/{repository}",
    size_kib,)

    if not isinstance(size_kib, int) or size_kib < 0:
        return None

    return size_kib * 1024



def clone_repository(repo_url: str, workspace: Path) -> Path:
    """Clone a repository once for the lifetime of an analysis run."""
    repository = workspace / "target-repository"
    if repository.exists():
        shutil.rmtree(repository, ignore_errors=True)
    result = subprocess.run(["git", "clone", "--depth", "1", repo_url.strip(), str(repository)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise AgentRunnerError("Could not clone the target repository: " + result.stderr.strip()[:2000])
    return repository


def repository_size_bytes(repository: Path) -> int:
    """Return the on-disk size of the cloned repository, including Git metadata."""
    total = 0
    try:
        for path in repository.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
    except OSError as exc:
        raise AgentRunnerError(f"Could not measure cloned repository size: {exc}") from exc
    return total


def _read_common_agent_contract() -> str:
    if COMMON_AGENT_SOURCE.is_file():
        return COMMON_AGENT_SOURCE.read_text(encoding="utf-8", errors="replace")
    return ""


def _read_agent_definition(phase: str) -> str:
    if not AGENTS_SOURCE.exists():
        return ""
    candidate = AGENTS_SOURCE / f"{phase}.md"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def _read_skill(phase: str) -> str:
    """Read the phase skill methodology from the runtime-owned skills directory."""
    candidate = SKILLS_SOURCE / phase / "SKILL.md"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def _resolve_skill_resources(phase: str, output_run_dir: Path) -> dict[str, Any]:
    """Discover runtime-owned resources for a phase without reading their contents."""
    skill_dir = (SKILLS_SOURCE / phase).resolve()
    resources: dict[str, Any] = {
        "root": str(skill_dir),
        "skill": "SKILL.md",
        "artifacts": {},
        "tools": {
            "repository": ["list_files","glob","grep", "read_file", "search_repository"],
            "runtime_resources": ["list_resources", "read_resource"],
            "output_content": ["list_previous_phase_outputs", "read_previous_phase_output"],
            "spec_output": ["list_spec_projects", "list_spec_sprints", "list_specification_phases", "read_spec_output", "list_project_documents", "read_project_document"],
        },
    }
    if skill_dir.is_dir():
        for resource_path in sorted(path for path in skill_dir.rglob("*") if path.is_file()):
            relative_path = resource_path.relative_to(skill_dir).as_posix()
            if relative_path != "SKILL.md":
                resources["artifacts"][relative_path] = relative_path
    if output_run_dir.exists():
        resources["artifacts"]["output_content"] = str(output_run_dir.resolve())
    if settings.spec_output_dir:
        spec_root = Path(settings.spec_output_dir)
        spec_root = spec_root if spec_root.is_absolute() else PROJECT_ROOT / spec_root
        spec_root.mkdir(parents=True, exist_ok=True)
        resources["artifacts"]["spec_output"] = str(spec_root.resolve())
    return resources


def _format_skill_resources(resources: dict[str, Any]) -> str:
    """Render runtime resource inventory and tool identifiers as agent-facing context."""
    lines = ["RUNTIME-SUPPLIED RESOURCES", f"skill: {resources.get('skill', 'SKILL.md')}"]
    artifacts = resources.get("artifacts", {})
    resource_artifacts = {name: path for name, path in artifacts.items() if name != "output_content"}
    if resource_artifacts:
        lines.append("artifacts:")
        for name, path in resource_artifacts.items():
            lines.append(f"  {name}: {path}")
    else:
        lines.append("artifacts: none")
    if "output_content" in artifacts:
        lines.append(f"output_content: {artifacts['output_content']}")
    if "spec_output" in artifacts:
        lines.append(f"spec_output: {artifacts['spec_output']}")
    tools_manifest = resources.get("tools", {})
    if tools_manifest:
        lines.append("tools:")
        for group, names in tools_manifest.items():
            lines.append(f"  {group}: {', '.join(names)}")
    else:
        lines.append("tools: none")
    lines.extend([
        "Runtime skill resources are relative to the supplied skill resource root; use read_resource with the supplied relative path.",
        "Use list_resources when you need to discover the complete runtime resource inventory.",
        "Use repository read_file/search/list tools only for the target repository.",
        "Use output-content tools only for workflow artifacts from the current analysis run. Use spec_output tools for durable approved specifications and historical sprint context.",
        "Do not construct host filesystem paths or use repository tools to access runtime resources. Use spec_output tools to explore durable approved sprint specifications.",
    ])
    return "\n".join(lines)

def _build_tools(phase: str, repository: Path, output_run_dir: Path):
    root = repository.resolve()
    output_root = output_run_dir.resolve()
    skill_dir = (SKILLS_SOURCE / phase).resolve()
    spec_store = SpecificationStore()

    def safe_path(relative_path: str) -> Path:
        candidate = (root / relative_path).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("Path escapes repository root.")
        return candidate

    @function_tool
    def list_resources() -> str:
        """List files available in the runtime-owned resource directory for the current phase."""
        if not skill_dir.is_dir():
            return "No runtime resources are available."
        files = sorted(
            path.relative_to(skill_dir).as_posix()
            for path in skill_dir.rglob("*")
            if path.is_file()
        )
        return "\n".join(files) if files else "No runtime resources are available."

    @function_tool
    def read_resource(path: str, max_chars: int = 30000) -> str:
        """Read a file from the runtime-owned resource directory for the current phase."""
        candidate = (skill_dir / path).resolve()
        if skill_dir != candidate and skill_dir not in candidate.parents:
            return "Invalid resource path: access outside the current phase resource directory is not allowed."
        if not candidate.is_file():
            return "Runtime resource does not exist or is not a regular file."
        try:
            return candidate.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError as exc:
            return f"Could not read runtime resource: {exc}"

    @function_tool
    def list_previous_phase_outputs() -> str:
        """
        List files produced by previous SDLC phases for the current analysis run.
        Paths are relative to the current run's output-content directory.
        """
        if not output_root.exists():
            return "No previous phase outputs are available."

        if not output_root.is_dir():
            return "The current run output path is not a directory."

        files = sorted(
            path.relative_to(output_root).as_posix()
            for path in output_root.rglob("*")
            if path.is_file() and path.name != "run-state.json"
        )

        if not files:
            return "No previous phase outputs are available."

        return "\n".join(files)

    @function_tool
    def read_previous_phase_output(filename: str) -> str:
        """
        Read a specific previous-phase output file from the current analysis run.
        The filename must be one returned by list_previous_phase_outputs().
        """
        file_path = (output_root / filename).resolve()

        # Prevent path traversal outside the current run output directory.
        if output_root != file_path and output_root not in file_path.parents:
            return "Invalid filename: access outside the current run output directory is not allowed."

        if not file_path.exists():
            return f"Previous phase output not found: {filename}"

        if not file_path.is_file():
            return f"Not a file: {filename}"

        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Unable to read {filename}: {exc}"
    @function_tool
    def list_resources() -> str:
        """List files available in the current phase's runtime resource directory."""
        if not skill_dir.is_dir():
            return "No runtime resources are available."
        files = sorted(
            path.relative_to(skill_dir).as_posix()
            for path in skill_dir.rglob("*")
            if path.is_file()
        )
        return "\n".join(files) if files else "No runtime resources are available."

    @function_tool
    def read_resource(path: str, max_chars: int = 30000) -> str:
        """Read a file from the current phase's runtime resource directory."""
        resource_root = skill_dir.resolve()
        candidate = (resource_root / path).resolve()
        if resource_root != candidate and resource_root not in candidate.parents:
            return "Invalid resource path: access outside the current phase resource directory is not allowed."
        if not candidate.is_file():
            return "Runtime resource does not exist or is not a regular file."
        try:
            return candidate.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError as exc:
            return f"Could not read runtime resource: {exc}"


    @function_tool
    def list_project_documents(project_id: str) -> str:
        """List current durable SDLC document artifacts for a project."""
        project_dir = spec_store.project_dir(project_id)
        document_dir = (project_dir / "document").resolve()
        root_dir = project_dir.resolve()
        if root_dir != document_dir and root_dir not in document_dir.parents:
            return "Invalid project."
        if not document_dir.is_dir():
            return "No current document artifacts are available."
        files = sorted(path.relative_to(document_dir).as_posix() for path in document_dir.rglob("*") if path.is_file())
        return "\\n".join(files) if files else "No current document artifacts are available."

    @function_tool
    def read_project_document(project_id: str, filename: str, max_chars: int = 30000) -> str:
        """Read one current durable SDLC document artifact for a project."""
        project_dir = spec_store.project_dir(project_id).resolve()
        document_dir = (project_dir / "document").resolve()
        target = (document_dir / filename).resolve()
        if document_dir != target and document_dir not in target.parents:
            return "Invalid document path."
        if not target.is_file():
            return "Document artifact does not exist."
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError as exc:
            return f"Unable to read document artifact: {exc}"

    @function_tool
    def list_spec_projects() -> str:
        """List durable specification projects available to this application."""
        projects = spec_store.list_projects()
        return "\\n".join(projects) if projects else "No durable specification projects are available."

    @function_tool
    def list_spec_sprints(project_id: str) -> str:
        """List sprint specifications for a durable specification project."""
        try:
            sprints = spec_store.list_sprints(project_id)
        except OSError as exc:
            return f"Unable to list specification sprints: {exc}"
        if not sprints:
            return "No sprint specifications are available."
        return "\\n".join(
            f"{item['sprint_id']}: {item['status']} (approved: {', '.join(item.get('approved_phases', [])) or 'none'})"
            for item in sprints
        )

    @function_tool
    def list_specification_phases(project_id: str, sprint_id: str) -> str:
        """List available approved specification artifacts in a sprint."""
        try:
            sprint = spec_store.get_sprint(project_id, sprint_id, include_content=False)
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            return f"Specification sprint not found: {exc}"
        phases = ["intent"] + [phase for phase in SPECIFICATION_PHASE_FILES if phase in sprint.get("approved_phases", [])]
        return "\\n".join(phases) if phases else "No specification artifacts are approved yet."

    @function_tool
    def read_spec_output(project_id: str, sprint_id: str, phase: str, max_chars: int = 30000) -> str:
        """Read one durable specification artifact from a project sprint."""
        if phase != "intent" and phase not in SPECIFICATION_PHASE_FILES:
            return "Unknown specification phase."
        try:
            content = spec_store.read_phase(project_id, sprint_id, phase)
        except (FileNotFoundError, OSError) as exc:
            return f"Specification artifact could not be read: {exc}"
        if content is None:
            return "Specification artifact does not exist yet."
        return content[:max_chars]

    @function_tool
    def list_files(path: str = ".", max_entries: int = 300) -> str:
        """List repository files and directories recursively, without modifying anything."""
        target = safe_path(path)
        if not target.exists():
            return "Path does not exist."
        entries = []
        for item in target.rglob("*"):
            if ".git" in item.parts:
                continue
            entries.append(str(item.relative_to(root)))
            if len(entries) >= max_entries:
                entries.append("[truncated]")
                break
        return "\n".join(entries)

    @function_tool
    def read_file(path: str, max_chars: int = 30000) -> str:
        """Read a UTF-8 text file for conditional follow-up evidence not already present in deterministic intelligence."""
        target = safe_path(path)
        if not target.is_file():
            return "File does not exist or is not a regular file."
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError as exc:
            return f"Could not read file: {exc}"

    @function_tool
    def search_repository(query: str, max_results: int = 100) -> str:
        """Search repository text for conditional follow-up evidence not already present in deterministic intelligence."""
        matches = []
        for item in root.rglob("*"):
            if ".git" in item.parts or not item.is_file():
                continue
            try:
                with item.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if query.lower() in line.lower():
                            matches.append(f"{item.relative_to(root)}:{line_number}: {line.rstrip()}")
                            if len(matches) >= max_results:
                                return "\n".join(matches + ["[truncated]"])
            except OSError:
                continue
        return "\n".join(matches) if matches else "No matches found."
    
    @function_tool
    def glob(pattern: str, path: str = ".", max_results: int = 300) -> str:
        """Find repository files and directories whose paths match a glob pattern."""
        base = safe_path(path)
        matches = []

        for item in base.glob(pattern):
            if ".git" in item.parts:
                continue
            matches.append(str(item.relative_to(root)))
            if len(matches) >= max_results:
                matches.append("[truncated]")
                break

        return "\n".join(matches) if matches else "No matches found."
    
    @function_tool
    def grep(pattern: str, path: str = ".", max_results: int = 100) -> str:
        """Search repository file contents for a text or regular-expression pattern."""
        import re

        base = safe_path(path)
        regex = re.compile(pattern, re.IGNORECASE)
        matches = []

        for item in base.rglob("*"):
            if ".git" in item.parts or not item.is_file():
                continue

            try:
                with item.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if regex.search(line):
                            matches.append(
                                f"{item.relative_to(root)}:{line_number}: {line.rstrip()}"
                            )
                            if len(matches) >= max_results:
                                return "\n".join(matches + ["[truncated]"])
            except OSError:
                continue

        return "\n".join(matches) if matches else "No matches found."

    return [
        list_files,
        glob,
        grep,
        read_file,
        search_repository,
        list_resources,
        read_resource,
        list_previous_phase_outputs,
        read_previous_phase_output,
        list_spec_projects,
        list_project_documents,
        read_project_document,
        list_spec_sprints,
        list_specification_phases,
        read_spec_output,
    ]


def _preview(value: Any, limit: int = 800) -> str:
    text = str(value).replace("\n", "\\n")
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")


class AgentDiagnosticsHooks(RunHooks):
    def __init__(self, trace_id: str, phase: str):
        self.trace_id = trace_id
        self.phase = phase
        self.llm_turn = 0
        self.tool_calls = 0

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.llm_turn += 1
        logger.warning("AGENT_DIAG llm_start trace_id=%s phase=%s turn=%d input_items=%d system_prompt_chars=%d", self.trace_id, self.phase, self.llm_turn, len(input_items), len(system_prompt or ""))

    async def on_llm_end(self, context, agent, response) -> None:
        output_items = getattr(response, "output", []) or []
        usage = getattr(context, "usage", None)
        logger.warning("AGENT_DIAG llm_end trace_id=%s phase=%s turn=%d output_items=%d usage_requests=%s", self.trace_id, self.phase, self.llm_turn, len(output_items), getattr(usage, "requests", None))

    async def on_tool_start(self, context, agent, tool) -> None:
        self.tool_calls += 1
        logger.warning("AGENT_DIAG tool_start trace_id=%s phase=%s turn=%d tool_index=%d tool=%s", self.trace_id, self.phase, self.llm_turn, self.tool_calls, getattr(tool, "name", type(tool).__name__))

    async def on_tool_end(self, context, agent, tool, result) -> None:
        logger.warning("AGENT_DIAG tool_end trace_id=%s phase=%s turn=%d tool_index=%d tool=%s result_chars=%d result_preview=%s", self.trace_id, self.phase, self.llm_turn, self.tool_calls, getattr(tool, "name", type(tool).__name__), len(str(result)), _preview(result, 1200))

    async def on_agent_end(self, context, agent, output) -> None:
        logger.warning("AGENT_DIAG agent_end trace_id=%s phase=%s turns=%d tool_calls=%d output_preview=%s", self.trace_id, self.phase, self.llm_turn, self.tool_calls, _preview(output, 1000))


async def _wait_for_cancellation(run_control: RunControl) -> None:
    while not run_control.is_cancelled():
        await asyncio.sleep(0.2)


async def _run_agent(*, phase: str, phase_name: str, repository: Path, phase_intelligence: str, model: str, api_key: str, provider: str, previous_output: Optional[str], output_run_dir: Path, run_control: Optional[RunControl] = None, workflow: str = "sdlc") -> tuple[str, str]:
    provider_name = provider.strip().lower()
    if provider_name == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    elif provider_name == "openai":
        base_url = "https://api.openai.com/v1"
    else:
        raise AgentRunnerError(f"Unsupported provider '{provider}'. Supported providers are: openrouter, openai")

    common_agent_contract = "" if workflow == "specification" else _read_common_agent_contract()
    agent_definition = _read_agent_definition(phase)
    skill = _read_skill(phase)
    skill_resources = _resolve_skill_resources(phase, output_run_dir)
    resource_context = _format_skill_resources(skill_resources)
    handoff = ""
    if previous_output:
        handoff = "\n\nPrevious phase output is supporting context only. Verify important claims against repository evidence.\n\n" + previous_output[:20000]

    if workflow == "specification":
        common_instructions = """You are performing an evidence-driven software specification workflow.
project.md is the stable, human-authored product context and must be considered for every sprint. The human-authored intent contains the current Sprint Goal and Sprint Backlog and is the authoritative sprint scope. Repository intelligence is supporting technical evidence about the existing system.
Do not turn the request into an SDLC documentation exercise. Do not invent requirements, silently resolve ambiguity, or allow repository conventions to override explicit intent without making the conflict visible.
The repository is read-only. Use repository tools only for targeted verification.
Durable spec_output is also available through dedicated read-only tools. Previous closed sprint specifications are historical context, not a replacement for the current human-authored intent.
Distinguish explicit intent, evidence-backed decisions, assumptions, and unresolved questions.
Return only the requested specification workflow artifact in professional Markdown. Do not describe the agent, tools, prompts, or execution process."""
        task_instruction = "Perform your assigned specification role and produce the requested workflow artifact."
        agent_label = "Specification"
    else:
        common_instructions = """You are performing an evidence-driven SDLC reverse-engineering phase.
The repository has already been cloned and deterministic repository intelligence has already been collected before your first turn. Treat that intelligence as the primary evidence index.
Do not repeat repository-wide discovery or reread files merely to reconstruct information already present in the intelligence package. Use repository tools only for a specific ambiguity, missing source passage, or precision check.
Do not invent details. Distinguish verified facts, reasonable inferences, and unknowns when evidence is incomplete.
The repository is read-only. Do not modify it.
Return only complete professional Markdown documentation for the requested phase. Do not describe the agent, tools, prompts, intelligence collection, or execution process.
Skill resources are supplied explicitly by the runtime. Use those paths and tool identifiers instead of discovering them.

INVESTIGATION BUDGET
You have a finite investigation budget defined by the runner. Prioritize high-value evidence gathering early. As the remaining budget becomes small, stop broad exploration and transition to verification and synthesis. On the final available turn, produce the best-supported artifact possible rather than continuing investigation. Never invent missing evidence; mark it unknown or unverified."""
        task_instruction = "Analyze the repository and produce the requested phase documentation."
        agent_label = "SDLC"

    instructions = "\n\n".join(part for part in [common_instructions, common_agent_contract, agent_definition, resource_context, f"Phase methodology:\n{skill}" if skill else "", phase_intelligence, handoff] if part)
    client = AsyncOpenAI(base_url=base_url, api_key=api_key.strip())
    agent = Agent(name=f"{agent_label} {phase_name}", instructions=instructions, model=OpenAIChatCompletionsModel(model=model.strip(), openai_client=client), tools=_build_tools(phase, repository, output_run_dir))
    trace_id = uuid.uuid4().hex[:12]
    hooks = AgentDiagnosticsHooks(trace_id, phase)
    started = time.perf_counter()
    logger.warning("AGENT_DIAG start trace_id=%s phase=%s model=%s provider=%s repository=%s intelligence_chars=%d common_agent_contract_chars=%d agent_definition_chars=%d skill_chars=%d skill_resources=%s max_turns=%d", trace_id, phase, model, provider_name, repository, len(phase_intelligence), len(common_agent_contract), len(agent_definition), len(skill), json.dumps(skill_resources, sort_keys=True), settings.phase_agent_max_turns)
    try:
        if run_control and run_control.is_cancelled():
            raise RunCancelled("Analysis stopped by the user.")
        agent_task = asyncio.create_task(Runner.run(agent, task_instruction, hooks=hooks, max_turns=settings.phase_agent_max_turns))
        if run_control is None:
            result = await agent_task
        else:
            cancel_task = asyncio.create_task(_wait_for_cancellation(run_control))
            done, pending = await asyncio.wait({agent_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done and run_control.is_cancelled():
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
                raise RunCancelled("Analysis stopped by the user.")
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass
            result = await agent_task
    except RunCancelled:
        logger.warning("AGENT_DIAG cancelled trace_id=%s phase=%s elapsed_s=%.3f turns_observed=%d tool_calls_observed=%d", trace_id, phase, time.perf_counter() - started, hooks.llm_turn, hooks.tool_calls)
        raise
    except Exception as exc:
        logger.warning("AGENT_DIAG failed trace_id=%s phase=%s elapsed_s=%.3f turns_observed=%d tool_calls_observed=%d error_type=%s error=%s", trace_id, phase, time.perf_counter() - started, hooks.llm_turn, hooks.tool_calls, type(exc).__name__, str(exc))
        raise
    output = str(result.final_output or "").strip()
    if not output:
        raise AgentRunnerError(f"OpenAI Agents SDK completed phase '{phase}' but returned no final output.")

    actual_model = model.strip()
    raw_responses = getattr(result, "raw_responses", None) or []
    for raw_response in reversed(raw_responses):
        response = getattr(raw_response, "response", raw_response)
        response_model = getattr(response, "model", None)
        if response_model:
            actual_model = str(response_model)
            break
    return output, actual_model


def run_phase_agent(phase: str, phase_name: str, repository: Path, phase_intelligence: str, previous_output: Optional[str] = None, provider: str = "openrouter", model: str = "openrouter/free", api_key: Optional[str] = None, run_control: Optional[RunControl] = None) -> tuple[str, str]:
    """Run one phase against a shared read-only repository workspace and return output plus actual model used."""
    if not api_key or not api_key.strip():
        raise AgentRunnerError(f"An API key is required for provider '{provider}'.")
    if not repository.is_dir():
        raise AgentRunnerError(f"Repository path does not exist: {repository}")
    try:
        run_id = getattr(run_control, "run_id", None) if run_control is not None else None
        if not run_id and run_control is not None:
            state_path = getattr(run_control, "state_path", None)
            if state_path:
                run_id = Path(state_path).parent.name

        if not run_id:
            raise AgentRunnerError("Could not determine the current analysis run ID for previous phase outputs.")

        output_run_dir = PROJECT_ROOT / "output-content" / str(run_id)
        return asyncio.run(
            _run_agent(
                phase=phase,
                phase_name=phase_name,
                repository=repository,
                phase_intelligence=phase_intelligence,
                model=model,
                api_key=api_key,
                provider=provider,
                previous_output=previous_output,
                output_run_dir=output_run_dir,
                run_control=run_control,
            )
        )
    except RunCancelled:
        raise
    except AgentRunnerError:
        raise
    except Exception as exc:
        logger.exception("OpenAI Agents SDK failed during phase %s", phase)
        raise AgentRunnerError(f"OpenAI Agents SDK failed during phase '{phase}': {exc}") from exc



def run_specification_agent(
    *,
    agent: str,
    agent_name: str,
    repository: Path,
    intent: str,
    repository_context: str,
    previous_output: Optional[str] = None,
    provider: str = "openrouter",
    model: str = "openrouter/free",
    api_key: Optional[str] = None,
    output_run_dir: Optional[Path] = None,
    run_control: Optional[RunControl] = None,
) -> tuple[str, str]:
    """Run one dedicated specification agent using the specification agent/skill namespace."""
    if not api_key or not api_key.strip():
        raise AgentRunnerError(f"An API key is required for provider '{provider}'.")
    if not repository.is_dir():
        raise AgentRunnerError(f"Repository path does not exist: {repository}")
    if not intent.strip():
        raise AgentRunnerError("Specification intent cannot be empty.")

    if output_run_dir is None:
        run_id = getattr(run_control, "run_id", None) if run_control is not None else None
        if not run_id and run_control is not None:
            state_path = getattr(run_control, "state_path", None)
            if state_path:
                run_id = Path(state_path).parent.name
        if not run_id:
            raise AgentRunnerError("Could not determine the specification run ID.")
        output_run_dir = PROJECT_ROOT / "output-content" / str(run_id)

    phase = f"specification/{agent}"
    phase_intelligence = (
        "CURRENT SPRINT INTENT (Sprint Goal + Sprint Backlog)\n\n"
        + intent.strip()
        + "\n\n"
        + repository_context
    )
    if previous_output:
        phase_intelligence += (
            "\n\nPREVIOUS SPECIFICATION WORKFLOW OUTPUT\n\n"
            + previous_output[:30000]
        )

    try:
        return asyncio.run(
            _run_agent(
                phase=phase,
                phase_name=agent_name,
                repository=repository,
                phase_intelligence=phase_intelligence,
                model=model,
                api_key=api_key,
                provider=provider,
                previous_output=previous_output,
                output_run_dir=output_run_dir,
                run_control=run_control,
                workflow="specification",
            )
        )
    except RunCancelled:
        raise
    except AgentRunnerError:
        raise
    except Exception as exc:
        logger.exception("Specification agent failed: %s", agent)
        raise AgentRunnerError(
            f"OpenAI Agents SDK failed during specification agent '{agent}': {exc}"
        ) from exc
