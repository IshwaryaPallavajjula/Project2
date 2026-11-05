import os

from runner import find_risky, run_code


def test_passing_code():
    result = run_code("def add(a, b):\n    return a + b\n", ["assert add(1, 2) == 3"])
    assert result.passed
    assert result.status == "PASSED"


def test_failing_assertion_reports_actual_value():
    result = run_code("def add(a, b):\n    return a - b\n", ["assert add(1, 2) == 3"])
    assert not result.passed
    assert "TEST FAILED: assert add(1, 2) == 3" in result.stderr
    assert "left side evaluated to: -1" in result.stderr


def test_exception_in_code_is_captured():
    result = run_code("def f():\n    return 1 / 0\n", ["assert f() == 1"])
    assert not result.passed
    assert "ZeroDivisionError" in result.feedback()


def test_syntax_error_is_captured():
    result = run_code("def f(:\n", ["assert True"])
    assert not result.passed
    assert "SyntaxError" in result.stderr


def test_infinite_loop_times_out():
    result = run_code("while True:\n    pass\n", [], timeout=1)
    assert result.timed_out
    assert result.status == "TIMEOUT"
    assert result.duration < 5


def test_early_exit_does_not_count_as_pass():
    result = run_code("import sys\nsys.exit(0)\n", ["assert False"])
    assert not result.passed


def test_printing_a_fake_marker_does_not_pass():
    result = run_code("print('PASSED_deadbeef')\n", ["assert False"])
    assert not result.passed


def test_dangerous_code_is_blocked_not_run():
    result = run_code("import shutil\nshutil.rmtree('/tmp/definitely-not-real')\n", [])
    assert result.status == "BLOCKED"
    assert "shutil" in result.blocked


def test_find_risky():
    assert find_risky("import subprocess") == ["import subprocess"]
    assert find_risky("import os\nos.system('ls')") == ["os.system"]
    assert find_risky("from os import remove") == ["os.remove"]
    assert find_risky("eval('1')") == ["eval()"]
    assert find_risky("import math\nmath.sqrt(4)") == []


def test_secrets_are_not_visible(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret-value")
    code = "import os\nprint(os.environ.get('GROQ_API_KEY'))\n"
    result = run_code(code, [])
    assert result.passed
    assert "super-secret-value" not in result.stdout


def test_runs_in_temp_directory_not_project():
    code = "import os\nprint(os.getcwd())\n"
    result = run_code(code, [])
    assert os.getcwd() not in result.stdout


def test_stdin_is_closed():
    result = run_code("input()\n", [])
    assert not result.passed
    assert "EOFError" in result.stderr


def test_large_output_is_truncated():
    result = run_code("print('x' * 100000)\n", [])
    assert len(result.stdout) < 4000
