FROM python:3.11-slim

WORKDIR /app

# The lock, not requirements.txt: every package, transitive ones included, at
# one version and verified by hash (ADR 0007). Wheels only: building from
# source would fetch unhashed build tools and need a compiler in the image,
# which is why the apt toolchain layer is gone. Copied before the source so
# a code change does not reinstall every package.
COPY requirements-lock.txt /app/
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements-lock.txt

COPY . /app

ENV url=/strategy
ENV acc_num=0
ENV acc_id=0

CMD ["sh", "-c", "python main_without_ssl.py --username $username --password $password --server $server --env $env --url $url --acc_num $acc_num --acc_id $acc_id"]
