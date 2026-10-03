"""Make the promo soundtrack and add it to promo.mp4.

The music and sound effects are generated here (no samples), so there are no
licence questions. Times match the scene timeline in promo.html.

    pip install numpy scipy
    python promo/sound.py
"""

import pathlib
import subprocess
import wave

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

HERE = pathlib.Path(__file__).parent
SR = 44100
LENGTH = 57.0
BPM = 120
BEAT = 60 / BPM
BAR = BEAT * 4
OVERLAP = 0.4  # scenes start this much before their slot (see promo.html)

# scene slots from promo.html; a whoosh plays as each one comes in
SCENE_STARTS = [4, 10.5, 15.5, 20.5, 25.5, 30.5, 35, 39.5, 44.5, 50]
DROP = 10.5   # drums come in with "Get a full admin panel"
END_HIT = 50.0

rng = np.random.default_rng(7)
N = int(LENGTH * SR)
T = np.arange(N) / SR


def stereo():
    return np.zeros((N, 2))


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def filt(x, kind, freq, order=2):
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def place(bus, sound, at, gain=1.0, pan=0.0):
    """Add a mono or stereo sound to a bus at time ``at`` (pan -1 left .. 1 right)."""
    i = int(at * SR)
    if i >= N:
        return
    if sound.ndim == 1:
        left, right = np.sqrt((1 - pan) / 2), np.sqrt((1 + pan) / 2)
        sound = np.stack([sound * left, sound * right], axis=1)
    sound = sound[: N - i]
    bus[i: i + len(sound)] += sound * gain


def saw(freq, t):
    return 2 * ((freq * t) % 1.0) - 1


# ---------------------------------------------------------------- instruments
def kick():
    t = np.arange(int(0.45 * SR)) / SR
    freq = 46 + 90 * np.exp(-t * 28)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t * 7)
    click = filt(rng.standard_normal(len(t)), "highpass", 2500) * np.exp(-t * 300) * 0.25
    return np.tanh((body + click) * 1.6)


def clap():
    t = np.arange(int(0.35 * SR)) / SR
    noise = filt(rng.standard_normal(len(t)), "bandpass", [900, 3200])
    env = np.exp(-t * 18)
    for d in (0.0, 0.011, 0.022):  # three quick hits make it sound like hands
        env = env + np.where(t >= d, np.exp(-(t - d) * 120), 0) * 0.6
    return noise * env * 0.5


def hat(open_=False):
    t = np.arange(int((0.35 if open_ else 0.08) * SR)) / SR
    noise = filt(rng.standard_normal(len(t)), "highpass", 7000)
    return noise * np.exp(-t * (11 if open_ else 70)) * 0.35


def pluck(freq, length=0.32):
    t = np.arange(int(length * SR)) / SR
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t) + 0.12 * saw(freq, t)
    return tone * np.exp(-t * 14) * np.minimum(1, t * 400)


def pop(f0=880, f1=560):
    t = np.arange(int(0.12 * SR)) / SR
    freq = f1 + (f0 - f1) * np.exp(-t * 40)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 38) * np.minimum(1, t * 900)


def click():
    t = np.arange(int(0.025 * SR)) / SR
    noise = filt(rng.standard_normal(len(t)), "highpass", 3000) * np.exp(-t * 500)
    tick = np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 400) * 0.4
    return noise + tick


def whoosh(length=0.75):
    """Noise that swells and brightens, then falls away. Panned left to right."""
    t = np.arange(int(length * SR)) / SR
    p = t / length
    noise = rng.standard_normal(len(t))
    dark, bright = filt(noise, "lowpass", 700), filt(noise, "bandpass", [1500, 6000])
    shape = np.sin(np.pi * np.clip(p / 0.8, 0, 1)) ** 2 * np.where(p < 0.8, 1, np.exp(-(p - 0.8) * 30))
    mono = (dark * (1 - shape) * 0.6 + bright * shape) * shape
    pan = -0.7 + 1.4 * p
    return np.stack([mono * np.sqrt((1 - pan) / 2), mono * np.sqrt((1 + pan) / 2)], axis=1)


