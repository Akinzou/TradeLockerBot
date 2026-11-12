"""Read the Dockerfile and the lock the way the image build reads them.

One reader for the tests and for CI: the image steps take the base image and
the lock's Python from here rather than from a ``sed`` of their own, so the
two cannot disagree on what the base image is (ADR 0019).

    python -m tests.dockerfile base         the image the last FROM names
    python -m tests.dockerfile lock-python  the Python the lock was compiled for
"""

import argparse
import re

from tests.dependency_lock import LOCK, ROOT

DOCKERFILE = ROOT / "Dockerfile"

# A tag and a full digest. Docker reads only the digest, which names one
# image for good; the tag is what Dependabot tracks to propose the next one,
# so a reference without it would never be bumped. The tag follows the last
# `/`, so a registry's port does not count as one.
PINNED = re.compile(r"(?P<tag>(?:[^@\s/]+/)*[^@\s/:]+:[^@\s/:]+)@sha256:[0-9a-f]{64}")


def instructions(keyword, text=None):
    """The arguments of each Dockerfile instruction with this keyword.

    Read as Docker reads them: a keyword in any case, and a line ending in
    ``\\`` continued on the next, so neither hides an instruction.
    """
    if text is None:
        text = DOCKERFILE.read_text(encoding="utf-8")
    logical = re.sub(r"\\[ \t]*\r?\n", " ", text).splitlines()
    found = []
    for line in logical:
        parts = line.split(None, 1)
        if parts and parts[0].upper() == keyword.upper():
            found.append(parts[1] if len(parts) > 1 else "")
    return found


def image_reference(arguments):
    """The image a ``FROM`` names, past ``--platform=`` and ``AS name``."""
    return next(word for word in arguments.split() if not word.startswith("--"))


def base_image(text=None):
    """The image the last ``FROM`` names: the one the bot runs on."""
    return image_reference(instructions("FROM", text)[-1])


def lock_python(text=None):
    """The ``major.minor`` Python the lock was compiled for, from its header.

    A patch version is refused rather than cut to ``major.minor``: the image
    tag names a minor only, so the two could not be compared.
    """
    if text is None:
        text = LOCK.read_text(encoding="utf-8")
    found = re.search(r"--python-version (\d+\.\d+)(?=\s)", text)
    if found is None:
        raise ValueError("the lock's header names no --python-version major.minor")
    return found[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("value", choices=["base", "lock-python"])
    args = parser.parse_args(argv)
    print(base_image() if args.value == "base" else lock_python())


if __name__ == "__main__":
    main()
