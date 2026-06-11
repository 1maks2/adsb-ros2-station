# Bazowy obraz ROS2 Jazzy dla ARM64 (Raspberry Pi)
FROM ros:jazzy-ros-base

# Aktualizacja listy pakietów
RUN apt-get update && apt-get upgrade -y

# Instalacja podstawowych narzędzi sieciowych i systemowych
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    iproute2 \
    net-tools \
    netcat-openbsd \
    tcpdump \
    iptables \
    nftables \
    curl \
    wget \
    nano \
    vim \
    htop \
    tree \
    git \
    cmake \
    build-essential \
    python3-pip \
    python3-colcon-common-extensions \
    ros-jazzy-demo-nodes-cpp \
    ros-jazzy-demo-nodes-py \
    python3-serial \
    && rm -rf /var/lib/apt/lists/*
    

# INSTALACJA STEROWNIKÓW RTL-SDR
RUN apt-get update && apt-get install -y \
    rtl-sdr \
    librtlsdr-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalacja biblioteki Python do obsługi SDR (przydatne do węzłów ROS2 w Pythonie)
RUN pip3 install --break-system-packages pyrtlsdr
# Instalacja bibliotek do obsługi wyświetlacza TFT
RUN pip3 install --break-system-packages luma.lcd RPi.GPIO spidev
# Ustawienie katalogu roboczego
WORKDIR /ros2_ws

# Konfiguracja środowiska ROS2
RUN echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc

# Komenda domyślna
CMD ["/bin/bash"]