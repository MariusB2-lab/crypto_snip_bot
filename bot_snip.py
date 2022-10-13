
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',level=logging.INFO)

import ccxt
import pandas as pd
import requests
import time
from datetime import datetime

##telegram 
import requests
import threading


class SpotKucoin():
    def __init__(self, apiKey=None, secret=None, password=None):
        kucoinAuthObject = {
            "apiKey": apiKey,
            "secret": secret,
            "password": password,
        }
        if kucoinAuthObject['secret'] == None:
            self._auth = False
            self._session = ccxt.kucoin()
        else:
            self._auth = True
            self._session = ccxt.kucoin(kucoinAuthObject)
        self.market = self._session.load_markets()

    def reload_markets(self):
        self.market = self._session.load_markets()

    #Cette fonction permet d'obtenir le prix actuel d'une crypto sur Kucoin       
    def get_price(self,pair):
        return self._session.fetch_ticker(pair)['close']
 
    def authentication_required(fn):
        """Annotation for methods that require auth."""
        def wrapped(self, *args, **kwargs):
            if not self._auth:
                print("You must be authenticated to use this method", fn)
                telegram_send(f"You must be authenticated to use this method")   
                exit()
            else:
                return fn(self, *args, **kwargs)
        return wrapped

    def convert_amount_to_precision(self, symbol, amount):
        return self._session.amount_to_precision(symbol, amount)

    def convert_price_to_precision(self, symbol, price):
        return self._session.price_to_precision(symbol, price)

    #Cette fonction permet de créer un ordre market
    @authentication_required
    def place_market_order(self, symbol, side, amount):
        try:
            return self._session.createOrder(
                symbol, 
                'market', 
                side, 
                self.convert_amount_to_precision(symbol, amount),
                None
            )
        except Exception as err:
            raise err

    #Cette fonction permet de créer un ordre limit
    @authentication_required
    def place_limit_order(self, symbol, side, amount, price):
        try:
            return self._session.createOrder(
                symbol, 
                'limit', 
                side, 
                self.convert_amount_to_precision(symbol, amount), 
                self.convert_price_to_precision(symbol, price)
                )
        except Exception as err:
            raise err

#Fonction telegram       
def telegram_send( message):
                    bot_token = ""
                    bot_chatID = ""
                    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + bot_chatID + '&parse_mode=Markdown&text=' + message
                    threading.Thread(target=requests.get, args=(send_text,)).start()


#Cette fonction permet d'obtenir le prix actuel d'une crypto sur Kucoin
def getCurrentPrice(perpSymbol) :
    global kucoin2
    try:
        ticker = kucoin2.fetchTicker(perpSymbol)
    except BaseException as err:
        print("An error occured", err)
    return float(ticker["ask"])

kucoin2 = ccxt.kucoin({
            "apiKey": "",
            "secret": "",
            "password": ""
            })

amount = 12

kucoin = SpotKucoin(
    apiKey="",
    secret="",
    password=""
)

#Exemple Trailing Stop 1%
def trailing_stop(symbol):

    #Initialisation
    ath = kucoin.get_price(symbol)
    trailing_stop = ath * 0.99

    while 1 : 
        close_price = kucoin.get_price(symbol)
        #Increase the trailing stop
        if(close_price > ath ):
            ath = close_price
            trailing_stop = ath * 0.99
        #Sell
        if(close_price < trailing_stop):
            print(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop} Executed")            
            break
        
        print(f"Close : {close_price} ATH : {ath} Trailing_stop : {trailing_stop} ")                         
        time.sleep(1)
                    

nbDePairesExecutionsPrecedentes=0
telegram_send(f"✳️ Bot de sniping lancé avec {amount} USDT, en attente dachat...")
print(f"✳️ Bot de sniping lancé avec {amount} USDT, en attente dachat...")

while True :

    try :
        
        #Récupération des données de kucoin
        liste_pairs = requests.get('https://openapi-v2.kucoin.com/api/v1/symbols').json()
        dataResponse = liste_pairs['data']
        df = pd.DataFrame(dataResponse, columns = ['symbol','enableTrading'])
        #df.drop(df.loc[df['enableTrading']==False].index, inplace=True)
        df = df[df.symbol.str.contains("-USDT")]

        #On créer une liste avec le nom de paires
        perpListBase = []
        for index, row in df.iterrows():
            perpListBase.append(row['symbol'])
             
            for pair in perpListBase :  
                pairs='KLCS-USDT'

                symbol = pairs
                amount = 12
                if symbol != '' :
                    symbol = symbol.replace("-", "/" )
                    print(f"{str(datetime.now()).split('.')[0]} | Tentative de snipping sur {symbol} avec {amount} USDT")
                    telegram_send(f"{str(datetime.now()).split('.')[0]} | Tentative de snipping sur {symbol} avec {amount} USDT")
                    amount = amount/getCurrentPrice(symbol)*1.30 #0.95
                    seconds_before_sell = 10

                    while True:
                        try:
                            kucoin.reload_markets()
                            symbol = symbol.replace("-", "/" )
                            kucoin.place_market_order(symbol, "buy", amount)
                            print(f"{str(datetime.now()).split('.')[0]} | Buy {symbol} Order success!")
                            telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ Buy {symbol} Order success!")
                            print(f"{str(datetime.now()).split('.')[0]} | Waiting for sell...")
                            telegram_send(f"⌛ Waiting for sell...")

                            #time.sleep(seconds_before_sell)
                            #achat avec 1% TL
                            trailing_stop(symbol)

                            symbol = symbol.replace("-", "/" )
                            kucoin.place_market_order(symbol, "sell", amount)
                            print(f"{str(datetime.now()).split('.')[0]} | Sell {symbol} Order success!")
                            telegram_send(f"{str(datetime.now()).split('.')[0]} |✅ 💯 Sell {symbol} Order success!")

                            break
                        except Exception as err:
                            print(err)
                            telegram_send(f"{err}")
                            if str(err) == "kucoin does not have market symbol " + symbol:
                                time.sleep(0.1)
                            else :
                                print(err)
                            pass
                    print(f"{str(datetime.now()).split('.')[0]} | Sniping réalisé sur {symbol}")
                    telegram_send(f"Sniping réalisé sur {symbol}")
                    del symbol
                    break
                break
            break
        break
    except Exception as err:
        print(f"{err}")
        if str(err) == "kucoin does not have market symbol " + symbol:
            time.sleep(0.1)
        pass
 
