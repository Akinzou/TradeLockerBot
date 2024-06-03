import random
import string

def generate_random_url(min_length=10, max_length=20):
    length1 = random.randint(min_length, max_length)
    random_string1 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length1))
    length2 = random.randint(min_length, max_length)
    random_string2 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length2))
    url = f'/{random_string1}/{random_string2}'
    return url