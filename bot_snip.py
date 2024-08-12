import logging
import ccxt
import requests
import time
from datetime import datetime
import threading
from config import exchange_auth, bot_token, bot_chatID
import json
import os
import decimal
from functools import wraps

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Initialiser la variable de la paire à trader
current_pair = 'POPCATUSDT'

# Fonction pour le changement de paire via Telegram
def change_pair(update: Update, context: CallbackContext):
    global current_pair
    if context.args:
        new_pair = context.args[0].upper().replace('-', '')  # Retirer les tirets pour MEXC
        logging.info(f"Changement de la paire à trader : {current_pair} -> {new_pair}")
        current_pair = new_pair
        update.message.reply_text(f"Paire changee en {new_pair}")
        telegram_send(f"Paire changee en {new_pair}")
    else:
        update.message.reply_text("Veuillez spécifier la nouvelle paire, par exemple : /change_pair ETH/USDT")

# Initialisation du bot Telegram
def start_bot():
    updater = Updater(token=bot_token, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler('change_pair', change_pair))
    updater.start_polling()

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

def authentication_required(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        if not self._auth:
            message = "You must be authenticated to use this method"
            logging.error(message)
            telegram_send(message)
            exit()
        return fn(self, *args, **kwargs)
    return wrapped

class SpotExchange():
    def __init__(self, exchange_name, apiKey=None, secret=None, dry_run=False):
        self.exchange_name = exchange_name
        self._auth = secret is not None
        self.dry_run = dry_run
        try:
            self._session = getattr(ccxt, exchange_name)({
                "apiKey": apiKey,
                "secret": secret,
            }) if self._auth else getattr(ccxt, exchange_name)()
            self.market = self._session.load_markets()

            if exchange_name == "mexc":
                self._session.options['createMarketBuyOrderRequiresPrice'] = False

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
            logging.error(f"Erreur lors de la recuperation du prix pour {pair}: {e}")
            return None

    def convert_amount_to_precision(self, symbol, amount):
        return self._session.amount_to_precision(symbol, amount)

    def convert_price_to_precision(self, symbol, price):
        return self._session.price_to_precision(symbol, price)

    def get_balance(self):
        try:
            balance = self._session.fetch_balance()
            usdt_balance = balance['free'].get('USDT', 0)
            return float(usdt_balance)
        except Exception as e:
            logging.error(f"Erreur lors de la récupération du solde: {e}")
            return 0.0

    def get_minimum_trade_amount(self, symbol):
        try:
            market = self._session.market(symbol)
            return market['limits']['amount']['min']
        except Exception as e:
            logging.error(f"Erreur lors de la récupération du montant minimum pour {symbol}: {e}")
            return 0.0  # Retourne 0.0 au lieu de None en cas d'erreur

    @authentication_required
    def place_order(self, symbol, side, quantity, price):
        if self.dry_run:
            logging.info(f"[DRY RUN] {side} order of {quantity} {symbol} at {price} USDT would be placed.")
            return None
        try:
            order = self._session.create_order(symbol, 'limit', side, quantity, price)
            logging.info(f"Order response: {order}")
            return order
        except ccxt.InsufficientFunds as e:
            logging.error(f"Fonds insuffisants pour {side} {quantity} {symbol}: {e}")
            telegram_send(f"Fonds insuffisants pour {side} {quantity} {symbol}: {e}")
        except ccxt.ExchangeError as e:
            logging.error(f"Erreur d'échange lors du placement de l'ordre marché pour {symbol}: {e}")
            telegram_send(f"Erreur d'échange lors du placement de l'ordre marché pour {symbol}: {e}")
        except ValueError as e:
            logging.error(f"Erreur de valeur pour l'ordre marché: {e}")
            telegram_send(f"Erreur de valeur pour l'ordre marché: {e}")
        except Exception as e:
            logging.error(f"Erreur inattendue lors du placement de l'ordre marché pour {symbol}: {e}")
            telegram_send(f"Erreur inattendue lors du placement de l'ordre marché pour {symbol}: {e}")
        return None

def get_symbols(exchange_name):
    try:
        if exchange_name == "mexc":
            url = 'https://api.mexc.com/api/v3/exchangeInfo'
        elif exchange_name == "kucoin":
            url = 'https://api.kucoin.com/api/v1/symbols'
        else:
            logging.error("Erreur: echange non supporte.")
            return []

        response = requests.get(url)
        
        if response.status_code != 200:
            logging.error(f"Erreur de connexion: {response.status_code} - {response.text}")
            return []

        try:
            response_json = response.json()
        except ValueError as e:
            logging.error(f"Erreur lors de l'analyse de la reponse JSON: {e}, Reponse brute: {response.text}")
            return []

        if not hasattr(get_symbols, "logged_success"):
            logging.info("Reponse de l'API recuperee avec succès.")
            get_symbols.logged_success = True

        if exchange_name == "mexc" and 'symbols' in response_json:
            return [pair['symbol'].replace('-', '') for pair in response_json['symbols'] if 'USDT' in pair['symbol']]
        elif 'data' in response_json:
            return [pair['symbol'] for pair in response_json['data'] if pair.get('enableTrading', True) and 'USDT' in pair['symbol']]
        else:
            logging.error("Erreur: 'data' ou 'symbols' non trouve dans la reponse de l'API ou mauvaise structure de la reponse.")
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de connexion lors de la recuperation des symboles: {e}")
        return []
    except Exception as e:
        logging.error(f"Erreur inattendue: {e}")
        return []

# Fonction pour charger les paires tradees depuis un fichier JSON
def load_traded_pairs(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return set(json.load(f))
    return set()

# Fonction pour sauvegarder les paires tradees dans un fichier JSON
def save_traded_pairs(file_path, traded_pairs):
    with open(file_path, 'w') as f:
        json.dump(list(traded_pairs), f)
    logging.info(f"Les paires tradees ont ete sauvegardees dans {file_path}: {traded_pairs}")

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
    logging.info(f"Les symboles ont ete sauvegardes dans {file_path}: {symbols}")

def get_current_price(perp_symbol, exchange_name):
    try:
        url = ""
        if exchange_name == "mexc":
            url = f"https://api.mexc.com/api/v3/ticker/price?symbol={perp_symbol.replace('/', '')}"
        elif exchange_name == "kucoin":
            url = f"https://api.kucoin.com/api/v1/prices?symbol={perp_symbol.replace('/', '-')}"
        else:
            return exchange.fetch_ticker(perp_symbol)['last']  # Assurez-vous que cette méthode existe et est correcte

        response = requests.get(url)
        response.raise_for_status()  # Cela lèvera une exception si le code de statut HTTP n'est pas 200
        data = response.json()
        price = float(data.get("price") if exchange_name == "mexc" else data["data"].get(perp_symbol.replace('/', '-')))
        return price
    except requests.exceptions.HTTPError as e:
        logging.error(f"Erreur HTTP lors de la récupération du prix pour {perp_symbol}: {e}")
    except ValueError as e:
        logging.error(f"Erreur lors de l'analyse de la réponse JSON pour {perp_symbol}: {e}")
    except KeyError as e:
        logging.error(f"Clé manquante dans la réponse JSON pour {perp_symbol}: {e}")
    return None

def get_balance(exchange):
    try:
        balance_data = exchange.fetch_balance()['total']
        return float(balance_data.get('USDT', 0))
    except Exception as e:
        logging.error(f"Erreur lors de la recuperation du solde: {e}")
        return 0.0

def trailing_stop(symbol, exchange, buy_price, quantity):
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
            exchange.place_order(symbol, 'sell', quantity, close_price)
            break

        price_change_percent = ((close_price - buy_price) / buy_price) * 100

        if price_change_percent >= 0:
            variation_message = f"Gain de {price_change_percent:.2f}%"
        else:
            variation_message = f"Perte de {price_change_percent:.2f}%"

        logging.info(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop_value} | {variation_message}")
        telegram_send(f"📈 Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop_value} | {variation_message}")
        
        time.sleep(1)

def is_symbol_supported(symbol, exchange_name):
    try:
        symbols = get_symbols(exchange_name)
        return symbol in symbols
    except Exception as e:
        logging.error(f"Erreur lors de la vérification du symbole supporté: {e}")
        return False

# Verifier si le fichier traded_pairs.json existe, sinon le creer
traded_pairs_file = 'traded_pairs.json'
if not os.path.exists(traded_pairs_file):
    with open(traded_pairs_file, 'w') as f:
        json.dump([], f)

# Charger les paires tradees
traded_pairs = load_traded_pairs(traded_pairs_file)

# Choix de l'echange
exchange_name = "mexc"
symbols_file = 'symbols.json'
symbols = load_symbols(symbols_file)

if not symbols:
    symbols = get_symbols(exchange_name)
    save_symbols(symbols_file, symbols)

dry_run_mode = False
exchange = SpotExchange(exchange_name, **exchange_auth, dry_run=dry_run_mode)
logging.info(f"Symboles recuperes : {symbols}")

# Démarrer le bot Telegram
threading.Thread(target=start_bot, daemon=True).start()

while True:
    try:
        perp_list_base = get_symbols(exchange_name)
        if current_pair in perp_list_base:
            logging.info(f"{str(datetime.now()).split('.')[0]} | Tentative de sniping sur {current_pair}")
            current_price = get_current_price(current_pair, exchange_name)
            if current_price is None or current_price == 0:
                logging.info(f"{str(datetime.now()).split('.')[0]} | {current_pair} n'est pas disponible ou le prix est zéro. Attente que la paire soit listée.")
                telegram_send(f"{str(datetime.now()).split('.')[0]} | {current_pair} n'est pas disponible ou le prix est zéro. Attente que la paire soit listée.")
                time.sleep(200)
                continue

            usdt_amount = 12  # Montant fixe en USDT pour l'achat
            usdt_balance = exchange.get_balance()
            
            if usdt_amount > usdt_balance:
                logging.warning(f"Le montant d'achat ({usdt_amount} USDT) est supérieur au solde disponible ({usdt_balance} USDT). Ajustement du montant d'achat.")
                usdt_amount = usdt_balance * 0.95  # Utilise 95% du solde disponible

            current_price = float(current_price)  # Assurez-vous que current_price est un float
            quantity = usdt_amount / current_price
            quantity = float(exchange.convert_amount_to_precision(current_pair, quantity))  # Assurez-vous que quantity est un float

            # Ajuster le montant pour tenir compte des frais de transaction
            fee_percentage = 0.001  # Exemple de frais de 0.1%
            adjusted_quantity = quantity * (1 - fee_percentage)
            adjusted_cost = adjusted_quantity * current_price

            if adjusted_cost > usdt_balance:
                logging.error(f"Solde insuffisant pour acheter {adjusted_quantity} {current_pair} au prix actuel de {current_price}. Coût ajusté : {adjusted_cost} USDT. Solde disponible : {usdt_balance} USDT.")
                telegram_send(f"Solde insuffisant pour acheter {adjusted_quantity} {current_pair} au prix actuel de {current_price}. Coût ajusté : {adjusted_cost} USDT. Solde disponible : {usdt_balance} USDT.")
                continue

            exchange.reload_markets()

            try:
                if is_symbol_supported(current_pair, exchange_name):
                    order_response = exchange.place_order(current_pair, "buy", adjusted_quantity, current_price)
                    purchase_price = current_price
                    logging.info(f"{str(datetime.now()).split('.')[0]} | Buy {current_pair} Order success at price: {purchase_price} USDT!")
                    telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ Buy {current_pair} Order success at price: {purchase_price} USDT!")

                    logging.info(f"{str(datetime.now()).split('.')[0]} | Waiting for sell...")
                    telegram_send(f"⌛ Waiting for sell...")

                    trailing_stop(current_pair, exchange, purchase_price, adjusted_quantity)

                    sell_price = exchange.get_price(current_pair)
                    profit_percentage = ((sell_price - purchase_price) / purchase_price) * 100 if purchase_price else 0

                    exchange.place_order(current_pair, "sell", adjusted_quantity, sell_price)
                    logging.info(f"{str(datetime.now()).split('.')[0]} | Sell {current_pair} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}%")
                    telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ 💯 Sell {current_pair} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}%")

                    traded_pairs.add(current_pair)
                    save_traded_pairs(traded_pairs_file, traded_pairs)
                else:
                    logging.error(f"Le symbole {current_pair} n'est pas supporté par l'API de l'échange {exchange_name}.")
                    telegram_send(f"Le symbole {current_pair} n'est pas supporté par l'API de l'échange {exchange_name}.")
            except ccxt.ExchangeError as e:
                logging.error(f"Erreur d'échange lors du placement de l'ordre marché pour {current_pair}: {e}")
                telegram_send(f"Erreur d'échange lors du placement de l'ordre marché pour {current_pair}: {e}")
            except Exception as e:
                logging.error(f"Erreur inattendue lors de la transaction pour {current_pair}: {e}")
                telegram_send(f"Erreur inattendue lors de la transaction pour {current_pair}: {e}")
        else:
            logging.info(f"{str(datetime.now()).split('.')[0]} | {current_pair} n'est pas dans la liste des symboles ou a déjà ete trade.")
            logging.info(f"{str(datetime.now()).split('.')[0]} | Attente de 200 secondes pour que la paire soit listee.")
            time.sleep(200)
    except Exception as e:
        logging.error(f"Erreur dans la boucle principale: {e}")
        time.sleep(5)