def riser(length):
    t = np.arange(int(length * SR)) / SR
    p = t / length
    noise = rng.standard_normal(len(t))
    low, high = filt(noise, "lowpass", 900), filt(noise, "highpass", 3000)
    tone = np.sin(2 * np.pi * np.cumsum(220 + 660 * p ** 2) / SR) * 0.15
    return ((low * (1 - p) + high * p) * 0.5 + tone) * p ** 2.2


def boom(length=2.5):
    t = np.arange(int(length * SR)) / SR
    freq = 38 + 60 * np.exp(-t * 9)
    sub = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 2.2)
    crash = filt(rng.standard_normal(len(t)), "highpass", 4500) * np.exp(-t * 2.4) * 0.35
    return np.tanh(sub * 1.4) + crash


# ---------------------------------------------------------------- music
# Am - F - C - G, one bar each (bass note, chord notes)
CHORDS = [
    (45, [57, 60, 64, 67]),
    (41, [53, 57, 60, 64]),
    (48, [55, 60, 64, 71]),
    (43, [55, 59, 62, 69]),
]
FINAL = (48, [55, 60, 64, 67, 71, 74])  # Cmaj9 to close


def chord_at(t):
    return CHORDS[int(t // BAR) % len(CHORDS)]


def make_pad():
    bus = stereo()
    music_end = END_HIT
    bars = int(np.ceil(music_end / BAR))
    for b in range(bars + 1):
        start = b * BAR
        final = start >= music_end
        bass, notes = FINAL if final else chord_at(start)
        length = (LENGTH - start) if final else BAR + 0.6
        t = np.arange(int(length * SR)) / SR
        env = np.minimum(1, t / 0.35) * np.minimum(1, np.maximum(0, (length - t) / 0.6))
        if final:
            env = np.minimum(1, t / 0.05) * np.exp(-t * 0.35)
        left = np.zeros(len(t))
        right = np.zeros(len(t))
        for n in notes:
            f = midi(n)
            for k, cents in enumerate((-8, 0, 8)):
                wave_ = saw(f * 2 ** (cents / 1200), t + rng.random())
                if k == 0:
                    left += wave_
                elif k == 2:
                    right += wave_
                else:
                    left += wave_ * 0.5
                    right += wave_ * 0.5
        pad = np.stack([left, right], axis=1) / (len(notes) * 2)
        pad = filt(pad, "lowpass", 1400 if not final else 2200)
        place(bus, pad * env[:, None], start, 0.55)
        if final:
            break
    return bus


def make_bass():
    bus = stereo()
    step = BEAT / 2
    t_ = 4.0
    while t_ < END_HIT - 0.01:
        root, _ = chord_at(t_)
        f = midi(root + (12 if int(round(t_ / step)) % 4 == 3 else 0))
        length = step * 0.95
        t = np.arange(int(length * SR)) / SR
        tone = np.sin(2 * np.pi * f * t) + 0.5 * filt(saw(f, t), "lowpass", 500)
        env = np.minimum(1, t * 200) * np.exp(-t * 4)
        # before the drop the bass only plays on the beat, softly
        if t_ < DROP and int(round(t_ / step)) % 2:
            t_ += step
            continue
        place(bus, tone * env, t_, 0.42 if t_ >= DROP else 0.25)
        t_ += step
    return bus


def make_arp():
    bus = stereo()
    step = BEAT / 4
    i = 0
    t_ = 2.0
    pattern = [0, 1, 2, 3, 2, 1, 2, 3]
    while t_ < END_HIT - 0.01:
        _, notes = chord_at(t_)
        n = notes[pattern[i % len(pattern)]] + 12
        gain = 0.16 if t_ < 4 else 0.2
        place(bus, pluck(midi(n)), t_, gain, pan=0.35 if i % 2 else -0.35)
        i += 1
        t_ += step
    return bus


def make_drums():
    bus = stereo()
    kicks = []
    k, c, h, ho = kick(), clap(), hat(), hat(True)
    beat = DROP
    while beat < END_HIT - 0.4:
        place(bus, k, beat, 0.9)
        kicks.append(beat)
        n = int(round((beat - DROP) / BEAT))
        if n % 2 == 1:
            place(bus, c, beat, 0.55, pan=0.05)
        place(bus, ho if (beat >= 25 and n % 4 == 3) else h, beat + BEAT / 2, 0.5, pan=0.25)
        if beat >= 15:
            place(bus, h, beat + BEAT * 0.75, 0.22, pan=-0.25)
        beat += BEAT
    # soft hats before the drop
    t_ = 4.0
    while t_ < DROP - 1.5:
        place(bus, h, t_ + BEAT / 2, 0.22, pan=0.25)
        t_ += BEAT
    return bus, kicks


def sidechain(kicks):
    gain = np.ones(N)
    for kt in kicks:
        i = int(kt * SR)
        t = np.arange(min(int(0.4 * SR), N - i)) / SR
        gain[i: i + len(t)] = np.minimum(gain[i: i + len(t)], 1 - 0.55 * np.exp(-t / 0.11))
    return gain[:, None]


# ---------------------------------------------------------------- sound effects
def make_fx():
    bus = stereo()
    # logo pop + soft boom at the start
    place(bus, boom(3.0) * 0.5, 0.25, 0.7)
    place(bus, pop(1200, 700), 0.35, 0.35)
    # whoosh into every scene (peaks as the new scene appears)
    for start in SCENE_STARTS:
        w = whoosh()
        place(bus, w, start - OVERLAP - 0.55, 0.32 if start != END_HIT else 0.4)
    # typing on the code scene (characters type from 4.6s to 9.4s)
    t_ = 4.6
    while t_ < 9.4:
        place(bus, click(), t_, rng.uniform(0.12, 0.26), pan=rng.uniform(-0.2, 0.2))
        t_ += rng.uniform(0.055, 0.11)
    # build-up into the drop and into the end
    place(bus, riser(2.0), DROP - 2.0, 0.35)
    place(bus, riser(1.6), END_HIT - 1.6, 0.35)
    place(bus, boom(1.6), DROP, 0.55)
    place(bus, boom(4.0), END_HIT, 0.8)
    # pops as items appear
    table = 15.5 - OVERLAP + 0.7
    for i in range(6):
        place(bus, pop(), table + i * 0.14, 0.18, pan=-0.4 + i * 0.16)
    for i in range(3):  # security cards
        place(bus, pop(700, 420), 39.5 - OVERLAP + 0.5 + i * 0.25, 0.2, pan=-0.5 + i * 0.5)
    for i in range(8):  # feature wall tiles
        place(bus, pop(1000 + 40 * i, 640), 44.5 - OVERLAP + 0.6 + i * 0.12, 0.14, pan=-0.6 + (i % 4) * 0.4)
    place(bus, pop(900, 520), 35 - OVERLAP + 1.25, 0.25)  # "English -> Hindi" pill
    place(bus, whoosh(1.6) * 0.8, 30.5 - OVERLAP + 1.0, 0.3)  # light-to-dark wipe
    for i, at in enumerate((50.8, 51.3, 51.7)):  # outro lines
        place(bus, pop(760 + 120 * i, 520), at, 0.14)
    return bus


def reverb(bus, seconds=1.6, mix=0.22):
    t = np.arange(int(seconds * SR)) / SR
    ir = rng.standard_normal((len(t), 2)) * np.exp(-t * 4.0)[:, None]
    ir = filt(ir, "lowpass", 5000)
    ir /= np.sqrt((ir ** 2).sum(axis=0))
    wet = np.stack([fftconvolve(bus[:, c], ir[:, c])[:N] for c in range(2)], axis=1)
    return bus + wet * mix


def main():
    pad, bass, arp = make_pad(), make_bass(), make_arp()
    drums, kicks = make_drums()
    duck = sidechain(kicks)
    music = (pad + arp) * duck
    music = reverb(music, mix=0.35) + bass * duck + drums
    # intro swell, and fade the whole track out at the end
    master_gain = np.clip(T / 1.2, 0.35, 1) * np.clip((LENGTH - T) / 2.5, 0, 1)
    mix = music * master_gain[:, None] + reverb(make_fx(), mix=0.25) * np.clip((LENGTH - T) / 1.0, 0, 1)[:, None]
    mix = filt(mix, "highpass", 28)
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    mix /= np.abs(mix).max() / 0.95

    wav = HERE / "soundtrack.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((mix * 32767).astype("<i2").tobytes())
    print("wrote", wav)

    video, out = HERE / "promo.mp4", HERE / "promo_with_sound.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-af", "loudnorm=I=-15:TP=-1.5:LRA=9", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    out.replace(video)
    print("added sound to", video)


if __name__ == "__main__":
    main()
