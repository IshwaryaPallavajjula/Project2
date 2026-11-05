import ast
import os
import secrets
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_CHARS = 3000
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
BLOCKED_MODULES = {
    "subprocess",
    "socket",
    "shutil",
    "ctypes",
    "urllib",
    "http",
    "requests",
    "multiprocessing",
    "pty",
}
BLOCKED_OS_ATTRS = {
    "system",
    "popen",
    "remove",
    "unlink",
    "rmdir",
    "removedirs",
    "rename",
    "replace",
    "kill",
    "fork",
    "execv",
    "execl",
    "execvp",
    "execlp",
    "spawnl",
    "spawnv",
}
BLOCKED_BUILTINS = {"eval", "exec", "compile", "__import__"}

HARNESS = '''

def __agent_run_tests__(tests, marker):
    import ast
    import sys
    import traceback

    namespace = globals()
    failures = 0
    for source in tests:
        try:
            exec(compile(source, "<test>", "exec"), namespace)
        except AssertionError:
            failures += 1
            detail = ""
            try:
                node = ast.parse(source).body[0]
                if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
                    left = ast.unparse(node.test.left)
                    detail = "\\n  left side evaluated to: " + repr(eval(left, namespace))
            except Exception:
                pass
            print("TEST FAILED: " + source + detail, file=sys.stderr)
        except Exception:
            failures += 1
            print("TEST ERROR: " + source, file=sys.stderr)
            traceback.print_exc()
    if failures:
        print(str(failures) + " of " + str(len(tests)) + " tests failed", file=sys.stderr)
        sys.exit(1)
    print(marker)


__agent_run_tests__(__TESTS__, __MARKER__)
'''


@dataclass
class RunResult:
    passed: bool
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    timeout: float
    duration: float
    blocked: str = ""

    @property
    def status(self) -> str:
        if self.blocked:
            return "BLOCKED"
        if self.timed_out:
            return "TIMEOUT"
        if self.passed:
            return "PASSED"
        return "FAILED"

    @property
    def error_summary(self) -> str:
        if self.blocked:
            return f"forbidden operations: {self.blocked}"
        if self.timed_out:
            return f"timed out after {self.timeout:g}s"
        lines = [line for line in self.stderr.strip().splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def feedback(self) -> str:
        if self.blocked:
            return (
                "The code was not executed because it uses forbidden operations: "
                f"{self.blocked}. Use only pure computation with the standard library."
            )
        if self.timed_out:
            return (
                f"The code did not finish within {self.timeout:g} seconds. "
                "It may contain an infinite loop or be too slow."
            )
        parts = [f"The process exited with code {self.returncode}."]
        if self.stderr.strip():
            parts.append("Error output:\n" + self.stderr.strip())
        if self.stdout.strip():
            parts.append("Printed output:\n" + self.stdout.strip())
        if self.returncode == 0:
            parts.append("The tests never completed. Do not call exit() or quit().")
        return "\n".join(parts)


def find_risky(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_MODULES:
                    found.add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in BLOCKED_MODULES:
                found.add(f"from {module} import ...")
            elif module == "os":
                for alias in node.names:
                    if alias.name in BLOCKED_OS_ATTRS:
                        found.add(f"os.{alias.name}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in BLOCKED_OS_ATTRS:
                found.add(f"os.{node.attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
                found.add(f"{node.func.id}()")
    return sorted(found)


def clean_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(hint in key.upper() for hint in SECRET_HINTS)
    }


def posix_limits() -> dict:
    if os.name != "posix":
        return {}

    def apply() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
            resource.setrlimit(resource.RLIMIT_FSIZE, (10 << 20, 10 << 20))
        except (ImportError, ValueError, OSError):
            pass

    return {"preexec_fn": apply}


def clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return "...[truncated]\n" + text[-MAX_OUTPUT_CHARS:]


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def build_script(code: str, tests: list[str], marker: str) -> str:
    harness = HARNESS.replace("__TESTS__", repr(list(tests))).replace("__MARKER__", repr(marker))
    return code.rstrip() + "\n\n" + harness


def run_code(code: str, tests: list[str] | tuple = (), timeout: float = 10.0) -> RunResult:
    risky = find_risky(code)
    if risky:
        return RunResult(
            passed=False,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            timeout=timeout,
            duration=0.0,
            blocked=", ".join(risky),
        )

    marker = "PASSED_" + secrets.token_hex(8)
    script = build_script(code, list(tests), marker)

    with tempfile.TemporaryDirectory(prefix="agent_run_") as workdir:
        path = Path(workdir) / "candidate.py"
        path.write_text(script, encoding="utf-8")
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-X", "utf8", str(path)],
                cwd=workdir,
                env=clean_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **posix_limits(),
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(
                passed=False,
                returncode=None,
                stdout=clip(as_text(exc.stdout)),
                stderr=clip(as_text(exc.stderr)),
                timed_out=True,
                timeout=timeout,
                duration=time.monotonic() - started,
            )
        duration = time.monotonic() - started
        stderr = proc.stderr.replace(str(path), "candidate.py")

    passed = proc.returncode == 0 and marker in proc.stdout
    stdout = proc.stdout.replace(marker, "")
    return RunResult(
        passed=passed,
        returncode=proc.returncode,
        stdout=clip(stdout),
        stderr=clip(stderr),
        timed_out=False,
        timeout=timeout,
        duration=duration,
    )
