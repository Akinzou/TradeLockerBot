"""Colours and banners of the operator's console output.

Moved from the legacy ``libs/`` package (ADR 0010). The greeting is a raw
string: the plain one held backslash sequences that are no valid escape,
which Python keeps as written but warns about. The text is the same, byte
for byte; the startup tests pin it.
"""

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def reset_style():
    print(RESET)


def print_red(text):
    """One red line, with the reset inside the same print rather than in a
    line after it: another thread's line can print in between, and it must
    not inherit the red."""
    print(f"{RED}{text}\n{RESET}")


def print_green(text):
    """One green line, its reset inside the same print, as ``print_red``.
    ``order_placed`` keeps the legacy two prints, which its tests pin; a new
    line has no such bytes to keep."""
    print(f"{GREEN}{text}\n{RESET}")


ascii_art_url = """
                                  _
 ___  __ ___   _____   _   _ _ __| |
/ __|/ _` \\ \\ / / _ \\ | | | | '__| |
\\__ \\ (_| |\\ V /  __/ | |_| | |  | |
|___/\\__,_| \\_/ \\___|  \\__,_|_|  |_|
"""

ascii_art_hello = r"""
 _____              _      _               _             ____        _
|_   _| __ __ _  __| | ___| |    ___   ___| | _____ _ __| __ )  ___ | |_
  | || '__/ _` |/ _` |/ _ \ |   / _ \ / __| |/ / _ \ '__|  _ \ / _ \| __|
  | || | | (_| | (_| |  __/ |__| (_) | (__|   <  __/ |  | |_) | (_) | |_
  |_||_|  \__,_|\__,_|\___|_____\___/ \___|_|\_\___|_|  |____/ \___/ \__|
"""
