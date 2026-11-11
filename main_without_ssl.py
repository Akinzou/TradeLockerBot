from tradelocker import TLAPI
import threading
from fastapi import FastAPI, Request
import uvicorn
import argparse
from libs import AsciiAlerts
from libs.URLgenerator import *
from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker
from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.application.ports import BrokerFailure
from tradelocker_bot.domain.result import Err
from tradelocker_bot.domain.signal import parse_signal

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

def handle_position_normal(tl, payload_list, lock):
    console = PrintingConsole()
    signal = parse_signal(payload_list)
    if isinstance(signal, Err):
        # Refused before the lock, so an invalid alert neither waits behind
        # nor delays a valid one, and before any broker call; the thread ends
        # without an exception, because the operator line says it all (ADR 0008).
        console.rejected(signal.error)
        return
    with lock:
        result = ExecuteSignal(TradeLockerBroker(tl), console).execute(signal.value)
        if isinstance(result, Err):
            if isinstance(result.error, BrokerFailure):
                # The client's own exception object, raised inside the lock: the
                # webhook thread fails with the same type, message and attributes
                # as before the Result (ADR 0006). Reporting broker failures
                # instead is a behaviour change of its own (roadmap step 6).
                raise result.error.cause
            # The broker answered and ruled the signal out before any close
            # request: reported like a payload rejection, without an
            # exception (ADR 0009).
            console.rejected(result.error)

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
