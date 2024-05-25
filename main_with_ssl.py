from tradelocker import TLAPI
import time, random
import ssl
from fastapi import FastAPI, Request
import time
import uvicorn
import threading

order_id = None

# Initialize the API client with the information you use to login
tl = TLAPI(environment = "https://demo.tradelocker.com", username = "wiktorjn@gmail.com", password = ".74nCqZz", server = "24K-DEMO")

app = FastAPI()

lock = threading.Lock()

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
        closed = not((positions['tradableInstrumentId'] == instrument_id).any())

def handle_position_normal(payload_list):
    with lock:
        symbol_name = payload_list[0]
        direction = payload_list[1]
        lot = float(payload_list[2])
        candle_close_price = payload_list[3]
        stoploss = float(payload_list[4])

        print("Normal: Locked")
        if payload_list[5] == "Close":
            close(symbol_name)


        if payload_list[5] == "Open":
            close(symbol_name)
            if direction == 'buy':
                order_id = ""
                instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
                while not order_id:
                    order_id = tl.create_order(instrument_id, quantity=lot, side="buy", type_="market", sl=stoploss,
                                               sl_type="offset")
                    if not order_id:
                        print("Order was not successful, trying again...")
                    else:
                        print("Order placed successfully, order ID:", order_id)

            if direction == 'sell':
                order_id = ""
                instrument_id = tl.get_instrument_id_from_symbol_name(symbol_name)
                while not order_id:
                    order_id = tl.create_order(instrument_id, quantity=lot, side="sell", type_="market", sl=stoploss,
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




ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile="certificate.crt", keyfile="private.key")

uvicorn.run(app, host="0.0.0.0", port=21933, ssl_certfile="certificate.crt", ssl_keyfile="private.key")
