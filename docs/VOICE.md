# CLAP voice

## Reference recording

CLAP's voice identity comes from the reference recording
`voice_preview_serafina_-_sensual_temptress.mp3` (3.66 s, mono MP3, 44.1 kHz,
320 kbps). The recording itself is **not** stored in this repository: it is the
voice creator's material. The file name is the format of an ElevenLabs Voice
Library preview download, identifying the voice **"Serafina – Sensual Temptress"**.

Acoustic profile, measured from the recording:

| Property | Measurement | Character |
|---|---|---|
| Pitch | median F0 ≈ 182 Hz (p10–p90: 167–246 Hz) | lower-register female voice |
| Intonation | F0 std ≈ 32 Hz | expressive, gliding contours |
| Timbre | median spectral centroid ≈ 1.0 kHz | warm, dark, soft |
| Pacing | ≈ 3 syllables/s, no pauses ≥ 250 ms | slow, smooth, legato |
| Dynamics | ≈ 13 dB (p90–p10) | intimate, even energy |

Accent and exact wording could not be measured in the build environment, because no
speech-recognition model could be downloaded there. The ElevenLabs Voice Library page
for the voice lists its accent and use case (`python -m voice find serafina` prints them).

## Provider: ElevenLabs (`voice/providers/elevenlabs.py`)

CLAP speaks with that exact library voice through the ElevenLabs text-to-speech API.
It does not clone the preview.

- **Rights.** Voice Library voices are published by their creators for use through
  ElevenLabs, subject to ElevenLabs' terms and any restrictions the creator sets.
  Cloning the preview recording into a new voice would copy another person's voice
  without their consent, so CLAP does not do that. If you own a recording of a voice
  you have the rights to, you can create your own ElevenLabs voice from it and put
  its ID in `CLAP_TTS_VOICE_ID`.
- **No silent fallback.** When the voice is not configured or synthesis fails, CLAP
  shows and logs "Voice output is currently unavailable." It never quietly switches
  to another voice. The macOS `say` provider exists only as an explicit opt-in
  (`CLAP_TTS_PROVIDER=macos`) and is labelled "approximation" in the HUD.

## Setup

1. Create an ElevenLabs account and API key (elevenlabs.io → Profile → API keys).
2. In `.env`:
   ```env
   CLAP_TTS_API_KEY=your-elevenlabs-key
   ```
3. Find the voice and add it to your account:
   ```bash
   python -m voice find serafina
   python -m voice add <public_owner_id> <voice_id>      # prints CLAP_TTS_VOICE_ID=...
   ```
   Or in the ElevenLabs web app: Voice Library → search "Serafina" → Add to My
   Voices → copy the voice ID.
4. In `.env`:
   ```env
   CLAP_TTS_VOICE_ID=the-voice-id
   # optional: lower latency, slightly lower fidelity
   # CLAP_TTS_MODEL_ID=eleven_flash_v2_5
   ```
5. Test: `python -m voice test "Hello. I am CLAP."`

## Environment variables

| Variable | Used for |
|---|---|
| `CLAP_TTS_API_KEY` | ElevenLabs API key (`xi-api-key` header). Server-side only; never sent to the browser. |
| `CLAP_TTS_VOICE_ID` | Voice to synthesise with. For `macos`, a macOS voice name. |
| `CLAP_TTS_MODEL_ID` | Optional ElevenLabs model (default `eleven_multilingual_v2`). |
| `CLAP_TTS_PROVIDER` | Optional: `elevenlabs` (default when the key and voice are set), `macos`, `none`. |

## How speech is produced

- `voice.speak(text)` strips markdown, splits long replies into sentence chunks,
  synthesises the next chunk while the current one plays, and plays through `afplay`
  (native on macOS).
- Short fixed phrases ("Yes?", "CLAP online.") are cached in `.cache/tts/`, so the
  wake acknowledgement starts instantly.
- The HUD shows SPEAKING only while audio is actually playing. The microphone ignores
  input during playback (plus a 0.35 s tail), so CLAP never wakes itself or
  transcribes its own voice.

## Verification status

- The request format, error handling, Voice Library search/add, caching, chunking and
  SPEAKING state were tested against a local mock of the ElevenLabs API
  (`tests/test_voice.py`, plus a live HUD run).
- Live ElevenLabs synthesis and real audio playback were **not** tested in the build
  environment, which could not reach ElevenLabs and has no audio device. Run
  `python -m voice test` on your Mac to confirm.
