import json
import logging
import ccxt
import requests
import time
from datetime import datetime
import threading
import os
from functools import wraps
import sys

# Charger les configurations depuis config.json
with open('config.json', 'r') as f:
    config = json.load(f)

exchange_auth = config['exchange_auth']
bot_token = config['bot_token']
bot_chatID = config['bot_chatID']

# Initialiser la variable de la paire à trader
current_pair = ''

# Fichier pour sauvegarder l'etat de la position ouverte
open_position_file = 'open_position.json'

# Configuration du logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Variable pour stocker le dernier message Telegram envoyé
last_telegram_message = None

# Fonction pour envoyer des messages via Telegram avec vérification de répétition
def telegram_send(message):
    global last_telegram_message
    if message != last_telegram_message:
        send_text = f'https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={bot_chatID}&parse_mode=Markdown&text={message}'
        threading.Thread(target=requests.get, args=(send_text,)).start()
        last_telegram_message = message

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
            sys.exit(1)
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

    def get_order_book(self, pair):
        try:
            return self._session.fetch_order_book(pair)
        except Exception as e:
            logging.error(f"Erreur lors de la recuperation de l'order book pour {pair}: {e}")
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
            logging.error(f"Erreur lors de la recuperation du solde: {e}")
            return 0.0

    def get_minimum_trade_amount(self, symbol):
        try:
            market = self._session.market(symbol)
            return market['limits']['amount']['min']
        except Exception as e:
            logging.error(f"Erreur lors de la recuperation du montant minimum pour {symbol}: {e}")
            return 0.0

    @authentication_required
    def place_order(self, symbol, side, quantity, price):
        if self.dry_run:
            logging.info(f"[DRY RUN] {side} order of {quantity} {symbol} at {price} USDT would be placed.")
            return None
        try:
            order = self._session.create_order(symbol, 'limit', side, quantity, price)
            logging.info(f"Order response: {order}")
            order_id = order['id']
            
            # Verifier l'etat de l'ordre
            while True:
                order_status = self._session.fetch_order(order_id, symbol)
                if order_status['status'] == 'closed':
                    logging.info(f"Order {order_id} for {symbol} has been executed.")
                    break
                logging.info(f"Order {order_id} for {symbol} is still open. Waiting...")
                time.sleep(5)

            return order
        except ccxt.InsufficientFunds as e:
            logging.error(f"Fonds insuffisants pour {side} {quantity} {symbol}: {e}")
            telegram_send(f"Fonds insuffisants pour {side} {quantity} {symbol}: {e}")
        except ccxt.ExchangeError as e:
            logging.error(f"Erreur d'echange lors du placement de l'ordre marche pour {symbol}: {e}")
            telegram_send(f"Erreur d'echange lors du placement de l'ordre marche pour {symbol}: {e}")
        except ValueError as e:
            logging.error(f"Erreur de valeur pour l'ordre marche: {e}")
            telegram_send(f"Erreur de valeur pour l'ordre marche: {e}")
        except Exception as e:
            logging.error(f"Erreur inattendue lors du placement de l'ordre marche pour {symbol}: {e}")
            telegram_send(f"Erreur inattendue lors du placement de l'ordre marche pour {symbol}: {e}")
        return None

def save_open_position(symbol, buy_price, quantity):
    with open(open_position_file, 'w') as f:
        json.dump({'symbol': symbol, 'buy_price': buy_price, 'quantity': quantity}, f)
    logging.info(f"Position ouverte sauvegardee: {symbol} à {buy_price} USDT pour {quantity} unites.")

def load_open_position():
    if os.path.exists(open_position_file) and os.path.getsize(open_position_file) > 0:
        with open(open_position_file, 'r') as f:
            return json.load(f)
    return None

def clear_open_position():
    if os.path.exists(open_position_file):
        os.remove(open_position_file)
    logging.info("Position ouverte efface.")

def get_second_bid_ask(exchange, symbol):
    order_book = exchange.get_order_book(symbol)
    if order_book:
        second_bid = order_book['bids'][1][0] if len(order_book['bids']) > 1 else None
        second_ask = order_book['asks'][1][0] if len(order_book['asks']) > 1 else None
        return second_bid, second_ask
    return None, None

