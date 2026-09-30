from pathlib import Path

from app.specification import analyzer
from app.specification_store import SpecificationStore


def test_specification_phases_run_in_order(monkeypatch, tmp_path):
    calls = []

    class Intelligence:
        def to_json(self):
            return '{"file_count": 1}'

    monkeypatch.setattr(analyzer, "SpecificationStore", lambda: SpecificationStore(tmp_path / "spec_output"))

    monkeypatch.setattr(
        analyzer,
        "clone_repository",
        lambda repo_url, workspace, run_control=None: Path(workspace),
    )
    monkeypatch.setattr(
        analyzer,
        "collect_repository_intelligence",
        lambda repository: Intelligence(),
    )

    def fake_agent(**kwargs):
        calls.append((kwargs["agent"], kwargs["previous_output"]))
        return f"output:{kwargs['agent']}", "test-model"

    monkeypatch.setattr(analyzer, "run_specification_agent", fake_agent)

    result = analyzer.analyze_specification(
        intent="Build a new component",
        repo_url="https://github.com/example/project",
        output_run_dir=tmp_path / "run-1",
        provider="openai",
        model="test-model",
        api_key="test-key",
    )

    assert [name for name, _ in calls] == [name for name, _ in analyzer.SPECIFICATION_PHASES]
    assert calls[0][1] is None
    for index in range(1, len(calls)):
        assert calls[index][1] == f"output:{calls[index - 1][0]}"

    assert result["intent"] == "Build a new component"
    assert result["scope"] == "output:scope"
    assert result["business_requirements"] == "output:business-requirements"
    assert result["software_requirements"] == "output:software-requirements"
    assert result["design"] == "output:design"
    assert result["tasks"] == "output:tasks"
    assert result["specification"] == "output:review"
    assert result["review"] == "output:review"
    assert result["project_id"] == "example-project"
    assert result["sprint_id"] == "sprint-001"


def test_specification_can_run_without_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(analyzer, "SpecificationStore", lambda: SpecificationStore(tmp_path / "spec_output"))

    calls = []

    def fake_agent(**kwargs):
        calls.append(kwargs["repository_context"])
        return f"output:{kwargs['agent']}", "test-model"

    monkeypatch.setattr(analyzer, "run_specification_agent", fake_agent)

    result = analyzer.analyze_specification(
        intent="Build a new storefront",
        repo_url=None,
        output_run_dir=tmp_path / "run-2",
        provider="openai",
        model="test-model",
        api_key="test-key",
    )

    assert result["project_id"].startswith("intent-")
    assert result["sprint_id"] == "sprint-001"
    assert len(calls) == len(analyzer.SPECIFICATION_PHASES)
    assert all("NO REPOSITORY WAS PROVIDED" in value for value in calls)
