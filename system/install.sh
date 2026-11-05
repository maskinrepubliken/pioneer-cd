#!/bin/sh
# Installs Pioneer CD on Raspberry Pi OS Lite. Run from the checkout:
#   sudo system/install.sh
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)

apt-get install -y mpv fonts-ibm-plex python3-spidev python3-smbus2 python3-pil python3-numpy python3-libgpiod \
    bluez-alsa-utils bluez-tools python3-dbus python3-libdiscid
raspi-config nonint do_spi 0
raspi-config nonint do_i2c 0

# The USB sound card is the default output, through the player's own volume
# control (see the file). An older /etc/asound.conf is kept beside it.
if ! cmp -s "$REPO/system/asound.conf" /etc/asound.conf; then
    [ -s /etc/asound.conf ] && cp /etc/asound.conf "/etc/asound.conf.bak-$(date +%F)"
    install -m 644 "$REPO/system/asound.conf" /etc/asound.conf
fi

# Bluetooth (Blåtand on the screen): a speaker called Pioneer CD. BlueALSA
# only receives and plays to the default output; bt-agent accepts pairing
# without a code, which the player allows only while Blåtand is open.
rfkill unblock bluetooth
sed -i -e 's/^#\?Name = .*/Name = Pioneer CD/' -e 's/^#\?Class = .*/Class = 0x200414/' \
    -e 's/^#\?DiscoverableTimeout = .*/DiscoverableTimeout = 0/' /etc/bluetooth/main.conf
install -D -m 644 "$REPO/system/bluealsa-sink.conf" /etc/systemd/system/bluealsa.service.d/pioneer-cd.conf
install -m 644 "$REPO/system/pioneer-cd-bt-agent.service" /etc/systemd/system/pioneer-cd-bt-agent.service

install -d -m 755 /etc/pioneer-cd
if [ ! -s /etc/pioneer-cd/config.toml ]; then
    install -m 640 -g pi "$REPO/player/config.example.toml" /etc/pioneer-cd/config.toml
fi

sed "s|@REPO@|$REPO|" "$REPO/system/pioneer-cd.service" > /etc/systemd/system/pioneer-cd.service
# A power cut right after an install once left every new file empty: write them out now.
sync
systemctl daemon-reload
systemctl enable bluealsa bluealsa-aplay pioneer-cd-bt-agent pioneer-cd
systemctl restart bluetooth bluealsa bluealsa-aplay pioneer-cd-bt-agent pioneer-cd
echo "Pioneer CD runs. Logs: journalctl -u pioneer-cd -f"