def trailing_stop(symbol, exchange, buy_price, quantity):
    ath = exchange.get_price(symbol)
    if ath is None:
        return

    trailing_stop_value = ath * 0.99
    logging.info(f"Trailing stop initialisé à {trailing_stop_value} USDT pour {symbol}")

    while True:
        close_price = exchange.get_price(symbol)
        if close_price is None:
            break

        if close_price > ath:
            ath = close_price
            trailing_stop_value = ath * 0.99
            logging.info(f"Nouveau ATH: {ath} USDT, Trailing stop ajusté à {trailing_stop_value} USDT pour {symbol}")
            
        if close_price < trailing_stop_value:
            logging.info(f"Close: {close_price} ATH: {ath} Trailing_stop: {trailing_stop_value} Executed")
            exchange.place_order(symbol, 'sell', quantity, close_price)
            clear_open_position()
            break

        price_change_percent = ((close_price - buy_price) / buy_price) * 100
        usdt_change = (close_price - buy_price) * quantity

        if price_change_percent >= 0:
            variation_message = f"Gain de {price_change_percent:.2f}% ({usdt_change:.2f} USDT)"
        else:
            variation_message = f"Perte de {price_change_percent:.2f}% ({usdt_change:.2f} USDT)"

        logging.info(f"Close: {close_price} ATH: {ath} Trailing_stop: {trailing_stop_value} | {variation_message}")
        telegram_send(f"📈 Close: {close_price} ATH: {ath} Trailing_stop: {trailing_stop_value} | {variation_message}")
        
        time.sleep(1)

def is_symbol_supported(symbol, exchange_name):
    try:
        symbols = get_symbols(exchange_name)
        return symbol in symbols
    except Exception as e:
        logging.error(f"Erreur lors de la verification du symbole supporte: {e}")
        return False

def get_symbols(exchange_name):
    try:
        exchange = getattr(ccxt, exchange_name)()
        return exchange.load_markets().keys()
    except Exception as e:
        logging.error(f"Erreur lors de la recuperation des symboles pour {exchange_name}: {e}")
        return []

# Verifier si le fichier traded_pairs.json existe, sinon le creer
traded_pairs_file = 'traded_pairs.json'
if not os.path.exists(traded_pairs_file):
    with open(traded_pairs_file, 'w') as f:
        json.dump([], f)

