"""Add a soundtrack to design.mp4, reusing the instruments in promo/sound.py.

    python promo/linkedin/sound.py
"""
import pathlib, subprocess, sys, wave

import numpy as np

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import sound as s  # noqa: E402

# timeline of design.html
s.LENGTH = 48.0
s.SCENE_STARTS = [4, 11.5, 16.5, 23.5, 29.5, 35, 42]
s.DROP = 4.0
s.END_HIT = 42.0
s.N = int(s.LENGTH * s.SR)
s.T = np.arange(s.N) / s.SR
s.OVERLAP = 0.0


def make_fx():
    bus = s.stereo()
    s.place(bus, s.boom(3.0) * 0.5, 0.2, 0.7)
    s.place(bus, s.pop(1200, 700), 0.3, 0.35)
    for start in s.SCENE_STARTS:
        s.place(bus, s.whoosh(), start - 0.55, 0.3)
    for i, at in enumerate((0.6, 0.9, 1.4)):  # intro lines
        s.place(bus, s.pop(760 + 120 * i, 520), at, 0.16)
    for i, at in enumerate((5.2, 6.0, 7.4, 8.2, 9.6)):  # widget tags
        s.place(bus, s.pop(900 + 60 * i, 560), at, 0.2, pan=-0.4 + 0.2 * i)
    s.place(bus, s.whoosh(1.6) * 0.8, 12.4, 0.32)  # light-to-dark wipe
    for i, at in enumerate((19, 19.6, 20.2)):
        s.place(bus, s.pop(700, 420), at, 0.2, pan=-0.5 + i * 0.5)
    s.place(bus, s.whoosh(), 23.4, 0.22)
    s.place(bus, s.whoosh(), 24.2, 0.22)
    for i in range(10):  # filament pills
        s.place(bus, s.pop(1000 + 40 * i, 640), 30.6 + i * 0.16, 0.14, pan=-0.6 + (i % 4) * 0.4)
    s.place(bus, s.riser(1.6), s.END_HIT - 1.6, 0.35)
    s.place(bus, s.boom(4.0), s.END_HIT, 0.8)
    for i, at in enumerate((42.8, 43.3, 43.7)):
        s.place(bus, s.pop(760 + 120 * i, 520), at, 0.14)
    return bus


s.make_fx = make_fx
s.HERE = HERE
src = open(HERE.parent / "sound.py").read()
# run promo/sound.py's main() with this timeline, on design.mp4
main_src = src[src.index("def main():"):src.index('if __name__')].replace('"promo.mp4"', '"design.mp4"').replace(
    '"promo_with_sound.mp4"', '"design_with_sound.mp4"')
ns = dict(vars(s))
exec(main_src, ns)
ns["main"]()
