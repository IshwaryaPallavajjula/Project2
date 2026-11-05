import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import codegen
from codegen import DEFAULT_MODELS, GenerationError, slugify, strip_fences
from runner import RunResult, run_code

SYSTEM_PROMPT = (
    "You are a Python code generator running inside an automated test loop. "
    "Reply with ONLY raw, valid Python 3 code.\n"
    "Rules:\n"
    "1. No explanations, no greetings, no markdown fences.\n"
    "2. Define the functions with exactly the names and signatures the task asks for.\n"
    "3. Use only the Python standard library and pure computation: no files, network, "
    "processes, eval or exec.\n"
    "4. Do not call input(), and do not include example usage or test code. The tests are run separately.\n"
    "5. If you are told your previous code failed, return the complete corrected code, not a diff."
)

RULE = "=" * 72
THIN = "-" * 72


class RunLog:
    def __init__(self, path: Path | None):
        self.handle = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = path.open("w", encoding="utf-8")

    def write(self, text: str = "") -> None:
        print(text)
        if self.handle:
            self.handle.write(text + "\n")
            self.handle.flush()

    def close(self) -> None:
        if self.handle:
            self.handle.close()


@dataclass
class Attempt:
    number: int
    code: str
    result: RunResult


@dataclass
class TaskOutcome:
    task_id: str
    passed: bool = False
    attempts: list = field(default_factory=list)
    error: str = ""

    @property
    def self_corrected(self) -> bool:
        return self.passed and len(self.attempts) > 1


def indent(text: str) -> str:
    return textwrap.indent(text, "    ")


def build_user_prompt(task: str, tests: list[str], blind: bool) -> str:
    if blind or not tests:
        return task
    return task + "\n\nYour code must pass these tests:\n" + "\n".join(tests)


def log_attempt(log: RunLog, attempt: Attempt, max_attempts: int) -> None:
    result = attempt.result
    log.write(f"\n{THIN}\nATTEMPT {attempt.number}/{max_attempts}\n{THIN}")
    log.write("Code:")
    log.write(indent(attempt.code))
    log.write(f"\nResult: {result.status} ({result.duration:.2f}s)")
    if not result.passed:
        log.write(indent(result.feedback()))


def solve_task(
    task: dict,
    provider: str,
    model: str,
    log: RunLog,
    max_attempts: int = 3,
    timeout: float = 10.0,
    blind: bool = False,
) -> TaskOutcome:
    tests = task.get("tests", [])
    outcome = TaskOutcome(task["id"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(task["task"], tests, blind)},
    ]
    call = codegen.PROVIDERS[provider]

    for number in range(1, max_attempts + 1):
        try:
            raw = call(messages, model)
        except GenerationError as exc:
            outcome.error = str(exc)
            log.write(f"\nLLM error: {exc}")
            break

        code = strip_fences(raw)
        result = run_code(code, tests, timeout)
        attempt = Attempt(number, code, result)
        outcome.attempts.append(attempt)
        log_attempt(log, attempt, max_attempts)

        if result.passed:
            outcome.passed = True
            break
        if number < max_attempts:
            log.write("\n>> Sending the error back to the model so it can fix the code")
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Attempt {number} failed.\n{result.feedback()}\n\n"
                        "Fix the code so that every test passes. Return the complete corrected code only."
                    ),
                }
            )
    return outcome


