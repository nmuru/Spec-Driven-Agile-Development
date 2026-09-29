from pathlib import Path

from app.specification import analyzer


def test_specification_agents_run_in_order(monkeypatch, tmp_path):
    calls = []

    class Intelligence:
        def to_json(self):
            return '{"file_count": 1}'

    monkeypatch.setattr(analyzer, "clone_repository", lambda repo_url, workspace, run_control=None: Path(workspace))
    monkeypatch.setattr(analyzer, "collect_repository_intelligence", lambda repository: Intelligence())

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

    assert [name for name, _ in calls] == [
        "intent-analyst",
        "specification-architect",
        "specification-reviewer",
    ]
    assert calls[0][1] is None
    assert calls[1][1] == "output:intent-analyst"
    assert calls[2][1] == "output:specification-architect"
    assert result["specification"] == "output:specification-architect"
    assert result["review"] == "output:specification-reviewer"
