from pathlib import Path

import pytest

from codegen import (
    GenerationError,
    generate_code,
    is_valid_python,
    read_batch_file,
    slugify,
    strip_fences,
    unique_path,
)


def test_strip_fences_with_language_tag():
    raw = "```python\ndef f():\n    return 1\n```"
    assert strip_fences(raw) == "def f():\n    return 1"


def test_strip_fences_without_language_tag():
    raw = "```\nx = 1\n```"
    assert strip_fences(raw) == "x = 1"


def test_strip_fences_with_surrounding_text():
    raw = "Here you go:\n```python\nx = 1\n```\nHope that helps!"
    assert strip_fences(raw) == "x = 1"


def test_strip_fences_leaves_plain_code_untouched():
    assert strip_fences("x = 1\n") == "x = 1"


def test_strip_fences_unclosed_fence():
    assert strip_fences("```python\nx = 1") == "x = 1"


def test_is_valid_python():
    assert is_valid_python("x = 1")[0]
    ok, message = is_valid_python("def f(:")
    assert not ok and message


def test_slugify():
    assert slugify("Write a function that checks if a number is prime") == "checks_if_number_is_prime"
    assert slugify("!!!") == "generated_code"


def test_unique_path(tmp_path: Path):
    (tmp_path / "demo.py").write_text("")
    assert unique_path(tmp_path, "demo").name == "demo_2.py"


def test_read_batch_file(tmp_path: Path):
    batch = tmp_path / "tasks.txt"
    batch.write_text("# comment\n\ntask one\n  task two  \n")
    assert read_batch_file(batch) == ["task one", "task two"]


def test_generate_code_retries_on_syntax_error(monkeypatch):
    replies = iter(["```python\ndef f(:\n```", "```python\ndef f():\n    return 1\n```"])
    monkeypatch.setitem(__import__("codegen").PROVIDERS, "groq", lambda messages, model: next(replies))
    assert generate_code("anything", "groq", "m") == "def f():\n    return 1"


def test_generate_code_gives_up(monkeypatch):
    monkeypatch.setitem(__import__("codegen").PROVIDERS, "groq", lambda messages, model: "def f(:")
    with pytest.raises(GenerationError):
        generate_code("anything", "groq", "m", max_attempts=2)
