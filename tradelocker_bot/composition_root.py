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
from tradelocker_bot.adapters.password_file import read_password_file
from tradelocker_bot.adapters.signal_handler import SignalHandler
from tradelocker_bot.adapters.system_clock import SystemClock
from tradelocker_bot.adapters.tradelocker_broker import TradeLockerBroker, log_in
from tradelocker_bot.adapters.server_log import server_log_config
from tradelocker_bot.adapters.webhook import create_app
from tradelocker_bot.adapters.webhook_path import random_webhook_path
from tradelocker_bot.application.execute_signal import ExecuteSignal
from tradelocker_bot.domain.result import Err, Ok, Result


def webhook_url(value):
    """The ``--url`` value: ``generate`` or a path that starts with ``/`` and
    has no ``{``, ``}``, ``?``, ``#`` or ``%``.

    A route without the leading slash matches no request, so the bot would
    look up while every alert got a 404 (ADR 0014). A route with ``{name}`` is
    a pattern that also matches paths the operator never set (ADR 0015). A
    sender reads ``?``, ``#`` and ``%`` as URL syntax, so a route with one is
    reached only percent-encoded (ADR 0020). In each case the bot stops, like
    any invalid argument, before the banners and the login. The message leaves
    the value out: it is the operator's secret path, or close to it.
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
    # Every `%`, not only one before two hex digits: `%zz` reaches the route
    # today, but a rule that needs the decoding rules to apply would be one an
    # operator cannot check by eye (ADR 0020).
    if any(character in value for character in "?#%"):
        raise argparse.ArgumentTypeError("must not contain ?, # or %")
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
    raise argparse.ArgumentTypeError("set password_file or the password environment variable instead")


def password_from(env) -> Result[str, str]:
    """The password from exactly one of ``password_file`` and ``password``,
    an empty one counting as not set (ADR 0024)."""
    path, variable = env.get("password_file", ""), env.get("password", "")
    # Neither wins: a password variable left in an env file would otherwise
    # decide, unseen, which password logs in.
    if path and variable:
        return Err("set either password_file or the password environment variable, not both")
    if path:
        return read_password_file(path)
    if variable:
        return Ok(variable)
    return Err("no password: set password_file to a file that holds it, or the password environment variable")


# The options the image sets through its environment variables, under the
# same names: the frozen contract's variables, less the password and its file.
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
    from ``env``, and the password only from ``env``, from its variable or
    the file ``password_file`` names."""
    argv = list(sys.argv[1:] if argv is None else argv)
    env = environ if env is None else env
    # No abbreviations, and no unknown argument printed: argparse would print
    # an ambiguous `--p=...` or a misspelt `--passwd ...` in full, password
    # included, to the container's log.
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Each option but --port can instead be set in the environment variable of the same name; "
        "an option given here replaces its variable, and --acc_num or --acc_id here replaces both. "
        "The password is read only from the environment: from the file password_file names, "
        "or from the password variable.",
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
    password = password_from(env)
    if isinstance(password, Err):
        parser.error(password.error)
    args.password = password.value
    return args


def build_signal_handler(client, lock, clock) -> SignalHandler:
    """The handler for every webhook request, over one logged-in client.

    Built once rather than per request, as legacy did: the console, the
    broker adapter and the use case hold nothing but their collaborators, so
    sharing them changes no call and no line. The clock is an argument
    without a default, so a test cannot get the real one, and its pauses, by
    leaving it out.
    """
    console = PrintingConsole()
    return SignalHandler(ExecuteSignal(TradeLockerBroker(client), console, clock), console, lock)


def main():
    args = parse_args()

    if args.url == "generate":
        print(ascii_alerts.RED + ascii_alerts.ascii_art_url + ascii_alerts.RESET)
        args.url = random_webhook_path()
        print(args.url)

    print(ascii_alerts.GREEN + ascii_alerts.ascii_art_hello + ascii_alerts.RESET)

    client = log_in(args.env, args.username, args.password, args.server, int(args.acc_num), int(args.acc_id))
    # The client names the account it chose only at debug, which also logs the
    # password (ADR 0025); the operator still needs to see which account trades.
    # Flushed, because without a terminal stdout waits for uvicorn's first
    # request line, and the first alert may trade before the line shows.
    print(f"Logged in: acc_id {client.account_id}, acc_num {client.acc_num}", flush=True)

    # One lock for the whole process: every request's signal runs inside it,
    # so two alerts never interleave between closing and ordering.
    app = create_app(args.url, build_signal_handler(client, threading.Lock(), SystemClock()).handle)

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_config=server_log_config())
