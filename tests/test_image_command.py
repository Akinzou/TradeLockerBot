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
import re

from tests.dependency_lock import LOCK, ROOT

# A digest names one image for good; Docker reads it and ignores the tag.
PINNED = re.compile(r"(?P<tag>[^@\s]+)@sha256:[0-9a-f]{64}")


def instructions(keyword, text=None):
    """The arguments of each Dockerfile instruction with this keyword.

    Read as Docker reads them: a keyword in any case, and a line ending in
    ``\\`` continued on the next, so neither hides an instruction.
    """
    if text is None:
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    logical = re.sub(r"\\[ \t]*\r?\n", " ", text).splitlines()
    found = []
    for line in logical:
        parts = line.split(None, 1)
        if parts and parts[0].upper() == keyword.upper():
            found.append(parts[1] if len(parts) > 1 else "")
    return found


def test_the_image_runs_the_entrypoint_with_no_shell_and_no_arguments():
    [command] = instructions("CMD")

    # The JSON form: Docker runs it as it is, with no shell in between.
    assert json.loads(command) == ["python", "main_without_ssl.py"]
    assert instructions("ENTRYPOINT") == []


def image_reference(arguments):
    """The image a ``FROM`` names, past ``--platform=`` and ``AS name``."""
    return next(word for word in arguments.split() if not word.startswith("--"))


def lock_python():
    """The Python version the lock was compiled for, from its header."""
    return re.search(r"--python-version (\d+\.\d+)\b", LOCK.read_text(encoding="utf-8"))[1]


def test_every_base_image_is_pinned_by_digest():
    bases = [image_reference(arguments) for arguments in instructions("FROM")]

    assert bases
    for base in bases:
        assert PINNED.fullmatch(base), base


def test_the_image_runs_on_the_slim_python_the_lock_was_compiled_for():
    # The tag is what Dependabot tracks to propose a new digest; Docker
    # ignores it, so CI checks the interpreter the image really runs too.
    final = PINNED.fullmatch(image_reference(instructions("FROM")[-1]))

    assert final
    assert final["tag"] == f"python:{lock_python()}-slim"


def test_the_image_a_from_names_is_found_past_its_flags_and_stage_name():
    found = image_reference("--platform=$BUILDPLATFORM python:3.11-slim@sha256:ab AS build")

    assert found == "python:3.11-slim@sha256:ab"
    assert image_reference("python:3.11-slim") == "python:3.11-slim"


def test_a_reference_is_pinned_only_with_a_tag_and_a_full_digest():
    digest = "sha256:" + "0" * 64

    assert PINNED.fullmatch(f"python:3.11-slim@{digest}")
    assert not PINNED.fullmatch("python:3.11-slim")
    assert not PINNED.fullmatch(f"python:3.11-slim@{digest[:-1]}")
    assert not PINNED.fullmatch(f"python:3.11-slim@{digest.upper()}")
    assert not PINNED.fullmatch(f"@{digest}")


def test_an_instruction_in_lower_case_or_over_several_lines_is_found():
    text = 'FROM x\nentrypoint ["sh", \\\n  "-c", "run $password"]\nCmd ["a"]\n'

    assert [json.loads(found) for found in instructions("ENTRYPOINT", text)] == [["sh", "-c", "run $password"]]
    assert instructions("CMD", text) == ['["a"]']
