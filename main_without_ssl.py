"""The container's command (frozen name, see the roadmap's frozen contract).

Everything it ran now lives in ``tradelocker_bot``; the composition root
reads the arguments and starts the bot (ADR 0010).
"""

from tradelocker_bot.composition_root import main

if __name__ == "__main__":
    main()
