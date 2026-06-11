#!/bin/bash
set -e

#xhost +local:root

# Nazwa kontenera (dopasuj do swojego docker-compose.yml)
CONTAINER_NAME="ros2_jazzy_lpa"
DOCKER_COMPOSE_FILE="docker-composer.yml"

echo "[INFO] Sprawdzam czy kontener '$CONTAINER_NAME' działa..."
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "[INFO] Kontener działa – zatrzymuję docker compose..."
    docker compose -f $DOCKER_COMPOSE_FILE down
fi

echo "[INFO] Uruchamiam kontener..."
docker compose -f $DOCKER_COMPOSE_FILE up -d

echo "[INFO] Czekam aż kontener wystartuje..."
sleep 2

echo "[INFO] Łączę się z kontenerem '$CONTAINER_NAME'..."
docker exec -e DISPLAY=unix$DISPLAY -it $CONTAINER_NAME /bin/bash -c "source /opt/ros/jazzy/setup.bash && /bin/bash"
