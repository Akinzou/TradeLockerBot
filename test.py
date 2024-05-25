import threading
import time

def print_i_continuously():
    while True:
        print("i")
        time.sleep(10)

def accept_user_input():
    while True:
        user_input = input()
        print(f"Otrzymano: {user_input}")

# Utworzenie wątku dla ciągłego printowania "i"
thread_print_i = threading.Thread(target=print_i_continuously)
thread_print_i.start()

# Utworzenie wątku dla przyjmowania wejścia użytkownika
thread_user_input = threading.Thread(target=accept_user_input)
thread_user_input.start()
