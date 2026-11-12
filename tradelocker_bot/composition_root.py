"""The composition root: reads the start settings, logs in, wires the
adapters to the use case and serves the webhook (ADR 0010).

The only module that knows every layer. Nothing inside the package imports
it; ``main_without_ssl.py``, the container's command, only calls ``main``.
"""

import argparse
import sys
import threading
from os import environ

import uvicorn

from tradelocker_bot.adapters import ascii_alerts
from tradelocker_bot.adapters.console import PrintingConsole
from tradelocker_bot.adapters.signal_handler import SignalHandler
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker, log_in
from tradelocker_bot.adapters.server_log import server_log_config
from tradelocker_bot.adapters.webhook import create_app
from tradelocker_bot.adapters.webhook_path import random_webhook_path
from tradelocker_bot.application.execute_signal import ExecuteSignal


def webhook_url(value):
    """The ``--url`` value: ``generate`` or a path that starts with ``/`` and
    has no ``{`` or ``}``.

    A route without the leading slash matches no request, so the bot would
    look up while every alert got a 404 (ADR 0014). A route with ``{name}`` is
    a pattern that also matches paths the operator never set (ADR 0015). Either
    way the bot stops, like any invalid argument, before the banners and the
    login. The message leaves the value out: it is the operator's secret path,
    or close to it.
    """
    # ArgumentTypeError rather than ValueError: for a ValueError argparse
    # prints the rejected value, and stderr goes to the container's log.
    if value != "generate" and not value.startswith("/"):
        raise argparse.ArgumentTypeError("must start with / or be generate")
    # Any brace rather than only the `{name}` forms Starlette reads as a
    # parameter: mirroring its pattern syntax here would let a future version
    # with a wider syntax turn a path that passed this check into a pattern.
    if "{" in value or "}" in value:
        raise argparse.ArgumentTypeError("must not contain { or }")
    return value


def not_empty(value):
    """A username or server: an empty one cannot log in, so it stops the bot
    like a missing one rather than reaching the login."""
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def refuse_password(_value):
    """``--password``, refused without its value: the host's process list
    shows the command line to every user (ADR 0018). Registered rather than
    left unknown, because argparse prints an unknown argument in full."""
    raise argparse.ArgumentTypeError("set the password environment variable instead")


# The options the image sets through its environment variables, under the
# same names: the frozen contract's variables, less the password.
FROM_ENVIRONMENT = ("username", "server", "env", "url", "acc_num", "acc_id")

# They exclude each other, so one given on the command line stands for both.
ACCOUNT_SELECTORS = {"acc_num", "acc_id"}


def environment_args(env, argv):
    """Each variable that is set and whose option ``argv`` does not give, as
    that option.

    One parser for both sources rather than a second set of checks: a value
    from either gets the same validation and the same message. A variable
    the command line replaces is left out rather than overridden, so a bad
    value there cannot stop the bot; with ``--help`` every variable is, so
    a bad one cannot hide the help. The ``=`` form keeps a value that starts
    with ``-`` from reading as an option.
    """
    given = {arg[2:].split("=", 1)[0] for arg in argv if arg.startswith("--")}
    if "help" in given or "-h" in argv:
        return []
    if given & ACCOUNT_SELECTORS:
        given |= ACCOUNT_SELECTORS
    return [f"--{name}={env[name]}" for name in FROM_ENVIRONMENT if name in env and name not in given]


def parse_args(argv=None, env=None):
    """The start settings: the options in ``argv``, those not given there
    from ``env``, and the password only from ``env``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    env = environ if env is None else env
    # No abbreviations, and no unknown argument printed: argparse would print
    # an ambiguous `--p=...` or a misspelt `--passwd ...` in full, password
    # included, to the container's log.
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Each option but --port can instead be set in the environment variable of the same name; "
        "an option given here replaces its variable, and --acc_num or --acc_id here replaces both. "
        "The password is read only from the password environment variable.",
    )
    parser.add_argument('--username', type=not_empty, required=True, help='username/email')
    parser.add_argument('--password', type=refuse_password, help=argparse.SUPPRESS)
    parser.add_argument('--server', type=not_empty, required=True, help='server')
    parser.add_argument('--env', type=str, required=True, choices=['live', 'demo'], help='live/demo')
    parser.add_argument('--url', type=webhook_url, default='/strategy', help='Optional URL, default is /strategy')
    parser.add_argument('--acc_num', type=str, default='0', help='Optional account number')
    parser.add_argument('--acc_id', type=str, default='0', help='Optional account ID')
    parser.add_argument('--port', type=int, default=443, help='Port to run the application')
    args, unknown = parser.parse_known_args(environment_args(env, argv) + argv)
    if unknown:
        parser.error("unrecognized arguments, not shown: one may be the password")
    args.password = env.get("password", "")
    if not args.password:
        parser.error("the password environment variable is not set or is empty")
    return args


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

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_config=server_log_config())
