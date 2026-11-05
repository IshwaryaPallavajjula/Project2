import argparse
import ast
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

SYSTEM_PROMPT = (
    "You are a Python code generator. The user describes a task in plain English. "
    "Reply with ONLY valid, runnable Python 3 code that solves it.\n"
    "Rules:\n"
    "1. Output raw code only. No explanations, no greetings, no markdown fences.\n"
    "2. Define the requested function(s) with clear names and type hints.\n"
    "3. Use only the Python standard library.\n"
    "4. Handle edge cases such as empty input and invalid values.\n"
    "5. Do not include input() calls or example usage unless the task asks for it."
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "ollama": "qwen2.5-coder"}

FENCE_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\n(.*?)```", re.DOTALL)


class GenerationError(Exception):
    pass


def strip_fences(text: str) -> str:
    text = text.strip()
    blocks = FENCE_BLOCK.findall(text)
    if blocks:
        return max(blocks, key=len).strip()
    text = re.sub(r"^```[a-zA-Z0-9_+-]*[ \t]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def is_valid_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return False, f"{exc.msg} (line {exc.lineno})"
    return True, ""


def slugify(task: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", task.lower())
    stop = {"a", "an", "the", "that", "which", "to", "of", "write", "function", "program"}
    kept = [w for w in words if w not in stop][:max_words]
    return "_".join(kept) or "generated_code"


def unique_path(directory: Path, slug: str) -> Path:
    path = directory / f"{slug}.py"
    counter = 2
    while path.exists():
        path = directory / f"{slug}_{counter}.py"
        counter += 1
    return path


def call_groq(messages: list[dict], model: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GenerationError("GROQ_API_KEY is not set. Add it to a .env file or your environment.")
    response = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "temperature": 0.2},
        timeout=60,
    )
    if response.status_code != 200:
        raise GenerationError(f"Groq API error {response.status_code}: {response.text[:300]}")
    return response.json()["choices"][0]["message"]["content"]


def call_ollama(messages: list[dict], model: str) -> str:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.2}},
            timeout=300,
        )
    except requests.ConnectionError:
        raise GenerationError("Cannot reach Ollama at localhost:11434. Is `ollama serve` running?")
    if response.status_code != 200:
        raise GenerationError(f"Ollama error {response.status_code}: {response.text[:300]}")
    return response.json()["message"]["content"]


PROVIDERS = {"groq": call_groq, "ollama": call_ollama}


def generate_code(task: str, provider: str, model: str, max_attempts: int = 3) -> str:
    call = PROVIDERS[provider]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    last_error = ""
    for _ in range(max_attempts):
        raw = call(messages, model)
        code = strip_fences(raw)
        valid, last_error = is_valid_python(code)
        if valid and code:
            return code
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": f"That code has a syntax error: {last_error}. Return the corrected code only.",
            }
        )
    raise GenerationError(f"Could not produce valid Python after {max_attempts} attempts: {last_error}")


def process_task(task: str, provider: str, model: str, output_dir: Path, save: bool = True) -> Path | None:
    code = generate_code(task, provider, model)
    print(f"\n# Task: {task}")
    print("-" * 60)
    print(code)
    print("-" * 60)
    if not save:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(output_dir, slugify(task))
    path.write_text(code + "\n", encoding="utf-8")
    print(f"Saved to {path}")
    return path


def read_batch_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def interactive_loop(provider: str, model: str, output_dir: Path, save: bool) -> None:
    print("Describe a task in plain English. Type 'quit' to exit.")
    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if task.lower() in {"quit", "exit", "q"}:
            break
        if not task:
            continue
        try:
            process_task(task, provider, model, output_dir, save)
        except GenerationError as exc:
            print(f"Error: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codegen",
        description="Turn a plain-English task description into Python code using an LLM.",
    )
    parser.add_argument("task", nargs="*", help="Task description, e.g. 'check if a number is prime'")
    parser.add_argument("-p", "--provider", choices=PROVIDERS, default="groq")
    parser.add_argument("-m", "--model", help="Model name (defaults depend on the provider)")
    parser.add_argument("-o", "--output-dir", default="generated", help="Folder for generated .py files")
    parser.add_argument("-b", "--batch", help="Text file with one task per line")
    parser.add_argument("--no-save", action="store_true", help="Print the code without saving it")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    model = args.model or DEFAULT_MODELS[args.provider]
    output_dir = Path(args.output_dir)
    save = not args.no_save

    try:
        if args.batch:
            tasks = read_batch_file(Path(args.batch))
            failures = 0
            for task in tasks:
                try:
                    process_task(task, args.provider, model, output_dir, save)
                except GenerationError as exc:
                    failures += 1
                    print(f"Error on '{task}': {exc}", file=sys.stderr)
            print(f"\nDone: {len(tasks) - failures}/{len(tasks)} tasks succeeded.")
            return 1 if failures else 0
        if args.task:
            process_task(" ".join(args.task), args.provider, model, output_dir, save)
            return 0
        interactive_loop(args.provider, model, output_dir, save)
        return 0
    except GenerationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
