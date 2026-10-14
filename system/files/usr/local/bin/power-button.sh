#!/bin/bash
# Wyłącza system po przytrzymaniu przycisku na GPIO3 (pin 5 <-> GND) przez HOLD sekund.
HOLD=2

while true; do
    # czekaj na zwarcie GPIO3 do masy (zbocze opadające)
    gpiomon -n 1 -f -B pull-up gpiochip0 3

    # sprawdzaj przez HOLD sekund, czy przycisk jest nadal trzymany
    held=true
    for i in $(seq 1 $((HOLD * 10))); do
        sleep 0.1
        if [ "$(gpioget -B pull-up gpiochip0 3)" = "1" ]; then
            held=false
            break
        fi
    done

    if [ "$held" = true ]; then
        /sbin/poweroff
        exit 0
    fi
done
