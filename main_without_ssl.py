from tradelocker import TLAPI
import threading
from fastapi import FastAPI, Request
import uvicorn
import argparse
from libs import AsciiAlerts
from libs.URLgenerator import *

app = FastAPI()
lock = threading.Lock()


parser = argparse.ArgumentParser(description="Add variables when starting")
parser.add_argument('--username', type=str, required=True, help='username/email')
parser.add_argument('--password', type=str, required=True, help='password')
parser.add_argument('--server', type=str, required=True, help='server')
parser.add_argument('--env', type=str, required=True, help='live/demo')
parser.add_argument('--url', type=str, default='/strategy', help='Optional URL, default is /strategy')
parser.add_argument('--acc_num', type=str, default='0', help='Optional account number')
parser.add_argument('--acc_id', type=str, default='0', help='Optional account number')
args = parser.parse_args()

username = args.username
password = args.password
server = args.server
enviroment = args.env
acc_num = int(args.acc_num)
acc_id = int(args.acc_id)
url = args.url

if enviroment == "demo":
    enviroment = "https://demo.tradelocker.com"
elif enviroment == "live":
    enviroment = "https://live.tradelocker.com"


if url == "generate":
    url = generate_random_url()
    print(AsciiAlerts.RED + AsciiAlerts.ascii_art_url + AsciiAlerts.RESET)
    print(url)


print(AsciiAlerts.GREEN + AsciiAlerts.ascii_art_hello + AsciiAlerts.RESET)

if acc_num != 0 and acc_id != 0:
    raise ValueError("Please provide only the account number or ID (starting from 1).")

if acc_num != 0:
    tl = TLAPI(environment=enviroment, username=username, password=password,
           server=server, acc_num=acc_num)

elif acc_id != 0:
    tl = TLAPI(environment=enviroment, username=username, password=password,
           server=server, account_id=acc_id)
else:
    tl = TLAPI(environment=enviroment, username=username, password=password,
               server=server)

#Close until closed
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

#Execute webhook
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
                    order_id = tl.create_order(instrument_id, quantity=lot, side="buy", type_="market", stop_loss=stoploss,
                                               take_profit=takeprofit, stop_loss_type="offset", take_profit_type = "offset")

                    if not order_id:
                        print(AsciiAlerts.GREEN + "Order was not successful, trying again...")
                        AsciiAlerts.resetStyle()
                    else:
                        print(AsciiAlerts.GREEN + "Order placed successfully, order ID:", order_id)
                        AsciiAlerts.resetStyle()

            if direction == 'sell':
                order_id = ""
                instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
                while not order_id:
                    order_id = tl.create_order(instrument_id, quantity=lot, side="sell", type_="market", take_profit=takeprofit,
                                                   stop_loss=stoploss, stop_loss_type="offset", take_profit_type = "offset")

                    if not order_id:
                        print(AsciiAlerts.RED + "Order was not successful, trying again..." )
                        AsciiAlerts.resetStyle()
                    else:
                        print(AsciiAlerts.GREEN + "Order placed successfully, order ID:", order_id )
                        AsciiAlerts.resetStyle()

        print("Normal: Unlocked")

@app.post(url)
async def process_webhook(request: Request):
    payload_bytes = await request.body()
    payload_str = payload_bytes.decode()
    payload_list = payload_str.splitlines()

    normal_thread = threading.Thread(target=handle_position_normal, args=(payload_list,))
    normal_thread.start()

uvicorn.run(app, host="0.0.0.0", port=443)
