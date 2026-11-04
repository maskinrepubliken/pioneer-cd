"""The CD drive: whether a disc is in, and whether it has music.

Asked straight from the drive with the kernel's CD-ROM ioctls (the user is
in the cdrom group), every few seconds in a thread of its own: an answer
can take a moment while the disc spins up.
"""
import fcntl
import os
import threading
import time

DEVICE = "/dev/sr0"
CDROM_DRIVE_STATUS, CDROM_DISC_STATUS = 0x5326, 0x5327
CDS_DISC_OK = 4
CDS_AUDIO, CDS_MIXED = 100, 105


def disc(device=DEVICE):
    """"audio" for a disc with music on it, "data" for another disc, None for none (or no drive)."""
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0) != CDS_DISC_OK:
            return None
        return "audio" if fcntl.ioctl(fd, CDROM_DISC_STATUS, 0) in (CDS_AUDIO, CDS_MIXED) else "data"
    except OSError:
        return None
    finally:
        os.close(fd)


def watch(changed, every=3):
    """Calls changed(disc()) now and whenever the answer changes."""
    def run():
        last = object()
        while True:
            now = disc()
            if now != last:
                last = now
                changed(now)
            time.sleep(every)
    threading.Thread(target=run, daemon=True).start()
