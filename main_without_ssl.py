from tradelocker import TLAPI
import threading
from fastapi import FastAPI, Request
import uvicorn
import argparse

app = FastAPI()
lock = threading.Lock()

parser = argparse.ArgumentParser(description="Add variables when starting")
parser.add_argument('--username', type=str, required=True, help='username/email')
parser.add_argument('--password', type=str, required=True, help='password')
parser.add_argument('--server', type=str, required=True, help='server')
parser.add_argument('--env', type=str, required=True, help='live/demo')
args = parser.parse_args()

username = args.username
password = args.password
server = args.server
enviroment = args.env

if enviroment == "demo":
    enviroment = "https://demo.tradelocker.com"
elif enviroment == "live":
    enviroment = "https://live.tradelocker.com"


tl = TLAPI(environment=enviroment, username=username, password=password,
           server=server)
invert = False



def accept_user_input():
    global invert
    while True:
        user_input = input()
        print(f"Recived: {user_input}")
        if user_input == 'invert':
            invert = not invert
            print("inverted: ", invert)


def close(symbol_name):
    closed = False
    positions = tl.get_all_positions()
    instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
    while not closed:
        for i in range(len(positions)):
            id = positions.at[i, 'id']
            tradableInstrumentId = positions.at[i, 'tradableInstrumentId']
            print(id)
            print(tradableInstrumentId)
            if tradableInstrumentId == instrument_id:
                tl.close_all_positions(instrument_id)
                print("Closing: ", symbol_name)
        positions = tl.get_all_positions()
        closed = not ((positions['tradableInstrumentId'] == instrument_id).any())


def handle_position_normal(payload_list):
    global invert
    with lock:
        symbol_name = payload_list[0]
        direction = payload_list[1]
        lot = float(payload_list[2])
        takeprofit = int(payload_list[3])
        stoploss = int(payload_list[4])

        print("Normal: Locked")
        if payload_list[5] == "Close":
            close(symbol_name)


        if payload_list[5] == "Open":
            close(symbol_name)
            if direction == 'buy':
                order_id = ""
                instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
                while not order_id:
                    if not invert:
                        order_id = tl.create_order(instrument_id, quantity=lot, side="buy", type_="market", sl=stoploss, tp = takeprofit,
                                               sl_type="offset")
                    else:
                        order_id = tl.create_order(instrument_id, quantity=lot, side="sell", type_="market", sl=stoploss, tp = takeprofit,
                                               sl_type="offset")
                    if not order_id:
                        print("Order was not successful, trying again...")
                    else:
                        print("Order placed successfully, order ID:", order_id)

            if direction == 'sell':
                order_id = ""
                instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
                while not order_id:
                    if not invert:
                        order_id = tl.create_order(instrument_id, quantity=lot, side="sell", type_="market", tp = takeprofit,
                                                   sl=stoploss,
                                                   sl_type="offset")
                    else:
                        order_id = tl.create_order(instrument_id, quantity=lot, side="buy", type_="market", tp = takeprofit,
                                                   sl=stoploss,
                                                   sl_type="offset")
                    if not order_id:
                        print("Order was not successful, trying again...")
                    else:
                        print("Order placed successfully, order ID:", order_id)


        print("Normal: Unlocked")


@app.post("/strategynormal")
async def process_webhook(request: Request):
    payload_bytes = await request.body()
    payload_str = payload_bytes.decode()
    payload_list = payload_str.splitlines()

    normal_thread = threading.Thread(target=handle_position_normal, args=(payload_list,))
    normal_thread.start()


thread_user_input = threading.Thread(target=accept_user_input)
thread_user_input.start()

# Uruchamianie serwera bez SSL
uvicorn.run(app, host="0.0.0.0", port=21933)
