import json
from pathlib import Path

import pytest

from runner import run_code

TASKS = json.loads((Path(__file__).resolve().parent.parent / "agent_tasks.json").read_text())

REFERENCE = {
    "reverse_string": "def reverse(s):\n    return s[::-1]\n",
    "is_palindrome": (
        "def is_palindrome(s):\n"
        "    cleaned = [c.lower() for c in s if c.isalnum()]\n"
        "    return cleaned == cleaned[::-1]\n"
    ),
    "fizzbuzz": (
        "def fizzbuzz(n):\n"
        "    out = []\n"
        "    for i in range(1, n + 1):\n"
        "        if i % 15 == 0:\n"
        "            out.append('FizzBuzz')\n"
        "        elif i % 3 == 0:\n"
        "            out.append('Fizz')\n"
        "        elif i % 5 == 0:\n"
        "            out.append('Buzz')\n"
        "        else:\n"
        "            out.append(str(i))\n"
        "    return out\n"
    ),
    "low_median": "def median(nums):\n    s = sorted(nums)\n    return s[(len(s) - 1) // 2]\n",
    "round_half_up": (
        "import math\n"
        "def round_half_up(x):\n"
        "    sign = -1 if x < 0 else 1\n"
        "    return sign * int(math.floor(abs(x) + 0.5))\n"
    ),
    "merge_sum": (
        "def merge_sum(a, b):\n"
        "    result = dict(a)\n"
        "    for key, value in b.items():\n"
        "        result[key] = result.get(key, 0) + value\n"
        "    return result\n"
    ),
    "flatten": (
        "def flatten(items):\n"
        "    out = []\n"
        "    for item in items:\n"
        "        if isinstance(item, list):\n"
        "            out.extend(flatten(item))\n"
        "        else:\n"
        "            out.append(item)\n"
        "    return out\n"
    ),
    "top_words": (
        "import re\n"
        "from collections import Counter\n"
        "def top_words(text, k):\n"
        "    counts = Counter(re.findall(r\"[a-z0-9']+\", text.lower()))\n"
        "    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]\n"
    ),
    "roman_to_int": (
        "def roman_to_int(s):\n"
        "    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}\n"
        "    total = 0\n"
        "    for i, ch in enumerate(s):\n"
        "        if i + 1 < len(s) and values[ch] < values[s[i + 1]]:\n"
        "            total -= values[ch]\n"
        "        else:\n"
        "            total += values[ch]\n"
        "    return total\n"
    ),
    "run_length_encode": (
        "def rle(s):\n"
        "    out = []\n"
        "    i = 0\n"
        "    while i < len(s):\n"
        "        j = i\n"
        "        while j < len(s) and s[j] == s[i]:\n"
        "            j += 1\n"
        "        out.append(s[i] + str(j - i))\n"
        "        i = j\n"
        "    return ''.join(out)\n"
    ),
}


def test_at_least_five_tasks_with_assertions():
    assert len(TASKS) >= 5
    assert all(task["tests"] for task in TASKS)


def test_every_task_has_a_reference_solution():
    assert {task["id"] for task in TASKS} == set(REFERENCE)


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_reference_solution_passes_task_tests(task):
    result = run_code(REFERENCE[task["id"]], task["tests"])
    assert result.passed, result.feedback()
