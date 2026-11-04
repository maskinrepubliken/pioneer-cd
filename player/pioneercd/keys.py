"""Turns the buttons held down into presses.

Events: up, down, left, right, center, home (center held), vol_up (A),
vol_down (B) and mute (A and B together). Up, down, A and B repeat while
held. A or B alone waits COMBO seconds for the other before it counts, so
pressing both does not first change the volume.
"""
REPEAT_AFTER, REPEAT_EVERY = 0.4, 0.15
HOLD = 0.8
COMBO = 0.12

REPEATS = {"up": "up", "down": "down", "A": "vol_up", "B": "vol_down"}
ONCE = {"left": "left", "right": "right"}


class Keys:
    def __init__(self):
        self.down = {}       # button -> time it went down
        self.next = {}       # button -> time it next repeats
        self.held_home = False
        self.combo = False   # A and B were down together: nothing more until both are up

    def feed(self, pressed, now):
        events = []
        for b in set(self.down) - pressed:          # released
            t = self.down.pop(b)
            self.next.pop(b, None)
            if b == "center":
                if not self.held_home:
                    events.append("center")
                self.held_home = False
            if b in ("A", "B") and not self.combo and now - t < COMBO:
                events.append(REPEATS[b])          # a tap shorter than the wait
        for b in pressed - set(self.down):          # pressed
            self.down[b] = now
            if b in ONCE:
                events.append(ONCE[b])
            elif b in ("up", "down"):
                events.append(REPEATS[b])
                self.next[b] = now + REPEAT_AFTER
        if {"A", "B"} <= pressed and not self.combo:
            self.combo = True
            events.append("mute")
        if self.combo and not ({"A", "B"} & pressed):
            self.combo = False
        for b in ("A", "B"):
            if b in self.down and not self.combo:
                t = self.down[b]
                if b not in self.next and now - t >= COMBO:
                    events.append(REPEATS[b])
                    self.next[b] = t + REPEAT_AFTER
                elif b in self.next and now >= self.next[b]:
                    events.append(REPEATS[b])
                    self.next[b] = now + REPEAT_EVERY
        for b in ("up", "down"):
            if b in self.down and now >= self.next.get(b, now + 1):
                events.append(REPEATS[b])
                self.next[b] = now + REPEAT_EVERY
        if "center" in self.down and not self.held_home and now - self.down["center"] >= HOLD:
            self.held_home = True
            events.append("home")
        return events
