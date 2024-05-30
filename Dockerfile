FROM python:3.11-slim

RUN apt-get update && apt-get install -y build-essential libssl-dev git

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV url=/strategy

CMD ["sh", "-c", "python main_without_ssl.py --username $username --password $password --server $server --env $env --url $url"]
