# Utiliser une image de base Python
FROM python:3.11-bullseye

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier les fichiers nécessaires dans le conteneur
COPY bot_snip.py .
COPY config.json .

# Installer les dépendances
RUN pip3 install --no-cache-dir -r requirements.txt

# Lancer le script Python
CMD ["python", "bot_snip.py"]
