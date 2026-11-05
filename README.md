# NL2Code: from code generator to self-correcting agent

A Python CLI that turns plain-English tasks into code with a free LLM (Groq, default model `openai/gpt-oss-120b`, or a local model through Ollama).

- **Week 1 (`codegen.py`)**: generate code from a task description, print it and save it to a `.py` file.
- **Week 2 (`agent.py`)**: close the loop. The agent **executes** what it writes, reads the result, and **fixes itself** when the code fails, up to 3 attempts.

## Setup

```bash
git clone <your-repo-url>
cd nl2code
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Groq (free, no credit card):** create a key at https://console.groq.com, copy `.env.example` to `.env` and paste it:

```
GROQ_API_KEY=your_groq_api_key_here
```

**Ollama (offline):** `ollama pull qwen2.5-coder`, `ollama serve`, then add `-p ollama` to any command.

## Week 2: the self-correcting agent

```
task + tests -> LLM writes code -> run in sandboxed subprocess -> pass? done
                      ^                                              |
                      +---- "this failed with error X, fix it" <-----+  (max 3 attempts)
```

### Run it

```bash
python agent.py                                   # all 10 tasks in agent_tasks.json
python agent.py --only low_median round_half_up   # selected tasks
python agent.py --blind                           # hide tests on the first prompt (shows self-correction)
python agent.py "write reverse(s)" -t "assert reverse('abc') == 'cba'"
python agent.py --safety-demo                     # sandbox demo, no API key needed
```

| Flag | Meaning |
| --- | --- |
| `--tasks FILE` | JSON file of tasks and assertions (default `agent_tasks.json`) |
| `--only ID ...` | Run only these task ids |
| `-t, --test` | Assertion the code must pass (repeatable, single-task mode) |
| `--max-attempts N` | Attempts per task (default 3) |
| `--timeout S` | Seconds before generated code is killed (default 10) |
| `--blind` | Do not show the tests to the model on the first prompt |
| `-p, -m` | Provider (`groq` or `ollama`) and model |
| `-o, --log-dir` | Where passing solutions (`solutions/`) and run logs (`logs/`) go |

### Task format

```json
{
  "id": "low_median",
  "task": "Write a function median(nums) that returns the median of a non-empty list of numbers.",
  "tests": ["assert median([1, 2, 3, 4]) == 2"]
}
```

The 10 included tasks cover strings, math, lists and dicts. Several (`low_median`, `round_half_up`, `top_words`, `run_length_encode`) use a convention that is only visible in the tests, so a first attempt often fails. That is what makes the self-correction visible. Use `--blind` to make that more likely.

### What the log shows

Every attempt is logged to the terminal and to `logs/run_<timestamp>.log`: attempt number, the code, the result (PASSED, FAILED, TIMEOUT or BLOCKED), and the error or traceback that is sent back to the model.

```
ATTEMPT 1/3
Code:
    def median(nums): ...
Result: FAILED (0.04s)
    TEST FAILED: assert median([1, 2, 3, 4]) == 2
      left side evaluated to: 2.5
>> Sending the error back to the model so it can fix the code
ATTEMPT 2/3
Result: PASSED (0.04s)
```

### How generated code is run safely

Generated code is untrusted, so it never touches `eval()` or `exec()` in the main process. `runner.py` does this instead:

1. **Static pre-check.** Code that imports `subprocess`, `socket`, `shutil`, `ctypes`, network libraries or calls `os.system`, `os.remove`, `eval()`, `exec()` and similar is refused before it runs. The model is told why and asked to rewrite it.
2. **Separate process.** The code and its tests are written to a temp file and run with `subprocess.run([python, "-I", ...])`.
3. **`timeout=`** kills infinite loops.
4. **`capture_output=True`** returns stdout, stderr and the exit code instead of letting them reach the terminal.
5. **Throwaway working directory.** The process runs inside a temp folder that is deleted afterwards.
6. **No secrets.** Environment variables with KEY, TOKEN, SECRET or PASSWORD in the name are removed, so generated code cannot read your API key.
7. **No stdin.** `input()` fails immediately instead of hanging.
8. **Resource limits** on Linux and macOS: 1 GB memory and 10 MB maximum file size.
9. **Tamper-resistant pass check.** A test only counts as passed when a random one-time marker is printed by the test harness after all assertions succeed, so code cannot fake success by printing "passed" or calling `exit(0)`.
10. **Output cap.** Long output is truncated before it goes back to the model.

**Limits:** this is the minimum safe pattern, not a full sandbox. A child process can still read files the user can read and make network calls through modules the pre-check does not cover. For stronger isolation, run the agent inside Docker or a VM.

## Week 1: the code generator

```bash
python codegen.py "write a function that checks if a number is prime"
python codegen.py --batch tasks.txt
python codegen.py                     # interactive mode
```

A strict system prompt asks for raw code only. `strip_fences()` removes markdown fences anyway, `ast.parse` checks syntax, and a syntax error is sent back to the model for up to 3 attempts. Output goes to `generated/<slug>.py`.

## Tests

```bash
pytest
```

44 tests, none of which need an API key. They cover the runner (timeouts, crashes, blocked code, hidden secrets, fake-pass attempts), the agent loop using a scripted fake LLM (fail, then fix), and every task in `agent_tasks.json` against a reference solution so the assertions are known to be valid.

## Project structure

```
nl2code/
├── agent.py            week 2: agent loop, logging, CLI
├── runner.py           week 2: safe subprocess execution
├── agent_tasks.json    10 tasks with assertions
├── codegen.py          week 1: code generator
├── tasks.txt           week 1 batch tasks
├── requirements.txt
├── .env.example
├── tests/
├── solutions/          passing code from agent runs (created on first run)
├── logs/               full attempt logs (created on first run)
└── generated/          week 1 output
```
