"""
ElevenLabs text-to-speech — CLAP's reference voice.

The CLAP reference recording is an ElevenLabs Voice Library preview
("Serafina – Sensual Temptress"). Library voices are shared by their creators
for use through ElevenLabs, so CLAP speaks with that voice directly via its
voice ID rather than cloning the preview recording.

Configuration (.env):
  CLAP_TTS_API_KEY   ElevenLabs API key
  CLAP_TTS_VOICE_ID  voice ID of the voice in your ElevenLabs account
  CLAP_TTS_MODEL_ID  optional, default eleven_multilingual_v2
                     (eleven_flash_v2_5 trades some fidelity for lower latency)

Find/add the voice: `python -m voice find serafina` then `python -m voice add ...`.
"""

from __future__ import annotations

import requests

from voice.providers.base import TTSError, TTSProvider

API_BASE = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"


def _error_detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("status") or detail)[:200]
    return str(detail)[:200]


class ElevenLabsProvider(TTSProvider):
    name = "elevenlabs"
    audio_ext = "mp3"
    reference_voice = True

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "",
        base_url: str = API_BASE,
        timeout: float = 30.0,
    ) -> None:
        if not api_key or not voice_id:
            raise ValueError("ElevenLabs needs an API key and a voice ID")
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    @property
    def voice_label(self) -> str:
        return f"ElevenLabs voice {self.voice_id} ({self.model_id})"

    @property
    def cache_key(self) -> str:
        return f"{self.name}:{self.voice_id}:{self.model_id}"

    def _headers(self, accept: str = "application/json") -> dict:
        return {"xi-api-key": self.api_key, "Accept": accept}

    def synthesize(self, text: str, out_path: str) -> None:
        url = f"{self.base_url}/v1/text-to-speech/{self.voice_id}"
        try:
            resp = self._session.post(
                url,
                headers=self._headers("audio/mpeg"),
                json={"text": text, "model_id": self.model_id},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TTSError("Voice output is currently unavailable.", f"ElevenLabs unreachable: {exc}") from exc

        if resp.status_code != 200:
            detail = f"ElevenLabs HTTP {resp.status_code}: {_error_detail(resp)}"
            if resp.status_code == 401:
                raise TTSError("Voice output is currently unavailable. The ElevenLabs key was rejected.", detail)
            if resp.status_code == 404:
                raise TTSError("Voice output is currently unavailable. The CLAP voice was not found.", detail)
            if resp.status_code == 429:
                raise TTSError("Voice output is busy. Try again in a moment.", detail)
            raise TTSError("Voice output is currently unavailable.", detail)

        if not resp.content or "audio" not in resp.headers.get("Content-Type", "audio/mpeg"):
            raise TTSError("Voice output is currently unavailable.", "ElevenLabs returned no audio")
        with open(out_path, "wb") as fh:
            fh.write(resp.content)

    # ── Voice Library helpers (used by `python -m voice`) ─────────────────

    def search_library(self, query: str, page_size: int = 20) -> list[dict]:
        resp = self._session.get(
            f"{self.base_url}/v1/shared-voices",
            headers=self._headers(),
            params={"search": query, "page_size": page_size},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise TTSError("Voice Library search failed.", f"HTTP {resp.status_code}: {_error_detail(resp)}")
        return resp.json().get("voices", [])

    def add_library_voice(self, public_owner_id: str, voice_id: str, new_name: str) -> str:
        resp = self._session.post(
            f"{self.base_url}/v1/voices/add/{public_owner_id}/{voice_id}",
            headers=self._headers(),
            json={"new_name": new_name},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise TTSError("Adding the voice failed.", f"HTTP {resp.status_code}: {_error_detail(resp)}")
        return resp.json().get("voice_id", voice_id)
