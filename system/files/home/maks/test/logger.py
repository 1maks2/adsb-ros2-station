import os
import time

# Ścieżka do pliku, w którym zapiszemy temperaturę
path = "/home/maks/test/public-html/temp.txt"

def get_temp():
    # Wykonuje komendę systemową sprawdzającą temp. procesora
    res = os.popen('vcgencmd measure_temp').readline()
    # Czyści wynik, żeby została sama liczba (np. 45.2)
    return res.replace("temp=","").replace("'C\n","")

print("Startowanie logowania temperatury... Naciśnij Ctrl+C, aby zatrzymać.")

while True:
    temp = get_temp()
    with open(path, "w") as f:
        f.write(temp)
    print(f"Aktualna temperatura: {temp}°C")
    time.sleep(2) # Odświeżaj co 2 sekundy