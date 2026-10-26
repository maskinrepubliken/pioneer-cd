"""Adafruit Mini Color TFT with Joystick FeatherWing (3321) on a Raspberry Pi.

The picture goes over SPI (spidev0.0, DC on GPIO25) to the ST7735R; the
backlight, the TFT's reset and the joystick and buttons are on the board's
seesaw chip, on I2C at 0x5E.

    python3 minitft.py [x_offset y_offset madctl]
"""
import os
import sys
import time

import gpiod
import numpy as np
import spidev
from gpiod.line import Direction, Value
from PIL import Image, ImageDraw, ImageFont
from smbus2 import SMBus, i2c_msg

WIDTH, HEIGHT = 160, 80
DC_PIN = 25

# seesaw
ADDR = 0x5E
BACKLIGHT, TFT_RESET = 5, 8
BUTTONS = {"upp": 2, "vänster": 3, "ner": 4, "höger": 7, "B": 9, "A": 10, "mitten": 11}


class Seesaw:
    def __init__(self, bus=1):
        self.bus = SMBus(bus)

    def write(self, module, function, data=b""):
        self.bus.i2c_rdwr(i2c_msg.write(ADDR, bytes([module, function]) + bytes(data)))

    def read(self, module, function, n):
        self.write(module, function)
        time.sleep(0.005)
        msg = i2c_msg.read(ADDR, n)
        self.bus.i2c_rdwr(msg)
        return bytes(msg)

    def hw_id(self):
        return self.read(0x00, 0x01, 1)[0]

    def _mask(self, pins):
        m = 0
        for p in pins:
            m |= 1 << p
        return m.to_bytes(4, "big")

    def output(self, pins):
        self.write(0x01, 0x02, self._mask(pins))

    def input_pullup(self, pins):
        self.write(0x01, 0x03, self._mask(pins))   # direction: input
        self.write(0x01, 0x0B, self._mask(pins))   # pull enable
        self.write(0x01, 0x05, self._mask(pins))   # pull up

    def set(self, pins, high):
        self.write(0x01, 0x05 if high else 0x06, self._mask(pins))

    def pins(self):
        return int.from_bytes(self.read(0x01, 0x04, 4), "big")

    def pwm(self, pin, value):
        self.write(0x08, 0x01, bytes([pin, value >> 8, value & 0xFF]))


class ST7735R:
    def __init__(self, x_off, y_off, madctl):
        self.x_off, self.y_off, self.madctl = x_off, y_off, madctl
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = int(os.environ.get("SPI_HZ", 16_000_000))
        self.spi.mode = 0
        self.dc = gpiod.request_lines("/dev/gpiochip0", consumer="minitft",
                                      config={DC_PIN: gpiod.LineSettings(direction=Direction.OUTPUT)})

    def cmd(self, c, data=b""):
        self.dc.set_value(DC_PIN, Value.INACTIVE)
        self.spi.writebytes([c])
        if data:
            self.dc.set_value(DC_PIN, Value.ACTIVE)
            self.spi.writebytes2(bytes(data))

    def init(self):
        seq = [
            (0x01, b"", 0.15),                      # software reset
            (0x11, b"", 0.5),                       # out of sleep
            (0xB1, b"\x01\x2c\x2d", 0), (0xB2, b"\x01\x2c\x2d", 0),
            (0xB3, b"\x01\x2c\x2d\x01\x2c\x2d", 0), (0xB4, b"\x07", 0),
            (0xC0, b"\xa2\x02\x84", 0), (0xC1, b"\xc5", 0), (0xC2, b"\x0a\x00", 0),
            (0xC3, b"\x8a\x2a", 0), (0xC4, b"\x8a\xee", 0), (0xC5, b"\x0e", 0),
            (0x20, b"", 0),                         # not inverted (tried on the panel)
            (0x36, bytes([self.madctl]), 0),
            (0x3A, b"\x05", 0),                     # 16 bits a pixel
            (0xE0, bytes.fromhex("021c07123732292d29252b3900010310"), 0),
            (0xE1, bytes.fromhex("031d07062e2c292d2e2e373f00000210"), 0),
            (0x13, b"", 0.01), (0x29, b"", 0.1),
        ]
        for c, d, wait in seq:
            self.cmd(c, d)
            time.sleep(wait)

    def show(self, img):
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        px = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
        x0, y0 = self.x_off, self.y_off
        self.cmd(0x2A, bytes([0, x0, 0, x0 + WIDTH - 1]))
        self.cmd(0x2B, bytes([0, y0, 0, y0 + HEIGHT - 1]))
        self.cmd(0x2C, px.astype(">u2").tobytes())


def test_image(text=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    bars = ["red", "lime", "blue", "white", "yellow", "cyan", "magenta", "black"]
    for i, c in enumerate(bars):
        d.rectangle([i * 20, 0, i * 20 + 19, 24], fill=c)
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline="white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    d.text((6, 30), "pioneer-cd", font=font, fill="white")
    d.text((6, 54), text, font=font, fill="orange")
    return img


def main():
    x_off, y_off, madctl = (int(a, 0) for a in sys.argv[1:4]) if len(sys.argv) > 3 else (0, 24, 0x60)
    ss = Seesaw()
    print("seesaw hw id", hex(ss.hw_id()))
    ss.output([TFT_RESET])
    ss.set([TFT_RESET], False)
    time.sleep(0.05)
    ss.set([TFT_RESET], True)
    time.sleep(0.15)
    ss.pwm(BACKLIGHT, 0)                              # backlight: 0 is full on, by the library's convention
    ss.input_pullup(BUTTONS.values())

    tft = ST7735R(x_off, y_off, madctl)
    tft.init()
    tft.show(test_image("tryck!"))
    print("visar testbild; knappar i 60 s")
    last = None
    end = time.time() + 60
    while time.time() < end:
        state = ss.pins()
        pressed = [n for n, p in BUTTONS.items() if not state & (1 << p)]
        if pressed != last:
            print("knappar:", pressed)
            tft.show(test_image(" ".join(pressed) or "tryck!"))
            last = pressed
        time.sleep(0.05)


if __name__ == "__main__":
    main()
