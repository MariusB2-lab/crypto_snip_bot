import logging
import ccxt
import pandas as pd
import requests
import time
from datetime import datetime
import threading
from config import exchange_auth, bot_token, bot_chatID
import json
import os

# Configuration du logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


# Fonction pour envoyer des messages via Telegram
def telegram_send(message):
    send_text = f'https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={bot_chatID}&parse_mode=Markdown&text={message}'
    threading.Thread(target=requests.get, args=(send_text,)).start()


def retry(exceptions, tries=5, delay=3, backoff=2):
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    logging.warning(f"{e}, Retrying in {mdelay} seconds...")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry


class SpotExchange():
    def __init__(self, exchange_name, apiKey=None, secret=None, dry_run=False):
        self.exchange_name = exchange_name
        self._auth = secret is not None
        self.dry_run = dry_run  # Ajout de l'attribut dry_run
        try:
            self._session = getattr(ccxt, exchange_name)({
                "apiKey": apiKey,
                "secret": secret,
            }) if self._auth else getattr(ccxt, exchange_name)()
            self.market = self._session.load_markets()
        except Exception as e:
            logging.error(f"Erreur lors de l'initialisation de l'API pour {exchange_name}: {e}")
            telegram_send(f"Erreur critique lors de l'initialisation de l'API pour {exchange_name}: {e}")
            raise


    def reload_markets(self):
        self.market = self._session.load_markets()

    def get_price(self, pair):
        try:
            return self._session.fetch_ticker(pair)['last']
        except Exception as e:
            logging.error(f"Erreur lors de la récupération du prix pour {pair}: {e}")
            return None

    def authentication_required(fn):
        def wrapped(self, *args, **kwargs):
            if not self._auth:
                message = "You must be authenticated to use this method"
                logging.error(message)
                telegram_send(message)
                exit()
            return fn(self, *args, **kwargs)
        return wrapped

    def convert_amount_to_precision(self, symbol, amount):
        return self._session.amount_to_precision(symbol, amount)

    def convert_price_to_precision(self, symbol, price):
        return self._session.price_to_precision(symbol, price)

    @authentication_required
    def place_market_order(self, symbol, side, amount):
        if self.dry_run:
            logging.info(f"[DRY RUN] Order {side} {amount} of {symbol} would be placed.")
            return None
        try:
            return self._session.create_order(symbol, 'market', side, self.convert_amount_to_precision(symbol, amount), None)
        except Exception as e:
            logging.error(f"Erreur lors du placement de l'ordre marché: {e}")
            return None

    @authentication_required
    def place_limit_order(self, symbol, side, amount, price):
        if self.dry_run:
            logging.info(f"[DRY RUN] Limit order {side} {amount} of {symbol} at {price} would be placed.")
            return None
        try:
            return self._session.create_order(symbol, 'limit', side, self.convert_amount_to_precision(symbol, amount), self.convert_price_to_precision(symbol, price))
        except Exception as e:
            logging.error(f"Erreur lors du placement de l'ordre limite: {e}")
            return None


def get_symbols(exchange_name):
    try:
        if exchange_name == "mexc":
            url = 'https://api.mexc.com/api/v3/exchangeInfo'
        elif exchange_name == "kucoin":
            url = 'https://api.kucoin.com/api/v1/symbols'
        else:
            logging.error("Erreur: Échange non supporté.")
            return []

        response = requests.get(url)
        
        if response.status_code != 200:
            logging.error(f"Erreur de connexion: {response.status_code} - {response.text}")
            return []

        try:
            response_json = response.json()
        except ValueError as e:
            logging.error(f"Erreur lors de l'analyse de la réponse JSON: {e}, Réponse brute: {response.text}")
            return []

        if not hasattr(get_symbols, "logged_success"):
            logging.info("Réponse de l'API récupérée avec succès.")
            get_symbols.logged_success = True

        if exchange_name == "mexc" and 'symbols' in response_json:
            return [pair['symbol'] for pair in response_json['symbols'] if 'USDT' in pair['symbol']]
        elif 'data' in response_json:
            return [pair['symbol'] for pair in response_json['data'] if pair.get('enableTrading', True) and 'USDT' in pair['symbol']]
        else:
            logging.error("Erreur: 'data' ou 'symbols' non trouvé dans la réponse de l'API ou mauvaise structure de la réponse.")
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de connexion lors de la récupération des symboles: {e}")
        return []
    except Exception as e:
        logging.error(f"Erreur inattendue: {e}")
        return []

