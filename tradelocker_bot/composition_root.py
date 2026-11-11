"""The composition root: reads the start arguments, logs in, wires the
adapters to the use case and serves the webhook (ADR 0010).

The only module that knows every layer. Nothing inside the package imports
it; ``main_without_ssl.py``, the container's command, only calls ``main``.
"""

import argparse
import threading

import uvicorn

from tradelocker_bot.adapters import ascii_alerts
from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.adapters.signal_handler import SignalHandler
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker, log_in
from tradelocker_bot.adapters.webhook import create_app
from tradelocker_bot.adapters.webhook_path import random_webhook_path
from tradelocker_bot.application.execute_signal import ExecuteSignal


def webhook_url(value):
    """The ``--url`` value: ``generate`` or a path that starts with ``/``.

    A route without the leading slash matches no request, so the bot would
    look up while every alert got a 404 (ADR 0014). It stops instead, like any
    invalid argument, before the banners and the login. The message leaves the
    value out: it is the operator's secret path, give or take a slash.
    """
    # ArgumentTypeError rather than ValueError: for a ValueError argparse
    # prints the rejected value, and stderr goes to the container's log.
    if value != "generate" and not value.startswith("/"):
        raise argparse.ArgumentTypeError("must start with / or be generate")
    return value


def parse_args():
    parser = argparse.ArgumentParser(description="Add variables when starting")
    parser.add_argument('--username', type=str, required=True, help='username/email')
    parser.add_argument('--password', type=str, required=True, help='password')
    parser.add_argument('--server', type=str, required=True, help='server')
    parser.add_argument('--env', type=str, required=True, choices=['live', 'demo'], help='live/demo')
    parser.add_argument('--url', type=webhook_url, default='/strategy', help='Optional URL, default is /strategy')
    parser.add_argument('--acc_num', type=str, default='0', help='Optional account number')
    parser.add_argument('--acc_id', type=str, default='0', help='Optional account ID')
    parser.add_argument('--port', type=int, default=443, help='Port to run the application')
    return parser.parse_args()


def build_signal_handler(client, lock) -> SignalHandler:
    """The handler for every webhook request, over one logged-in client.

    Built once rather than per request, as legacy did: the console, the
    broker adapter and the use case hold nothing but their collaborators, so
    sharing them changes no call and no line.
    """
    console = PrintingConsole()
    return SignalHandler(ExecuteSignal(TradeLockerBroker(client), console), console, lock)


def main():
    args = parse_args()

    if args.url == "generate":
        print(ascii_alerts.RED + ascii_alerts.ascii_art_url + ascii_alerts.RESET)
        args.url = random_webhook_path()
        print(args.url)

    print(ascii_alerts.GREEN + ascii_alerts.ascii_art_hello + ascii_alerts.RESET)

    client = log_in(args.env, args.username, args.password, args.server, int(args.acc_num), int(args.acc_id))

    # One lock for the whole process: every request's signal runs inside it,
    # so two alerts never interleave between closing and ordering.
    app = create_app(args.url, build_signal_handler(client, threading.Lock()).handle)

    uvicorn.run(app, host="0.0.0.0", port=args.port)
