from app.specification.store import SPECIFICATION_PHASES, SpecificationStore


def test_active_sprint_overwrites_approved_content_and_closes_immutably(tmp_path):
    store = SpecificationStore(tmp_path / "spec_output")
    first = store.get_or_create_active_sprint("https://github.com/example/project", "Build a feature")

    assert first["sprint_id"] == "sprint-001"
    assert first["status"] == "active"
    assert (tmp_path / "spec_output" / "example-project" / "document").is_dir()

    store.approve_phase("example-project", "sprint-001", "scope", "draft one")
    store.approve_phase("example-project", "sprint-001", "scope", "draft two")

    current = store.get_sprint("example-project", "sprint-001")
    assert current["contents"]["scope"] == "draft two"
    assert current["approved_phases"] == ["scope"]

    for phase in SPECIFICATION_PHASES:
        if phase != "scope":
            store.approve_phase("example-project", "sprint-001", phase, f"approved {phase}")

    closed = store.close_sprint("example-project", "sprint-001")
    assert closed["status"] == "closed"
    assert closed["specification_version"] == 1

    try:
        store.approve_phase("example-project", "sprint-001", "scope", "must not change")
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("Closed sprint specification accepted an approval.")

    next_sprint = store.get_or_create_active_sprint("https://github.com/example/project", "Next sprint")
    assert next_sprint["sprint_id"] == "sprint-002"
    assert next_sprint["status"] == "active"
