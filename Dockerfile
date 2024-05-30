# Użyj oficjalnego obrazu Pythona 3.11 jako bazowego
FROM python:3.11-slim

# Instalacja narzędzi systemowych oraz Gita
RUN apt-get update && apt-get install -y build-essential libssl-dev git

# Ustaw katalog roboczy w kontenerze
WORKDIR /app

# Skopiuj pliki projektu do kontenera
COPY . /app

# Zainstaluj zależności wymagane przez Twój projekt
RUN pip install --no-cache-dir -r requirements.txt

# Komenda uruchamiająca Twój skrypt Pythona
CMD ["sh", "-c", "python main_without_ssl.py --username $username --password $password --server $server --env $env --url $url"]
