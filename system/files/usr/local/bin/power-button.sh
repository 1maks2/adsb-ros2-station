#!/bin/bash
HOLD=2   # ile sekund trzeba trzymać

while true; do
    # czekaj na zwarcie GPIO3 do masy (zbocze opadające)
    gpiomon -n 1 -f -B pull-up gpiochip0 3

    # przycisk wciśnięty - sprawdzaj przez HOLD sekund, czy trzymany
    held=true
    for i in $(seq 1 $((HOLD * 10))); do
        sleep 0.1
        # odczytaj stan pinu; jeśli zwolniony (stan wysoki = 1), przerwij
        if [ "$(gpioget -B pull-up gpiochip0 3)" = "1" ]; then
            held=false
            break
        fi
    done

    if [ "$held" = true ]; then
        /sbin/poweroff
    fi
done#!/bin/bash
while true; do
    gpiomon -n 1 -f -B pull-up gpiochip0 3
    sleep 0.1
    /sbin/poweroff
done
