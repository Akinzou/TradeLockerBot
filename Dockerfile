# By digest, not by tag alone: the tag moves, so a rebuild of the same commit
# could change the interpreter and the system libraries unreviewed, and the
# image CI tested would not be the one published (ADR 0019). The digest is
# the multi-platform index's, so each platform still gets its own image. The
# tag stays for Dependabot, which proposes the tag's new digest as a pull
# request; Docker itself reads only the digest. 3.11 is the Python the lock
# was compiled for.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

WORKDIR /app

# The lock, not requirements.txt: every package, transitive ones included, at
# one version and verified by hash (ADR 0007). Wheels only: building from
# source would fetch unhashed build tools and need a compiler in the image,
# which is why the apt toolchain layer is gone. Copied before the source so
# a code change does not reinstall every package. No dependency resolution:
# the lock overrides the tradelocker client's pins on packages with published
# advisories, which pip would refuse (ADR 0017). The lock is complete by
# construction, and CI checks it (tests/dependency_closure.py).
COPY requirements-lock.txt /app/
RUN pip install --no-cache-dir --require-hashes --only-binary :all: --no-deps -r requirements-lock.txt

COPY . /app

# No shell and no arguments: the bot reads its settings from the container's
# environment (ADR 0018). The shell split, expanded and globbed the password,
# and the arguments put the credentials and the webhook path in the host's
# process list, which every user of the host can read. The optional settings'
# defaults live in the bot alone, so the image sets no variable.
CMD ["python", "main_without_ssl.py"]
