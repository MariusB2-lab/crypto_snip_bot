# Bot de Trading Automatisé

Ce projet est un bot de trading automatisé utilisant l'API de l'échange MEXC. Le bot surveille les paires de trading, place des ordres d'achat et de vente, et utilise un stop suiveur pour maximiser les profits.

## Fonctionnalités

- **Surveillance des paires de trading** : Le bot surveille les paires de trading définies via des commandes Telegram.
- **Placement d'ordres** : Le bot place des ordres d'achat et de vente en fonction des conditions du marché.
- **Stop suiveur** : Utilisation d'un stop suiveur pour sécuriser les profits.
- **Notifications Telegram** : Envoi de notifications via Telegram pour informer des actions du bot.

## Prérequis

- Python 3.6 ou supérieur
- Bibliothèques Python : `ccxt`, `requests`, `logging`, `json`, `threading`, `datetime`, `os`, `functools`, `signal`, `sys`

## Installation

1. Clonez ce dépôt :
    ```bash
    git clone [(https://github.com/MariusB2-lab/crypto_snip_bot.git]
    cd crypto_snip_bot
    ```

2. Installez les dépendances :
    ```bash
    pip install -r requirements.txt
    ```

3. Configurez les informations d'authentification dans le fichier `config.json` :
    ```python
    "usdt_amount": 12,
    "fee_percentage": 0.001,
    "telegram_poll_interval": 10,
    "main_loop_interval": 10,
    "exchange_auth": {
        "apiKey": "votre_api_key",
        "secret": "votre_secret"
    },
    "bot_token": "votre_bot_token",
    "bot_chatID": "votre_chat_id"
    ```

## Utilisation

1. Lancez le bot :
    ```bash
    python bot_snip.py
    ```

2. Utilisez les commandes Telegram pour interagir avec le bot :
    - `/change_paire <paire>` : Change la paire de trading actuelle.

## Fichiers Importants

- `bot_snip.py` : Le script principal du bot.
- `config.py` : Fichier de configuration pour les informations d'authentification.
- `open_position.json` : Fichier pour sauvegarder l'état de la position ouverte.
- `traded_pairs.json` : Fichier pour sauvegarder les paires déjà tradées.
- `symbols.json` : Fichier pour sauvegarder les symboles disponibles sur l'échange.

## Contribuer

Les contributions sont les bienvenues! Veuillez soumettre une pull request ou ouvrir une issue pour discuter des changements que vous souhaitez apporter.

## Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Avertissement

Le trading de cryptomonnaies comporte des risques. Utilisez ce bot à vos propres risques. L'auteur n'est pas responsable des pertes financières.
