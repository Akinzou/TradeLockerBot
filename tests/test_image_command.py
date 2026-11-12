"""Fitness function: the image starts the bot with no shell and no arguments.

The start command ran ``sh -c`` over the credentials and the webhook path,
expanded unquoted: the shell split, expanded and globbed a password, and every
value sat in the command line, which the host's process list shows to all its
users. The bot now reads its settings from the environment (ADR 0018), so the
command needs neither; this keeps either from coming back, since no test of
the bot reads the Dockerfile.
"""

import json

from tests.dependency_lock import ROOT


def instructions(keyword):
    """The arguments of each Dockerfile instruction with this keyword."""
    lines = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    return [line.split(None, 1)[1] for line in lines if line.split(None, 1)[:1] == [keyword]]


def test_the_image_runs_the_entrypoint_with_no_shell_and_no_arguments():
    [command] = instructions("CMD")

    # The JSON form: Docker runs it as it is, with no shell in between.
    assert json.loads(command) == ["python", "main_without_ssl.py"]
    assert instructions("ENTRYPOINT") == []