def save_solution(outcome: TaskOutcome, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{outcome.task_id}.py"
    path.write_text(outcome.attempts[-1].code.rstrip() + "\n", encoding="utf-8")
    return path


def print_summary(log: RunLog, outcomes: list[TaskOutcome]) -> None:
    width = max((len(o.task_id) for o in outcomes), default=0)
    log.write(f"\n{RULE}\nSUMMARY\n{RULE}")
    for outcome in outcomes:
        if outcome.passed:
            note = f"attempt {len(outcome.attempts)}"
            if outcome.self_corrected:
                note += " (self-corrected)"
            line = f"{outcome.task_id.ljust(width)}  PASSED  {note}"
        elif outcome.error:
            line = f"{outcome.task_id.ljust(width)}  ERROR   {outcome.error[:80]}"
        else:
            line = f"{outcome.task_id.ljust(width)}  FAILED  after {len(outcome.attempts)} attempts"
        log.write(line)
    passed = sum(o.passed for o in outcomes)
    corrected = sum(o.self_corrected for o in outcomes)
    log.write(f"\nPassed {passed}/{len(outcomes)} | self-corrected {corrected}")


def run_tasks(
    tasks: list[dict],
    provider: str,
    model: str,
    log: RunLog,
    output_dir: Path,
    max_attempts: int,
    timeout: float,
    blind: bool,
) -> list[TaskOutcome]:
    outcomes = []
    for index, task in enumerate(tasks, start=1):
        log.write(f"\n{RULE}\nTASK {index}/{len(tasks)}: {task['id']}\n{RULE}")
        log.write(f"Task: {task['task']}")
        if task.get("tests"):
            log.write("Tests:")
            for test in task["tests"]:
                log.write(f"    {test}")
        outcome = solve_task(task, provider, model, log, max_attempts, timeout, blind)
        outcomes.append(outcome)
        if outcome.passed:
            path = save_solution(outcome, output_dir)
            log.write(f"\nSaved passing solution to {path}")
        else:
            log.write(f"\nTask '{task['id']}' failed after {len(outcome.attempts)} attempt(s)")
    print_summary(log, outcomes)
    return outcomes


def load_tasks(path: Path) -> list[dict]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    for task in tasks:
        if "id" not in task or "task" not in task:
            raise ValueError(f"Every task needs 'id' and 'task' keys: {task}")
    return tasks


def safety_demo() -> int:
    cases = [
        ("Infinite loop is killed by the timeout", "while True:\n    pass\n", 2.0),
        ("A crash is captured, not propagated", "print(1 / 0)\n", 5.0),
        ("Dangerous code is refused before it runs", "import shutil\nshutil.rmtree('/')\n", 5.0),
        (
            "API keys are not visible to generated code",
            "import os\nprint('GROQ_API_KEY =', os.environ.get('GROQ_API_KEY'))\n",
            5.0,
        ),
    ]
    for title, code, timeout in cases:
        print(f"\n{RULE}\n{title}\n{RULE}")
        print(indent(code.rstrip()))
        result = run_code(code, [], timeout)
        print(f"\nResult: {result.status} ({result.duration:.2f}s)")
        detail = result.feedback() if not result.passed else result.stdout.strip()
        if result.passed and not detail:
            detail = "(no output)"
        print(indent(detail))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Generate code, run it in a sandboxed subprocess, and self-correct from errors.",
    )
    parser.add_argument("task", nargs="*", help="A single task description (otherwise --tasks file is used)")
    parser.add_argument("-t", "--test", action="append", default=[], help="Assertion the code must pass (repeatable)")
    parser.add_argument("--tasks", default="agent_tasks.json", help="JSON file with tasks and tests")
    parser.add_argument("--only", nargs="+", metavar="ID", help="Run only these task ids")
    parser.add_argument("-p", "--provider", choices=list(codegen.PROVIDERS), default="groq")
    parser.add_argument("-m", "--model", help="Model name (defaults depend on the provider)")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds before generated code is killed")
    parser.add_argument(
        "--blind",
        action="store_true",
        help="Do not show the tests to the model on the first prompt, so mistakes surface and get corrected",
    )
    parser.add_argument("-o", "--output-dir", default="solutions", help="Folder for passing solutions")
    parser.add_argument("--log-dir", default="logs", help="Folder for run logs")
    parser.add_argument("--safety-demo", action="store_true", help="Show the sandbox handling dangerous code")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.safety_demo:
        return safety_demo()

    if args.task:
        text = " ".join(args.task)
        tasks = [{"id": slugify(text), "task": text, "tests": args.test}]
    else:
        tasks = load_tasks(Path(args.tasks))
        if args.only:
            wanted = set(args.only)
            tasks = [task for task in tasks if task["id"] in wanted]
            if not tasks:
                print(f"No tasks matched {sorted(wanted)}", file=sys.stderr)
                return 1

    model = args.model or DEFAULT_MODELS[args.provider]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = RunLog(Path(args.log_dir) / f"run_{stamp}.log")
    try:
        log.write(
            f"Agent run {stamp} | provider={args.provider} model={model} "
            f"max_attempts={args.max_attempts} timeout={args.timeout:g}s blind={args.blind}"
        )
        outcomes = run_tasks(
            tasks,
            args.provider,
            model,
            log,
            Path(args.output_dir),
            args.max_attempts,
            args.timeout,
            args.blind,
        )
    finally:
        log.close()
    return 0 if all(outcome.passed for outcome in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
