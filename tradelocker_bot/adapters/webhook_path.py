"""The random webhook path ``--url generate`` serves.

Moved from the legacy ``libs/`` package (ADR 0010); only the function's name
changed, from ``generate_random_url``. It still draws
from ``random``, not a cryptographically secure source, although the path is
the only thing protecting the endpoint: a known defect that roadmap step 6
fixes as a behaviour change of its own.
"""

import random
import string


def random_webhook_path(min_length=10, max_length=20):
    length1 = random.randint(min_length, max_length)
    random_string1 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length1))
    length2 = random.randint(min_length, max_length)
    random_string2 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length2))
    url = f'/{random_string1}/{random_string2}'
    return url