# Charger les paires tradees
def load_traded_pairs(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

traded_pairs = load_traded_pairs(traded_pairs_file)

# Ensemble pour stocker les paires déjà tradées dans cette session
traded_pairs_session = set(traded_pairs)

# Choix de l'echange
exchange_name = "mexc"
def load_symbols(file_path):
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

symbols_file = 'symbols.json'
def save_symbols(file_path, symbols):
    with open(file_path, 'w') as f:
        json.dump(list(symbols), f)
    logging.info(f"Symboles sauvegardés dans {file_path}")

symbols = get_symbols(exchange_name)
save_symbols(symbols_file, symbols)
symbols = load_symbols(symbols_file)

if not symbols:
    symbols = get_symbols(exchange_name)
    save_symbols(symbols_file, symbols)
symbols = load_symbols(symbols_file)

if not symbols:
    symbols = get_symbols(exchange_name)
    save_symbols(symbols_file, symbols)

dry_run_mode = False
exchange = SpotExchange(exchange_name, **exchange_auth, dry_run=dry_run_mode)
logging.info(f"Symboles recuperes : {symbols}")

# Charger la position ouverte si elle existe
open_position = load_open_position()
if open_position:
    logging.info(f"Reprise de la position ouverte: {open_position['symbol']} à {open_position['buy_price']} USDT pour {open_position['quantity']} unités.")
    trailing_stop(open_position['symbol'], exchange, open_position['buy_price'], open_position['quantity'])

def save_traded_pairs(file_path, traded_pairs):
    with open(file_path, 'w') as f:
        json.dump(list(traded_pairs), f)
    logging.info(f"Paires tradees sauvegardees dans {file_path}")

# Fonction pour écouter les messages Telegram
def listen_telegram():
    url = f'https://api.telegram.org/bot{bot_token}/getUpdates'
    response = requests.get(url)
    if response.status_code == 200:
        messages = response.json().get('result', [])
        if messages:
            last_message = messages[-1]
            message_text = last_message['message']['text']
            return message_text
    return None

# Variables globales pour contrôler l'état du bot
is_paused = False
previous_state = None  # Variable pour suivre l'état précédent du bot

# Variable pour suivre l'état du clavier
keyboard_sent = False

# Variables pour suivre l'état des messages
last_change_pair_error_sent = False
last_pause_message_sent = False
last_resume_message_sent = False

# Fonction pour envoyer le clavier personnalisé
def send_telegram_keyboard():
    global keyboard_sent
    if not keyboard_sent:
        keyboard = {
            "keyboard": [
                ["/pause", "/resume", "/change_paire"]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
        send_text = f'https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={bot_chatID}&text=Commandes disponibles&reply_markup={json.dumps(keyboard)}'
        requests.get(send_text)
        keyboard_sent = True

# Appeler la fonction pour envoyer le clavier personnalisé au démarrage du bot
send_telegram_keyboard()

# Fonction pour traiter les commandes Telegram
def process_telegram_commands():
    global current_pair, can_send_bid_ask_error, is_paused, previous_state, keyboard_sent
    global last_change_pair_error_sent, last_pause_message_sent, last_resume_message_sent

    new_pair = listen_telegram()
    if new_pair:
        if new_pair.startswith("/change_paire"):
            parts = new_pair.split()
            if len(parts) == 2:
                _, new_pair_value = parts
                if not open_position:
                    if new_pair_value in traded_pairs_session:  # Vérification si la paire a déjà été tradée
                        logging.info(f"La paire {new_pair_value} a déjà été tradée. Ignorer cette paire.")
                        return  # Ignorer le message si la paire a déjà été tradée
                    current_pair = new_pair_value
                    logging.info(f"Paire changée à {current_pair} via Telegram.")
                    telegram_send(f"Paire changée à {current_pair} via Telegram.")
                    last_change_pair_error_sent = False  # Réinitialiser l'état du message d'erreur
                    
                    # Vérification si la paire est dans traded_pairs
                    if current_pair not in traded_pairs:
                        logging.warning(f"La paire {current_pair} n'est pas dans traded_pairs.")
                        telegram_send(f"Alerte : La paire {current_pair} n'est pas dans la liste des paires tradées.")
                else:
                    logging.info("Impossible de changer la paire, un trade est en cours.")
                    if not last_change_pair_error_sent:  # Vérifier si le message a déjà été envoyé
                        telegram_send("Impossible de changer la paire, un trade est en cours.")
                        last_change_pair_error_sent = True  # Marquer le message comme envoyé
            else:
                logging.error("Commande /change_paire mal formée. Format attendu: /change_paire BTC/USDT")
                if not last_change_pair_error_sent:  # Vérifier si le message a déjà été envoyé
                    telegram_send("Commande /change_paire mal formée. Format attendu: /change_paire BTC/USDT")
                    last_change_pair_error_sent = True  # Marquer le message comme envoyé
        elif new_pair == "/pause":
            if not is_paused:  # Vérifier si le bot n'est pas déjà en pause
                is_paused = True
                logging.info("Bot mis en pause via Telegram.")
                if not last_pause_message_sent:  # Vérifier si le message a déjà été envoyé
                    telegram_send("Bot mis en pause.")
                    last_pause_message_sent = True  # Marquer le message comme envoyé
        elif new_pair == "/resume":
            if is_paused:  # Vérifier si le bot est en pause
                is_paused = False
                logging.info("Bot relancé via Telegram.")
                if not last_resume_message_sent:  # Vérifier si le message a déjà été envoyé
                    telegram_send("Bot relancé.")
                    last_resume_message_sent = True  # Marquer le message comme envoyé
                keyboard_sent = False  # Réinitialiser l'état du clavier
        # Envoyer le clavier personnalisé après avoir traité une commande
        send_telegram_keyboard()

# Ajouter une variable pour contrôler l'envoi des messages d'erreur
can_send_bid_ask_error = True

# Boucle principale optimisée
while True:
    try:
        # Traiter les commandes Telegram
        process_telegram_commands()

        # Vérifier si le bot est en pause
        if is_paused:
            if previous_state != "paused":
                logging.info("Bot en pause. En attente de la commande /resume...")
                previous_state = "paused"
            time.sleep(10)
            continue
        else:
            if previous_state == "paused":
                previous_state = "running"

        # Attendre qu'une paire soit définie si aucune paire n'est enregistrée
        if not current_pair:
            logging.info("Aucune paire définie. En attente d'une paire via Telegram...")
            telegram_send("Aucune paire définie. Veuillez envoyer une paire via la commande /change_paire.")
            time.sleep(10)
            continue

        if current_pair in symbols:
            if current_pair in traded_pairs_session:
                logging.info(f"{str(datetime.now()).split('.')[0]} | {current_pair} a déjà été tradée. Ignorer cette paire.")
                # Effacer la paire actuelle et attendre une nouvelle commande
                current_pair = ''
                logging.info("Paire actuelle effacée. En attente d'une nouvelle paire via Telegram...")
                telegram_send("Paire actuelle effacée. Veuillez envoyer une nouvelle paire via la commande /change_paire.")
                time.sleep(10)  # Réduire le temps d'attente à 10 secondes
                continue

            logging.info(f"{str(datetime.now()).split('.')[0]} | Tentative de sniping sur {current_pair}")
            second_bid, second_ask = get_second_bid_ask(exchange, current_pair)
            if second_bid is None or second_ask is None:
                if can_send_bid_ask_error:
                    error_message = f"{str(datetime.now()).split('.')[0]} | Impossible d'obtenir le deuxième bid/ask pour {current_pair}."
                    logging.info(error_message)
                    #telegram_send(error_message)
                    can_send_bid_ask_error = False  # Désactiver l'envoi jusqu'à la prochaine commande
                time.sleep(10)  # Réduire le temps d'attente à 10 secondes
                continue

            usdt_amount = 12
            usdt_balance = exchange.get_balance()
            
            if usdt_amount > usdt_balance:
                logging.warning(f"Le montant d'achat ({usdt_amount} USDT) est superieur au solde disponible ({usdt_balance} USDT). Ajustement du montant d'achat.")
                usdt_amount = usdt_balance * 0.95

            quantity = usdt_amount / second_ask
            quantity = float(exchange.convert_amount_to_precision(current_pair, quantity))

            fee_percentage = 0.001
            adjusted_quantity = quantity * (1 - fee_percentage)
            adjusted_cost = adjusted_quantity * second_ask

            if adjusted_cost > usdt_balance:
                logging.error(f"Solde insuffisant pour acheter {adjusted_quantity} {current_pair} au prix actuel de {second_ask}. Coût ajuste : {adjusted_cost} USDT. Solde disponible : {usdt_balance} USDT.")
                telegram_send(f"Solde insuffisant pour acheter {adjusted_quantity} {current_pair} au prix actuel de {second_ask}. Coût ajuste : {adjusted_cost} USDT. Solde disponible : {usdt_balance} USDT.")
                continue

            exchange.reload_markets()

            try:
                if is_symbol_supported(current_pair, exchange_name):
                    order_response = exchange.place_order(current_pair, "buy", adjusted_quantity, second_ask)
                    purchase_price = second_ask
                    logging.info(f"{str(datetime.now()).split('.')[0]} | Buy {current_pair} Order success at price: {purchase_price} USDT!")
                    telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ Buy {current_pair} Order success at price: {purchase_price} USDT!")

                    save_open_position(current_pair, purchase_price, adjusted_quantity)

                    logging.info(f"{str(datetime.now()).split('.')[0]} | Waiting for sell...")
                    telegram_send(f"⌛ Waiting for sell...")

                    trailing_stop(current_pair, exchange, purchase_price, adjusted_quantity)

                    sell_price = second_bid
                    profit_percentage = ((sell_price - purchase_price) / purchase_price) * 100 if purchase_price else 0
                    profit_usdt = (sell_price - purchase_price) * adjusted_quantity

                    exchange.place_order(current_pair, "sell", adjusted_quantity, sell_price)
                    logging.info(f"{str(datetime.now()).split('.')[0]} | Sell {current_pair} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}% ({profit_usdt:.2f} USDT)")
                    telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ 💯 Sell {current_pair} Order success at price: {sell_price} USDT! Profit: {profit_percentage:.2f}% ({profit_usdt:.2f} USDT)")

                    clear_open_position()

                    traded_pairs_session.add(current_pair)
                    traded_pairs.append(current_pair)
                    save_traded_pairs(traded_pairs_file, traded_pairs)
                else:
                    logging.error(f"Le symbole {current_pair} n'est pas supporte par l'API de l'echange {exchange_name}.")
                    telegram_send(f"Le symbole {current_pair} n'est pas supporte par l'API de l'echange {exchange_name}.")
            except ccxt.ExchangeError as e:
                logging.error(f"Erreur d'echange lors du placement de l'ordre marche pour {current_pair}: {e}")
                telegram_send(f"Erreur d'echange lors du placement de l'ordre marche pour {current_pair}: {e}")
            except Exception as e:
                logging.error(f"Erreur inattendue lors de la transaction pour {current_pair}: {e}")
                telegram_send(f"Erreur inattendue lors de la transaction pour {current_pair}: {e}")
        else:
            logging.info(f"{str(datetime.now()).split('.')[0]} | {current_pair} n'est pas dans la liste des symboles ou a déjà été tradée.")
            logging.info(f"{str(datetime.now()).split('.')[0]} | Attente de 10 secondes pour que la paire soit listée.")
            time.sleep(10)  # Réduire le temps d'attente à 10 secondes
    except Exception as e:
        logging.error(f"Erreur dans la boucle principale: {e}")
        time.sleep(5)
