#!/usr/bin/env python3
"""
Voice diagnostic — run this to see what your mic picks up and what Whisper hears.
Usage: python debug_voice.py
"""
import sys
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed"); sys.exit(1)

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("ERROR: faster-whisper not installed"); sys.exit(1)

from tools.voice_input import wake_word_in

SAMPLE_RATE = 16_000
DURATION    = 3.0

print("\n── Microphone devices ─────────────────────────────────────────")
devices = sd.query_devices()
default_in = sd.query_devices(kind='input')
print(f"Default input : {default_in['name']}")
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        marker = " ◄ DEFAULT" if d['name'] == default_in['name'] else ""
        print(f"  [{i}] {d['name']}{marker}")

print("\n── Loading Whisper (base.en) ───────────────────────────────────")
model = WhisperModel("base.en", device="cpu", compute_type="int8")
print("Whisper ready.")

print("\n── 5 recording tests ──────────────────────────────────────────")
print("Say 'CLAP' (or 'Hey CLAP') clearly each time when prompted.\n")

for i in range(5):
    input(f"  Test {i+1}/5 — press Enter then speak...")
    audio = sd.rec(int(SAMPLE_RATE * DURATION), samplerate=SAMPLE_RATE,
                   channels=1, dtype="float32")
    sd.wait()
    chunk = audio[:, 0]

    rms = float(np.sqrt(np.mean(chunk ** 2)))
    peak = float(np.max(np.abs(chunk)))

    segments, _ = model.transcribe(chunk, beam_size=5, language="en", vad_filter=False)
    text = " ".join(s.text.strip() for s in segments).strip()

    detected = wake_word_in(text)

    print(f"    RMS={rms:.4f}  Peak={peak:.4f}  Transcript='{text}'  Wake={'✓ YES' if detected else '✗ NO'}")

print("\n── Threshold diagnosis ────────────────────────────────────────")
print("ENERGY_MIN in tools/voice_input.py: 0.005 (wake scan skips quieter audio)")
print("If your RMS values above are < 0.005, the mic is too quiet — lower ENERGY_MIN.")
print("If Whisper never transcribes 'CLAP', try 'Hey CLAP' and check System Settings → Privacy → Microphone.\n")
