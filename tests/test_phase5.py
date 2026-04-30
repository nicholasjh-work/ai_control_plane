import json
from pathlib import Path


def test_eval_prompts_load():
    prompts = json.loads(Path("eval/prompts.json").read_text())
    assert len(prompts) == 30


def test_eval_prompts_have_required_fields():
    prompts = json.loads(Path("eval/prompts.json").read_text())
    sql_fields = {"id", "sql", "expected_allowed", "tags"}
    intake_fields = {
        "id",
        "intake",
        "expected_routing_team",
        "expected_policy_decision",
        "expected_redacted",
        "tags",
    }
    for case in prompts:
        is_sql = "sql" in case.get("tags", [])
        required = sql_fields if is_sql else intake_fields
        missing = required - case.keys()
        assert not missing, f"{case['id']} missing fields: {missing}"


def test_eval_prompts_tag_distribution():
    prompts = json.loads(Path("eval/prompts.json").read_text())
    all_tags = {tag for case in prompts for tag in case.get("tags", [])}
    for required_tag in ("routing", "pii", "sql", "fallback"):
        assert required_tag in all_tags, f"No case tagged '{required_tag}'"


def test_ci_yml_exists():
    ci_path = Path(".github/workflows/ci.yml")
    assert ci_path.exists(), ".github/workflows/ci.yml not found"
    content = ci_path.read_text()
    assert "make test" in content
    assert "make lint" in content