# Fonction pour charger les paires tradées depuis un fichier JSON
def load_traded_pairs(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return set(json.load(f))
    return set()

# Fonction pour sauvegarder les paires tradées dans un fichier JSON
def save_traded_pairs(file_path, traded_pairs):
    with open(file_path, 'w') as f:
        json.dump(list(traded_pairs), f)
    logging.info(f"Les paires tradées ont été sauvegardées dans {file_path}: {traded_pairs}")  # Log ajout

# Fonction pour charger les symboles depuis un fichier JSON
def load_symbols(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

# Fonction pour sauvegarder les symboles dans un fichier JSON
def save_symbols(file_path, symbols):
    with open(file_path, 'w') as f:
        json.dump(symbols, f)
    logging.info(f"Les symboles ont été sauvegardés dans {file_path}: {symbols}")  # Log ajout

def get_current_price(perp_symbol, exchange_name):
    try:
        if exchange_name == "mexc":
            url = f"https://api.mexc.com/api/v3/ticker/price?symbol={perp_symbol.replace('/', '')}"
            ticker = requests.get(url).json()
            return float(ticker["price"])
        elif exchange_name == "kucoin":
            url = f"https://api.kucoin.com/api/v1/prices?symbol={perp_symbol.replace('/', '-')}"
            ticker = requests.get(url).json()
            return float(ticker["data"][perp_symbol.replace('/', '-')])
        else:
            ticker = exchange.fetch_ticker(perp_symbol)
            return float(ticker["last"])
    except Exception as e:
        logging.error(f"Erreur lors de la récupération du prix pour {perp_symbol}: {e}")
        return None


def get_balance(exchange):
    try:
        balance_data = exchange.fetch_balance()['total']
        return float(balance_data.get('USDT', 0))
    except Exception as e:
        logging.error(f"Erreur lors de la récupération du solde: {e}")
        return 0.0


def trailing_stop(symbol, exchange):
    ath = exchange.get_price(symbol)
    if ath is None:
        return

    trailing_stop_value = ath * 0.99
    while True:
        close_price = exchange.get_price(symbol)
        if close_price is None:
            break

        if close_price > ath:
            ath = close_price
            trailing_stop_value = ath * 0.99
        if close_price < trailing_stop_value:
            logging.info(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop_value} Executed")
            break
        logging.info(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop_value}")
        telegram_send(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop_value}")
        time.sleep(1)


# Vérifier si le fichier traded_pairs.json existe, sinon le créer
traded_pairs_file = 'traded_pairs.json'
if not os.path.exists(traded_pairs_file):
    with open(traded_pairs_file, 'w') as f:
        json.dump([], f)  # Créer un fichier vide

# Charger les paires tradées
traded_pairs = load_traded_pairs(traded_pairs_file)

# Choix de l'échange
exchange_name = "mexc"
symbols_file = 'symbols.json'
symbols = load_symbols(symbols_file)  # Charger les symboles depuis le fichier JSON

if not symbols:  # Si le fichier est vide, récupérer les symboles depuis l'API
    symbols = get_symbols(exchange_name)
    save_symbols(symbols_file, symbols)  # Sauvegarder les symboles dans le fichier JSON

dry_run_mode = True
exchange = SpotExchange(exchange_name, **exchange_auth, dry_run=dry_run_mode)
logging.info(f"Symboles récupérés : {symbols}")

while True:
    try:
        pairs = 'BABYUSDT'  # Définir le symbole que vous souhaitez trader
        amount = 12

        # Vérifier si le symbole est dans la liste récupérée et n'a pas encore été tradé
        if pairs in symbols and pairs not in traded_pairs:
            logging.info(f"{str(datetime.now()).split('.')[0]} | Tentative de sniping sur {pairs} avec {amount} USDT")
            current_price = get_current_price(pairs, exchange_name)
            if current_price is None:
                continue

            # Calculer le montant à acheter
            amount = amount / current_price * 1.30
            exchange.reload_markets()

            try:
                # Passer l'ordre d'achat
                order_response = exchange.place_market_order(pairs, "buy", amount)
                purchase_price = current_price  # Capturer le prix d'achat
                logging.info(f"{str(datetime.now()).split('.')[0]} | Buy {pairs} Order success at price: {purchase_price} USDT!")
                telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ Buy {pairs} Order success at price: {purchase_price} USDT!")

                logging.info(f"{str(datetime.now()).split('.')[0]} | Waiting for sell...")
                telegram_send(f"⌛ Waiting for sell...")

                trailing_stop(pairs, exchange)

                # Récupérer le prix de vente
                sell_price = exchange.get_price(pairs)
                profit_percentage = ((sell_price - purchase_price) / purchase_price) * 100 if purchase_price else 0

                exchange.place_market_order(pairs, "sell", amount)
                logging.info(f"{str(datetime.now()).split('.')[0]} | Sell {pairs} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}%")
                telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ 💯 Sell {pairs} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}%")

                traded_pairs.add(pairs)  # Ajouter la paire à l'ensemble des paires tradées
                save_traded_pairs(traded_pairs_file, traded_pairs)  # Sauvegarder les paires tradées
            except Exception as e:
                logging.error(f"Erreur lors de la transaction pour {pairs}: {e}")
                telegram_send(f"Erreur: {e}")
        else:
            logging.info(f"{str(datetime.now()).split('.')[0]} | {pairs} n'est pas dans la liste des symboles ou a déjà été tradé.")
            logging.info(f"{str(datetime.now()).split('.')[0]} | Attente de 200 secondes pour que la paire soit listée.")
            time.sleep(200)  # Attendre 200 secondes avant de réessayer
    except Exception as e:
        logging.error(f"Erreur dans la boucle principale: {e}")
        time.sleep(5)
