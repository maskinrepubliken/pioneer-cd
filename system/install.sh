#!/bin/sh
# Installs Pioneer CD on Raspberry Pi OS Lite. Run from the checkout:
#   sudo system/install.sh
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)

apt-get install -y mpv fonts-ibm-plex python3-spidev python3-smbus2 python3-pil python3-numpy python3-libgpiod
raspi-config nonint do_spi 0
raspi-config nonint do_i2c 0

# The USB sound card is the default output, through the player's own volume
# control (see the file). An older /etc/asound.conf is kept beside it.
if ! cmp -s "$REPO/system/asound.conf" /etc/asound.conf; then
    [ -s /etc/asound.conf ] && cp /etc/asound.conf "/etc/asound.conf.bak-$(date +%F)"
    install -m 644 "$REPO/system/asound.conf" /etc/asound.conf
fi

install -d -m 755 /etc/pioneer-cd
if [ ! -s /etc/pioneer-cd/config.toml ]; then
    install -m 640 -g pi "$REPO/player/config.example.toml" /etc/pioneer-cd/config.toml
fi

sed "s|@REPO@|$REPO|" "$REPO/system/pioneer-cd.service" > /etc/systemd/system/pioneer-cd.service
# A power cut right after an install once left every new file empty: write them out now.
sync
systemctl daemon-reload
systemctl enable pioneer-cd
systemctl restart pioneer-cd
echo "Pioneer CD runs. Logs: journalctl -u pioneer-cd -f"
