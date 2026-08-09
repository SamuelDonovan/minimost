#!/usr/bin/env python3
"""Generate MiniMost's notification and call sounds from scratch.

Every sound the app plays is synthesised here rather than sourced from a sample
library.  That is a licensing decision as much as an aesthetic one: the output
is original work with no third party's terms attached to it, so MiniMost can be
redistributed — commercially or otherwise — without tracking attribution for a
handful of UI blips.  It is also reproducible — the output is byte-identical
across runs — so to retune a sound you edit its recipe function (they are all
registered in :data:`SOUNDS`) and re-run this script, rather than hunting for a
replacement file.

Usage::

    pip install numpy          # not a runtime dependency — only needed here
    python3 tools/gen_sounds.py

Requires ``ffmpeg`` on ``PATH`` for the WAV → MP3 encode.

Design notes
------------
The sounds are additive synthesis: a handful of sine partials per note, each
with its own amplitude and its own decay rate.  Partials that die away faster
than the fundamental are what make the ear hear a struck object rather than a
beep, and the exact ratios are what separate "wooden" from "metallic" — see
:data:`MARIMBA` and :data:`BELL`.

The two ring sounds loop in the browser (``audio.loop = true``), and every MP3
carries around 26 ms of encoder padding that ``<audio loop>`` does not splice
out.  So the loops are built to *start and end in silence*, with the phrase
decayed and faded to zero well before the seam: the gap lands in silence and
cannot be heard.  (A circular convolution would make the tail wrap around
perfectly, but only for a format that loops gaplessly — which MP3 is not.)

Every sound is faded out over its last few tens of milliseconds for the same
reason a note is faded *in*: cutting a waveform off mid-decay is a step change,
and a step change is a click.
"""

import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "minimost" / "static"

# Nothing above this is worth encoding: it is inaudible to most adults and only
# costs bitrate (and risks aliasing for the highest partials of the top notes).
MAX_PARTIAL_HZ = 17000

# ── Timbres ───────────────────────────────────────────────────────────────────
# (frequency ratio, amplitude, decay multiplier) per partial.

# A struck marimba bar is tuned so its overtones land near 4x and 10x the
# fundamental — far from the small-integer harmonics of a string — and they die
# away much faster than it does.  That combination is the "wooden" sound.
MARIMBA = (
    (1.00, 1.00, 1.00),
    (3.95, 0.30, 0.42),
    (9.80, 0.10, 0.22),
)

# A soft mallet on a small bell: a nearly-harmonic stack with a slightly
# stretched top and one inharmonic partial at 2.76x for the metallic shimmer.
BELL = (
    (1.00, 1.00, 1.00),
    (2.00, 0.40, 0.72),
    (2.76, 0.16, 0.45),
    (4.07, 0.11, 0.34),
    (5.93, 0.05, 0.22),
)

# Rounded and flute-like — a fundamental with only a whisper of harmonics above
# it.  Used where the sound has to sit politely under whatever else is going on.
SOFT = (
    (1.00, 1.00, 1.00),
    (2.00, 0.13, 0.60),
    (3.00, 0.04, 0.40),
)


def hz(midi):
    """Return the frequency of a MIDI note number (69 = A4 = 440 Hz)."""
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _partial_phases(count):
    """Deterministic, spread-out starting phases for a note's partials.

    Starting every partial at phase 0 stacks their peaks into one loud sample at
    the attack, which both wastes headroom and adds an audible click.
    """
    return [(i * 2.399963) % (2 * np.pi) for i in range(count)]


def struck(freq, dur, timbre, decay, attack=0.004, amp=1.0):
    """Synthesise one struck note (exponential per-partial decay)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    phases = _partial_phases(len(timbre))
    for (ratio, p_amp, p_decay), phase in zip(timbre, phases):
        if freq * ratio > MAX_PARTIAL_HZ:
            continue
        out += (
            p_amp
            * np.sin(2 * np.pi * freq * ratio * t + phase)
            * np.exp(-t / (decay * p_decay))
        )
    # A raised-cosine attack instead of a hard start: the discontinuity of
    # switching a waveform on is heard as a click.
    a = max(1, int(attack * SR))
    out[:a] *= 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, a))
    return out * amp


def sustained(freq, dur, timbre, fade=0.045, amp=1.0):
    """Synthesise one held note that fades in and out (a ringback-style pulse)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    phases = _partial_phases(len(timbre))
    for (ratio, p_amp, _), phase in zip(timbre, phases):
        if freq * ratio > MAX_PARTIAL_HZ:
            continue
        out += p_amp * np.sin(2 * np.pi * freq * ratio * t + phase)
    f = max(1, int(fade * SR))
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, f))
    out[:f] *= ramp
    out[-f:] *= ramp[::-1]
    return out * amp


def _impulse_response(tail, predelay=0.018, seed=7):
    """A small synthetic room: decaying noise, damped at the top end."""
    rng = np.random.default_rng(seed)
    n = int(tail * SR)
    t = np.arange(n) / SR
    ir = rng.normal(0.0, 1.0, n) * np.exp(-t / (tail / 4.5))
    # Smooth the noise to roll off the highs, so the tail sits behind the note
    # as room rather than in front of it as hiss.
    ir = np.convolve(ir, np.ones(24) / 24, mode="same")
    ir[: int(predelay * SR)] = 0.0
    energy = np.sqrt((ir**2).sum())
    return ir / energy if energy else ir


def reverb(x, wet, tail):
    """Mix a reverb tail into *x*, keeping the buffer length unchanged."""
    ir = _impulse_response(tail)
    y = np.convolve(x, ir)[: len(x)]
    out = np.zeros(len(x))
    out[: len(y)] = y
    return x + wet * out


