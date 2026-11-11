"""The server's log settings are a copy: uvicorn writes into the dictionary it
is given, so handing it its own module-level default would change that
default for every later server in the process (ADR 0016).

What the settings make a real server write is pinned in
``tests/characterization/test_server_log.py``.
"""

import copy

from uvicorn.config import LOGGING_CONFIG

from tradelocker_bot.adapters.webhook import server_log_config


def test_building_the_settings_leaves_uvicorns_default_as_shipped():
    shipped = copy.deepcopy(LOGGING_CONFIG)

    server_log_config()

    assert LOGGING_CONFIG == shipped


def test_writing_into_one_copy_changes_no_other():
    first, second = server_log_config(), server_log_config()

    first["formatters"]["access"]["use_colors"] = True

    assert "use_colors" not in second["formatters"]["access"]
