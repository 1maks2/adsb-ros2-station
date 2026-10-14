#!/bin/bash
# Zbiera konfigurację Raspberry Pi do katalogu system/ w repozytorium,
# robi commit i push. Uruchamiaj z katalogu projektu: ./backup_system.sh
# Skrypt sam poprosi o hasło sudo (część plików jest czytelna tylko dla roota).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$REPO_DIR/system"
FILES_DIR="$DEST/files"
STATE_DIR="$DEST/state"

# 1 = kopiuj też konfigurację sieci (netplan). UWAGA: zawiera hasła Wi-Fi!
INCLUDE_NETPLAN=0

# Pojedyncze pliki konfiguracyjne do skopiowania
FILES=(
  /boot/firmware/config.txt
  /boot/firmware/cmdline.txt
  /etc/hostname
  /etc/hosts
  /etc/fstab
  /usr/local/sbin/ensure-gpio-shutdown.sh
)

# Całe katalogi do skopiowania
DIRS=(
  /etc/systemd/logind.conf.d
  /etc/docker
)

echo "[INFO] Czyszczę poprzednią kopię..."
rm -rf "$DEST"
mkdir -p "$FILES_DIR" "$STATE_DIR"

copy_path() {
  local src="$1"
  if sudo test -e "$src"; then
    mkdir -p "$FILES_DIR$(dirname "$src")"
    sudo cp -a "$src" "$FILES_DIR$src"
    echo "  + $src"
  else
    echo "  - brak: $src (pomijam)"
  fi
}

echo "[INFO] Kopiuję pliki konfiguracyjne..."
for f in "${FILES[@]}"; do copy_path "$f"; done
for d in "${DIRS[@]}"; do copy_path "$d"; done

# Własne usługi systemd (zwykłe pliki, nie symlinki od pakietów)
echo "[INFO] Kopiuję własne usługi systemd..."
while IFS= read -r unit; do
  copy_path "$unit"
done < <(sudo find /etc/systemd/system -maxdepth 1 -type f \( -name '*.service' -o -name '*.timer' \))

if [ "$INCLUDE_NETPLAN" = "1" ]; then
  copy_path /etc/netplan
fi

echo "[INFO] Zapisuję stan systemu..."
{
  echo "# Data kopii: $(date -Iseconds)"
  echo; echo "## /etc/os-release"; cat /etc/os-release
  echo; echo "## uname -a"; uname -a
  echo; echo "## Model"; tr -d '\0' < /proc/device-tree/model; echo
} > "$STATE_DIR/system-info.txt"

systemctl get-default                                  > "$STATE_DIR/default-target.txt"
systemctl list-unit-files --state=enabled --no-pager   > "$STATE_DIR/enabled-services.txt"
apt-mark showmanual                                    > "$STATE_DIR/apt-packages-manual.txt"
crontab -l 2>/dev/null                                 > "$STATE_DIR/crontab-user.txt"  || true
sudo crontab -l 2>/dev/null                            > "$STATE_DIR/crontab-root.txt"  || true
docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null > "$STATE_DIR/docker-images.txt" || true

# Pliki skopiowane przez sudo należą do roota – oddaj je użytkownikowi
sudo chown -R "$(id -u):$(id -g)" "$DEST"

echo "[INFO] Commit i push..."
cd "$REPO_DIR"
git add -A
if git diff --cached --quiet; then
  echo "[INFO] Brak zmian – nic do zapisania."
else
  git commit -m "Backup $(date '+%Y-%m-%d %H:%M')"
  git push
  echo "[INFO] Gotowe – kopia wysłana."
fi
