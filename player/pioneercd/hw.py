"""The Mini Color TFT with Joystick FeatherWing (Adafruit 3321).

The picture goes over SPI (spidev0.0, DC on GPIO25) to the ST7735R; the
backlight, the TFT's reset and the joystick and buttons are on the board's
seesaw chip, on I2C at 0x5E. display/minitft.py is the same driver as a
stand-alone test.
"""
import time

import gpiod
import numpy as np
import spidev
from gpiod.line import Direction, Value
from smbus2 import SMBus, i2c_msg

WIDTH, HEIGHT = 160, 80
DC_PIN = 25

ADDR = 0x5E
BACKLIGHT, TFT_RESET = 5, 8
BUTTONS = {"up": 2, "left": 3, "down": 4, "right": 7, "B": 9, "A": 10, "center": 11}


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

    @staticmethod
    def _mask(pins):
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
    # Found on the panel: no inversion, RGB, landscape, 24 rows into the controller's memory.
    X_OFF, Y_OFF, MADCTL = 0, 24, 0x60

    def __init__(self, hz=4_000_000):
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = hz
        self.spi.mode = 0
        self.dc = gpiod.request_lines("/dev/gpiochip0", consumer="pioneer-cd",
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
            (0x20, b"", 0),                         # not inverted
            (0x36, bytes([self.MADCTL]), 0),
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
        x0, y0 = self.X_OFF, self.Y_OFF
        self.cmd(0x2A, bytes([0, x0, 0, x0 + WIDTH - 1]))
        self.cmd(0x2B, bytes([0, y0, 0, y0 + HEIGHT - 1]))
        self.cmd(0x2C, px.astype(">u2").tobytes())


class Board:
    """The screen, its backlight and the seven buttons."""

    def __init__(self):
        self.ss = Seesaw()
        self.ss.output([TFT_RESET])
        self.ss.set([TFT_RESET], False)
        time.sleep(0.05)
        self.ss.set([TFT_RESET], True)
        time.sleep(0.15)
        self.ss.input_pullup(BUTTONS.values())
        self.tft = ST7735R()
        self.tft.init()
        self._pressed = set()

    def backlight(self, percent):
        # The seesaw's PWM is inverted on this board: 0 is full on.
        self.ss.pwm(BACKLIGHT, round(0xFFFF * (100 - max(0, min(100, percent))) / 100))

    def pressed(self):
        """The buttons held down now. A failed I2C read (a loose wire) keeps the last answer."""
        try:
            state = self.ss.pins()
        except OSError:
            return self._pressed
        self._pressed = {name for name, pin in BUTTONS.items() if not state & (1 << pin)}
        return self._pressed

    def show(self, img):
        self.tft.show(img)
