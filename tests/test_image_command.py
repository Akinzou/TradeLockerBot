"""Fitness functions on the Dockerfile, which no test of the bot reads.

The image starts the bot with no shell and no arguments. The start command
ran ``sh -c`` over the credentials and the webhook path, expanded unquoted:
the shell split, expanded and globbed a password, and every value sat in the
command line, which the host's process list shows to all its users. The bot
now reads its settings from the environment (ADR 0018), so the command needs
neither; this keeps either from coming back.

The image builds on a base pinned by digest, under the Python the lock was
compiled for (ADR 0019). A tag alone moves: a rebuild of the same commit
could change the interpreter or the system libraries, unreviewed.
"""

import json

import pytest

from tests.dockerfile import PINNED, base_image, image_reference, instructions, lock_python


def test_the_image_runs_the_entrypoint_with_no_shell_and_no_arguments():
    [command] = instructions("CMD")

    # The JSON form: Docker runs it as it is, with no shell in between.
    assert json.loads(command) == ["python", "main_without_ssl.py"]
    assert instructions("ENTRYPOINT") == []


def test_every_base_image_is_pinned_by_digest():
    bases = [image_reference(arguments) for arguments in instructions("FROM")]

    assert bases
    for base in bases:
        assert PINNED.fullmatch(base), base


def test_the_image_runs_on_the_slim_python_the_lock_was_compiled_for():
    # The tag is what Dependabot tracks to propose a new digest; Docker
    # ignores it, so CI checks the interpreter the image really runs too.
    final = PINNED.fullmatch(base_image())

    assert final
    assert final["tag"] == f"python:{lock_python()}-slim"


def test_the_image_a_from_names_is_found_past_its_flags_and_stage_name():
    found = image_reference("--platform=$BUILDPLATFORM python:3.11-slim@sha256:ab AS build")

    assert found == "python:3.11-slim@sha256:ab"
    assert image_reference("python:3.11-slim") == "python:3.11-slim"
    assert base_image("FROM --platform=x a:1 AS build\nfrom \\\n  b:2\n") == "b:2"


def test_a_reference_is_pinned_only_with_a_tag_and_a_full_digest():
    digest = "sha256:" + "0" * 64

    assert PINNED.fullmatch(f"python:3.11-slim@{digest}")
    assert PINNED.fullmatch(f"registry.example:5000/team/python:3.11-slim@{digest}")
    assert not PINNED.fullmatch("python:3.11-slim")
    assert not PINNED.fullmatch(f"python:3.11-slim@{digest[:-1]}")
    assert not PINNED.fullmatch(f"python:3.11-slim@{digest.upper()}")
    assert not PINNED.fullmatch(f"@{digest}")
    # Without a tag Dependabot has nothing to track, so the digest would
    # never be bumped; a registry's port is not a tag.
    assert not PINNED.fullmatch(f"python@{digest}")
    assert not PINNED.fullmatch(f"registry.example:5000/python@{digest}")


def test_the_locks_python_is_read_as_major_and_minor_only():
    header = "#    uv pip compile requirements.txt --python-version {} --generate-hashes\n"

    assert lock_python(header.format("3.11")) == "3.11"
    # A patch version cannot be compared with the image tag, which names a
    # minor: refused rather than cut to 3.11.
    with pytest.raises(ValueError, match="names no --python-version major.minor"):
        lock_python(header.format("3.11.9"))
    with pytest.raises(ValueError, match="names no --python-version major.minor"):
        lock_python("#    uv pip compile requirements.txt\n")


def test_an_instruction_in_lower_case_or_over_several_lines_is_found():
    text = 'FROM x\nentrypoint ["sh", \\\n  "-c", "run $password"]\nCmd ["a"]\n'

    assert [json.loads(found) for found in instructions("ENTRYPOINT", text)] == [["sh", "-c", "run $password"]]
    assert instructions("CMD", text) == ['["a"]']
