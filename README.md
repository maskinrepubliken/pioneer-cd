# Pioneer CD

A music player for a Raspberry Pi 4: CDs from a USB drive, Jellyfin over the network and Bluetooth
from a phone, played through a small amplifier and controlled from a tiny colour screen with a
joystick. Early days: so far the screen and its buttons work, and the power and sound hardware is
on its way.

## Part of the pioneer series

This is a pioneer project from Maskinrepubliken. Pioneer projects are small programs that run on a Raspberry Pi, each built for one specific place and purpose. They are open source, so you can read, change and run the code yourself. The code is kept small and plainly structured, which makes it easy to adapt, with or without AI tools. Treat it as a starting point for your own setup, not a finished product.

## Hardware

- Raspberry Pi 4 with Raspberry Pi OS Lite (64-bit, Trixie)
- [Adafruit Mini Color TFT with Joystick FeatherWing](https://www.adafruit.com/product/3321):
  a 160×80 ST7735R screen on SPI, and a seesaw chip on I2C (address `0x5E`) for the joystick, the
  A/B buttons, the backlight and the screen's reset
- a USB sound card into a stand-alone 12–24 V amplifier board
- one 12–24 V power supply, split with a DC Y-cable between the amplifier and a 5 V USB-C
  step-down converter that powers the Pi
- a USB CD drive

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
