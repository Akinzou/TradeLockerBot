"""Fitness function: the image starts the bot with no shell and no arguments.

The start command ran ``sh -c`` over the credentials and the webhook path,
expanded unquoted: the shell split, expanded and globbed a password, and every
value sat in the command line, which the host's process list shows to all its
users. The bot now reads its settings from the environment (ADR 0018), so the
command needs neither; this keeps either from coming back, since no test of
the bot reads the Dockerfile.
"""

import json
import re

from tests.dependency_lock import ROOT


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


def test_an_instruction_in_lower_case_or_over_several_lines_is_found():
    text = 'FROM x\nentrypoint ["sh", \\\n  "-c", "run $password"]\nCmd ["a"]\n'

    assert [json.loads(found) for found in instructions("ENTRYPOINT", text)] == [["sh", "-c", "run $password"]]
    assert instructions("CMD", text) == ['["a"]']
