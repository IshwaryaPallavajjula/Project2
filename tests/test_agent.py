import json
from pathlib import Path

import codegen
from agent import RunLog, build_user_prompt, main, solve_task
from runner import run_code

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TASK = {"id": "add", "task": "Write add(a, b).", "tests": ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]}


def scripted_provider(monkeypatch, replies):
    seen = []
    iterator = iter(replies)

    def fake(messages, model):
        seen.append([m["content"] for m in messages])
        return next(iterator)

    monkeypatch.setitem(codegen.PROVIDERS, "groq", fake)
    return seen


def test_agent_self_corrects(monkeypatch):
    seen = scripted_provider(monkeypatch, ["```python\n" + BUGGY + "```", FIXED])
    outcome = solve_task(TASK, "groq", "m", RunLog(None))
    assert outcome.passed
    assert outcome.self_corrected
    assert [a.result.passed for a in outcome.attempts] == [False, True]
    feedback = seen[1][-1]
    assert "Attempt 1 failed" in feedback
    assert "left side evaluated to: -1" in feedback


def test_agent_gives_up_after_max_attempts(monkeypatch):
    scripted_provider(monkeypatch, [BUGGY, BUGGY, BUGGY])
    outcome = solve_task(TASK, "groq", "m", RunLog(None), max_attempts=3)
    assert not outcome.passed
    assert len(outcome.attempts) == 3


def test_agent_recovers_from_infinite_loop(monkeypatch):
    scripted_provider(monkeypatch, ["while True:\n    pass\n", FIXED])
    outcome = solve_task(TASK, "groq", "m", RunLog(None), timeout=1)
    assert outcome.passed
    assert outcome.attempts[0].result.timed_out


def test_agent_recovers_from_blocked_code(monkeypatch):
    seen = scripted_provider(monkeypatch, ["import subprocess\n" + FIXED, FIXED])
    outcome = solve_task(TASK, "groq", "m", RunLog(None))
    assert outcome.passed
    assert "forbidden operations" in seen[1][-1]


def test_llm_error_is_reported(monkeypatch):
    def boom(messages, model):
        raise codegen.GenerationError("api down")

    monkeypatch.setitem(codegen.PROVIDERS, "groq", boom)
    outcome = solve_task(TASK, "groq", "m", RunLog(None))
    assert not outcome.passed
    assert outcome.error == "api down"


def test_tests_are_in_first_prompt_unless_blind():
    assert "assert add(1, 2) == 3" in build_user_prompt("task", TASK["tests"], blind=False)
    assert "assert" not in build_user_prompt("task", TASK["tests"], blind=True)


def test_cli_writes_log_and_solution(monkeypatch, tmp_path: Path):
    scripted_provider(monkeypatch, [BUGGY, FIXED])
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps([TASK]))
    code = main(
        [
            "--tasks",
            str(tasks_file),
            "-o",
            str(tmp_path / "solutions"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert code == 0
    assert (tmp_path / "solutions" / "add.py").read_text() == FIXED
    log_text = next((tmp_path / "logs").glob("run_*.log")).read_text()
    assert "ATTEMPT 1/3" in log_text and "ATTEMPT 2/3" in log_text
    assert "self-corrected" in log_text


def test_saved_solution_passes_its_tests(monkeypatch, tmp_path: Path):
    scripted_provider(monkeypatch, [FIXED])
    main(
        [
            "add numbers",
            "-t",
            "assert add(2, 2) == 4",
            "-o",
            str(tmp_path / "s"),
            "--log-dir",
            str(tmp_path / "l"),
        ]
    )
    saved = next((tmp_path / "s").glob("*.py")).read_text()
    assert run_code(saved, ["assert add(2, 2) == 4"]).passed
