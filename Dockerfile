FROM python:3.11-slim

RUN apt-get update && apt-get install -y build-essential libssl-dev git

WORKDIR /app

COPY . /app

# The lock, not requirements.txt: every package, transitive ones included, at
# one version and verified by hash, so a rebuild installs what CI tested.
RUN pip install --no-cache-dir --require-hashes -r requirements-lock.txt

ENV url=/strategy
ENV acc_num=0
ENV acc_id=0

CMD ["sh", "-c", "python main_without_ssl.py --username $username --password $password --server $server --env $env --url $url --acc_num $acc_num --acc_id $acc_id"]
