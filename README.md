# Pioneer CD

A music player for a Raspberry Pi 4: CDs from a USB drive, Jellyfin over the network and Bluetooth
from a phone, played through a small amplifier and controlled from a tiny colour screen with a
joystick. CDs, radio, Jellyfin and Bluetooth play.

## Part of the pioneer series

This is a pioneer project from Maskinrepubliken. Pioneer projects are small programs that run on a Raspberry Pi, each built for one specific place and purpose. They are open source, so you can read, change and run the code yourself. The code is kept small and plainly structured, which makes it easy to adapt, with or without AI tools. Treat it as a starting point for your own setup, not a finished product.

## Hardware

- Raspberry Pi 4 with Raspberry Pi OS Lite (64-bit, Trixie)
- [Adafruit Mini Color TFT with Joystick FeatherWing](https://www.adafruit.com/product/3321):
  a 160×80 ST7735R screen on SPI, and a seesaw chip on I2C (address `0x5E`) for the joystick, the
  A/B buttons, the backlight and the screen's reset
- a USB sound card (C-Media) into a Lepai LP-2020A+ amplifier (TA2020, two channels, 12 V)
- one 12 V power supply, split with a DC Y-cable between the amplifier and a 5 V USB-C step-down
  converter that powers the Pi, behind a 2.5 A slow fuse
- a USB DVD drive (a laptop drive, MATSHITA UJ8B0, in a USB–SATA case)

## Wiring the screen

FeatherWing pin → Raspberry Pi physical pin:

| FeatherWing | Pi pin | |
|---|---|---|
| 3V | 1 | 3.3 V |
| GND | 9 (or any ground) | ground |
| SCK | 23 | GPIO11, SPI clock |
| MO | 19 | GPIO10, SPI data |
| 5 | 24 | GPIO8, screen chip select |
| 6 | 22 | GPIO25, screen data/command |
| SDA | 3 | GPIO2, I2C |
| SCL | 5 | GPIO3, I2C |

On the FeatherWing, 5 and 6 are the first and second pins next to SCL on the short header
([Feather pinout](https://learn.adafruit.com/adafruit-feather/feather-specification)). MISO is not
used. Pin 1 of the Pi's header is at the end away from the USB ports.

## Trying the screen

```sh
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
sudo apt install python3-spidev python3-smbus2 python3-pil python3-numpy python3-libgpiod fonts-dejavu-core
python3 display/minitft.py
```

It draws colour bars, a white frame and the joystick's direction for a minute. The panel wants
colour inversion off and RGB order (`MADCTL 0x60`), with the picture 24 rows into the controller's
memory; these were found on the panel itself and differ from Adafruit's library defaults.

## The player

`player/` is a Python service that owns the screen and the buttons and plays through mpv:
Sveriges Radio live, with what is on now and next from SR's API, and Jellyfin's albums,
artists and playlists (called Bibliotek on the screen), with suggestions: most played,
recently played and recently added. Half a track, or four minutes, counts as a play in Jellyfin.
Bluetooth (Blåtand on the screen) makes it a speaker for a phone: BlueALSA receives and plays
the sound, and while the Blåtand screen is open the Pi is visible as "Pioneer CD" and pairs
without a code. A phone paired once is trusted and reconnects by itself; one source plays at a
time, so the phone starting stops the radio, and the radio starting pauses the phone. Install it on the Pi:

```sh
git clone https://github.com/maskinrepubliken/pioneer-cd.git
cd pioneer-cd
sudo system/install.sh
```

Then put Jellyfin's address and an API key (Jellyfin: Dashboard → API Keys) in
`/etc/pioneer-cd/config.toml` and `sudo systemctl restart pioneer-cd`. Logs:
`journalctl -u pioneer-cd -f`.

Radio starts P1 at once. The buttons: up and down move in lists, and change track or channel while something plays
(held, they jump a letter at a time); the middle picks, plays and pauses, and held goes Home;
left goes back, everywhere. A and B set the volume, both together mute. After ten minutes
without a press the screen goes dark; the first press only lights it. Right on Spelas nu opens Val: first Minns (a star), which keeps what plays, with all that is
known about it and the date, as a line of JSON in the inbox, `/var/lib/pioneer-cd/inkorg.jsonl`
(Glöm, once it is there, takes it out again); then Blanda
and Upprepa (av, låten, listan) for the library, and for every source Sovtimer (10, 20, 30, 50
minutes or an hour; its last half minute fades out, then the music stops and the screen sleeps)
and Vila, which darkens the screen at once.

Home lists what there is to play: Spelas nu while something plays, CD while a disc with music is
in the drive, Radio, Bibliotek and Blåtand. There is no settings screen: the volume cap, the
brightness, the minutes before the screen sleeps and the Bluetooth boost are set in the config's
`[player]` table; the volume itself is kept by the player.

## The CD drive

A laptop DVD drive in a USB–SATA case. Spinning up it draws more than the Pi 4's USB ports
give (1.2 A between them, a limit in the hardware): the ports cut out again and again
(`over-current change` in `dmesg`) and the sound card with them. The case's second USB plug
goes in a USB charger of its own, not in the Pi.

The player reads the disc's table of contents (libdiscid), plays the disc with mpv
(`cdda://`, a chapter a track) and names the tracks from, in turn: its own file for the disc,
`/var/lib/pioneer-cd/cd/<disc id>.json`, which can be written by hand; MusicBrainz, by the
disc's id, the tracks' lengths or the barcode (what it says is kept in that file); the disc's
own CD-Text (asked of the drive straight, READ TOC format 5: a fifth of a second, where
cd-info takes half a minute); or Spår 1, 2, …. A disc starts at once on its table of contents
and CD-Text; MusicBrainz's names, if it has any, come after.
A disc put in plays at once: another than the last one, or the same one taken out and put back
(the drive says it was shut empty in between). Opening and shutting the tray with the disc in
does nothing.

## Saving a CD

Spara skivan in Val (right on a CD) saves the disc as FLAC on the Pi and then into Jellyfin.
The drive reads one place at a time, so the disc is saved only while it does not play:
cdparanoia (its fast mode; the paranoid ones read slower than the music plays on this drive)
is stopped while the disc plays and goes on when it is paused or done. The files are in
`/var/lib/pioneer-cd/cd-rips/<disc id>/<artist>/<album>/`. Saved, the album goes as a tar
stream over ssh to the server named in `[upload]`, with a key of the Pi's own that the server
lets do one thing only, in `~/.ssh/authorized_keys` there:

    restrict,command="cd '/Volumes/Collections/Musik/Pioneer CD' && exec /usr/bin/tar -xf - --no-same-owner" ssh-ed25519 … pioneer-cd upload

and Jellyfin is told the folder is new (`/Library/Media/Updated`). Jellyfin has no API to
upload music: it reads folders on its server.

## Sound

The USB sound card is the default output, through a volume control of the player's own:
`system/asound.conf` puts an ALSA softvol control, "Pioneer", in front of the card. The player
shows the volume as a number from 0 to 100, as on a TV, one step a press of A or B, and sets the
control to 27·log10(n/100) dB, so 28 is −15 dB: the level that sounded right through the
amplifier. The card's own control stays at full.

`speaker-test -c 2 -t wav` says "Front Left" and "Front Right" from each speaker in turn.

## Power cuts

A power cut right after an install once left every file just written empty, the systemd unit
too (an empty unit reads as masked). `install.sh` syncs before it starts the service, and the
player writes its settings beside the old file and renames it over. If it happens again:
`find /home/pi/pioneer-cd /etc/pioneer-cd -size 0`, then clone and install again.