def mix(dest, sig, at):
    """Add *sig* into *dest* starting at *at* seconds, truncating any overhang."""
    i = int(at * SR)
    end = min(len(dest), i + len(sig))
    if end > i:
        dest[i:end] += sig[: end - i]


def fade_out(x, seconds):
    """Ramp the tail to silence so the file cannot end on a step change."""
    n = min(len(x), max(1, int(seconds * SR)))
    x[-n:] *= 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, n))
    return x


def normalise(x, peak):
    """Scale to an absolute peak, so each sound's loudness is set deliberately."""
    m = np.abs(x).max()
    return x * (peak / m) if m else x


# ── Recipes ───────────────────────────────────────────────────────────────────
# Each builder returns a mono float array in [-1, 1].  The peak each one
# normalises to *is* its playback level — the client plays these files at the
# default volume of 1.0, so the relative loudness of the whole set is decided
# here and nowhere else.  Roughly: the incoming ring has to carry across a room,
# a new message should be noticeable, and the in-call cues should not startle
# anyone who is mid-sentence.


def notification():
    """New message: a quick two-note marimba ding, up a perfect fifth."""
    buf = np.zeros(int(1.10 * SR))
    mix(buf, struck(hz(88), 1.05, MARIMBA, 0.30, amp=0.95), 0.000)  # E6
    mix(buf, struck(hz(95), 0.95, MARIMBA, 0.26, amp=0.72), 0.075)  # B6
    return normalise(fade_out(reverb(buf, wet=0.13, tail=0.40), 0.12), 0.62)


def receiving_call():
    """Incoming call: a warm bell arpeggio, twice per loop.

    The second phrase is placed so its tail has decayed to near nothing by the
    time the fade reaches the end of the buffer — the loop has to seam in
    silence, so the ringing has to be finished before it gets there.
    """
    buf = np.zeros(int(4.20 * SR))
    for start in (0.12, 2.05):
        for i, note in enumerate((69, 73, 76, 81)):  # A4 C#5 E5 A5
            amp = 0.95 if i < 3 else 1.0
            mix(buf, struck(hz(note), 1.5, BELL, 0.38, amp=amp), start + i * 0.13)
    return normalise(fade_out(reverb(buf, wet=0.20, tail=0.6), 0.30), 0.80)


def calling():
    """Outgoing call: a soft double ringback pulse, then a long wait.

    Among the quietest of the set — it repeats in your ear for up to thirty
    seconds while the other end decides whether to pick up, so it only has to
    say "still trying", not demand attention.
    """
    buf = np.zeros(int(4.00 * SR))
    for start in (0.20, 0.80):
        mix(buf, sustained(hz(69), 0.34, SOFT, amp=0.9), start)  # A4
        mix(buf, sustained(hz(76), 0.34, SOFT, amp=0.35), start)  # E5
    return normalise(fade_out(reverb(buf, wet=0.16, tail=0.6), 0.20), 0.34)


def call_accepted():
    """Someone answered: a rising perfect fifth."""
    buf = np.zeros(int(1.20 * SR))
    mix(buf, struck(hz(74), 1.15, BELL, 0.28, amp=0.85), 0.00)  # D5
    mix(buf, struck(hz(81), 1.05, BELL, 0.30, amp=1.00), 0.10)  # A5
    return normalise(fade_out(reverb(buf, wet=0.16, tail=0.45), 0.15), 0.42)


def hang_up():
    """Call over: the same shape as the answer tone, falling instead of rising."""
    buf = np.zeros(int(1.20 * SR))
    mix(buf, struck(hz(81), 1.15, BELL, 0.28, amp=0.85), 0.00)  # A5
    mix(buf, struck(hz(74), 1.05, BELL, 0.32, amp=0.90), 0.10)  # D5
    return normalise(fade_out(reverb(buf, wet=0.16, tail=0.45), 0.15), 0.38)


def left_call():
    """Someone else left: a soft descending blip, quiet enough to ignore."""
    buf = np.zeros(int(0.75 * SR))
    mix(buf, struck(hz(76), 0.70, SOFT, 0.16, amp=0.9), 0.00)  # E5
    mix(buf, struck(hz(71), 0.68, SOFT, 0.18, amp=0.7), 0.06)  # B4
    return normalise(fade_out(reverb(buf, wet=0.11, tail=0.30), 0.12), 0.26)


SOUNDS = {
    "notification": notification,
    "receiving_call": receiving_call,
    "calling": calling,
    "call_accepted": call_accepted,
    "hang_up": hang_up,
    "left_call": left_call,
}


# ── Output ────────────────────────────────────────────────────────────────────


def write_wav(path, samples):
    """Write a mono 16-bit WAV, clipping anything that overshot."""
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())


def encode_mp3(wav_path, mp3_path):
    """Encode to mono 96 kbps MP3 — transparent for sounds this short."""
    # Fixed argv, no shell: nothing here is caller-controlled.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "96k",
            "-ac",
            "1",
            str(mp3_path),
        ],
        check=True,
    )


def main():
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg is required to encode the MP3s but was not found on PATH")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in SOUNDS.items():
        samples = build()
        wav_path = OUT_DIR / f"{name}.wav"
        mp3_path = OUT_DIR / f"{name}.mp3"
        write_wav(wav_path, samples)
        encode_mp3(wav_path, mp3_path)
        wav_path.unlink()
        print(
            f"{mp3_path.name:20s} {len(samples) / SR:4.2f}s "
            f"{mp3_path.stat().st_size / 1024:6.1f} KiB"
        )


if __name__ == "__main__":
    main()
