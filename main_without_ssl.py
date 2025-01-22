from tradelocker import TLAPI
import threading
from fastapi import FastAPI, Request
import uvicorn
import argparse
from libs import AsciiAlerts
from libs.URLgenerator import *

app = FastAPI()
lock = threading.Lock()

def parse_args():
    parser = argparse.ArgumentParser(description="Add variables when starting")
    parser.add_argument('--username', type=str, required=True, help='username/email')
    parser.add_argument('--password', type=str, required=True, help='password')
    parser.add_argument('--server', type=str, required=True, help='server')
    parser.add_argument('--env', type=str, required=True, choices=['live', 'demo'], help='live/demo')
    parser.add_argument('--url', type=str, default='/strategy', help='Optional URL, default is /strategy')
    parser.add_argument('--acc_num', type=str, default='0', help='Optional account number')
    parser.add_argument('--acc_id', type=str, default='0', help='Optional account ID')
    parser.add_argument('--port', type=int, default=443, help='Port to run the application')
    return parser.parse_args()

def create_tl_instance(env, username, password, server, acc_num, acc_id):
    if acc_num and acc_id:
        raise ValueError("Please provide only the account number or ID (starting from 1).")
    if acc_num:
        return TLAPI(environment=env, username=username, password=password, server=server, acc_num=acc_num)
    if acc_id:
        return TLAPI(environment=env, username=username, password=password, server=server, account_id=acc_id)
    return TLAPI(environment=env, username=username, password=password, server=server)

def close_positions(tl, symbol_name):
    instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
    closed = False
    while not closed:
        positions = tl.get_all_positions()
        relevant_positions = positions[positions['tradableInstrumentId'] == instrument_id]
        for _, position in relevant_positions.iterrows():
            tl.close_all_positions(instrument_id)
            print(f"Closing: {symbol_name}")
        closed = relevant_positions.empty

def place_order(tl, instrument_id, lot, side, stoploss, takeprofit):
    order_id = ""
    while not order_id:
        order_id = tl.create_order(
            instrument_id,
            quantity=lot,
            side=side,
            type_="market",
            stop_loss=stoploss,
            take_profit=takeprofit,
            stop_loss_type="offset",
            take_profit_type="offset"
        )
        if not order_id:
            print(AsciiAlerts.RED + f"{side.capitalize()} order was not successful, trying again...")
            AsciiAlerts.resetStyle()
        else:
            print(AsciiAlerts.GREEN + f"Order placed successfully, order ID: {order_id}")
            AsciiAlerts.resetStyle()

def handle_position_normal(tl, payload_list, lock):
    with lock:
        symbol_name = payload_list[0]
        direction = payload_list[1]
        mainLot = payload_list[2]
        takeprofit = int(payload_list[3])
        stoploss = int(payload_list[4])
        isInvert = payload_list[6]
        balance = tl.get_account_state().get("projectedBalance")

        minilot, per = map(float, mainLot.split('/'))
        lot = round((balance / per) * minilot, 2)

        print("Normal: Locked")
        if payload_list[5] == "close":
            close_positions(tl, symbol_name)

        if payload_list[5] == "open":
            close_positions(tl, symbol_name)
            instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)

            if isInvert == "NonInvert":
                order_direction = direction
            elif isInvert == "Invert":
                order_direction = 'sell' if direction == 'buy' else 'buy'
            else:
                raise ValueError("Invalid value for isInvert. Expected 'NonInvert' or 'Invert'.")

            place_order(tl, instrument_id, lot, order_direction, stoploss, takeprofit)


        print("Normal: Unlocked")

def main():
    args = parse_args()
    if args.env == "demo":
        env_url = "https://demo.tradelocker.com"
    elif args.env == "live":
        env_url = "https://live.tradelocker.com"
    else:
        raise ValueError("Invalid environment specified. Use 'demo' or 'live'.")

    if args.url == "generate":
        print(AsciiAlerts.RED + AsciiAlerts.ascii_art_url + AsciiAlerts.RESET)
        args.url = generate_random_url()
        print(args.url)

    print(AsciiAlerts.GREEN + AsciiAlerts.ascii_art_hello + AsciiAlerts.RESET)

    tl = create_tl_instance(env_url, args.username, args.password, args.server, int(args.acc_num), int(args.acc_id))

    @app.post(args.url)
    async def process_webhook(request: Request):
        payload_bytes = await request.body()
        payload_list = payload_bytes.decode().splitlines()
        normal_thread = threading.Thread(target=handle_position_normal, args=(tl, payload_list, lock))
        normal_thread.start()

    uvicorn.run(app, host="0.0.0.0", port=args.port)

if __name__ == "__main__":
    main()
