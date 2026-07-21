"""
notebooks/kaggle_tts_server.py
─────────────────────────────────────────────────────────────────────────────
Run the cloned-voice TTS server on a Kaggle GPU and expose it to your local
machine.

WHY THIS EXISTS
───────────────
Chatterbox is a neural TTS model. On CPU it takes roughly 10 to 30 seconds per
sentence, which makes the voice feature unusable: a ten sentence answer would
take minutes before the first word is heard. It needs a GPU.

With no local GPU, the model has to run somewhere that has one. Kaggle gives
free T4 sessions, so the split is:

    your laptop            Kaggle notebook (T4 GPU)
    ───────────            ────────────────────────
    Next.js frontend
    FastAPI backend  ──────►  Chatterbox TTS
    Postgres (Supabase)       exposed via a tunnel

The backend already reads CHATTERBOX_URL from the environment, so pointing it
at the tunnel is a one line change with no code edits.

HOW TO USE
──────────
1. Create a new Kaggle notebook. Settings, Accelerator, choose GPU T4 x2.
   Settings, Internet, must be ON, or the tunnel cannot be created.

2. Upload backend/data/andrew_ng_ref.wav as a Kaggle Dataset, or set
   REFERENCE_AUDIO_URL below to somewhere it can be downloaded from.

3. Paste this entire file into one notebook cell and run it.

4. It prints a public https URL. Put that in your local .env:

       CHATTERBOX_URL=https://<the-printed-url>/v1/audio/speech

5. Restart the backend. Voice now uses the cloned voice on a real GPU.

WHAT TO EXPECT
──────────────
* First run downloads the model, a few minutes.
* Synthesis on a T4 is roughly 1 to 3 seconds per sentence, so with the
  sentence streaming already in place the first audio arrives in a couple of
  seconds rather than tens.
* Kaggle sessions expire after about 9 hours and the tunnel URL changes each
  time you restart. This is a development and demo setup, not production.
* The notebook tab must stay open. Kaggle stops idle sessions.
"""

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
# Where the reference voice sample lives inside the Kaggle session.
# If uploaded as a dataset named "andrew-ng-voice", this is the path.
REFERENCE_AUDIO_PATH = "/kaggle/input/andrew-ng-voice/andrew_ng_ref.wav"

# Optional: download the reference instead of uploading it as a dataset.
REFERENCE_AUDIO_URL = ""

PORT = 5002

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────
import os
import subprocess
import sys
import threading
import time

# Do NOT let pip upgrade torch. Kaggle ships 2.6.0, which is what
# chatterbox-tts pins; upgrading it breaks transformers with a confusing
# "Could not import module 'LlamaModel'". Constraints pin the three packages
# that matter and let pip resolve the rest.
print("Installing dependencies. Takes a few minutes on first run.")
with open("/tmp/constraints.txt", "w") as f:
    f.write(
        "torch==2.6.0\n"
        "torchaudio==2.6.0\n"
        "numpy<2.0.0\n"
        "safetensors==0.5.3\n"
    )
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-c", "/tmp/constraints.txt",
     "chatterbox-tts", "fastapi", "uvicorn", "soundfile", "nest_asyncio"],
    check=False,
)

# Download cloudflared for the tunnel. No account or token required for a
# quick tunnel, which keeps this copy-paste friendly.
if not os.path.exists("cloudflared"):
    print("Fetching cloudflared...")
    subprocess.run(
        ["wget", "-q", "-O", "cloudflared",
         "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"],
        check=False,
    )
    subprocess.run(["chmod", "+x", "cloudflared"], check=False)

# ─────────────────────────────────────────────────────────────────────────────
# WATERMARKER
# Kept enabled deliberately. It embeds an inaudible provenance marker so the
# audio can later be identified as synthetic. For cloned speech of a real,
# identifiable person, stripping that is indefensible. See docs/POSTURE.md.
# ─────────────────────────────────────────────────────────────────────────────
WATERMARKING = True
try:
    import perth  # noqa: F401
except Exception as exc:  # noqa: BLE001
    WATERMARKING = False
    from unittest.mock import MagicMock

    class _Passthrough:
        def __init__(self, *a, **k): pass
        def __call__(self, wav, *a, **k): return wav
        def encode(self, wav, *a, **k): return wav
        def apply_watermark(self, wav, *a, **k): return wav

    _mock = MagicMock()
    _mock.PerthImplicitWatermarker = _Passthrough
    _mock.DummyWatermarker = _Passthrough
    sys.modules["perth"] = _mock
    print(f"\nWARNING: perth watermarker unavailable ({exc}).")
    print("Generated audio will NOT carry a synthetic-speech marker.\n")

# ─────────────────────────────────────────────────────────────────────────────
# REFERENCE AUDIO
# ─────────────────────────────────────────────────────────────────────────────
if REFERENCE_AUDIO_URL and not os.path.exists(REFERENCE_AUDIO_PATH):
    REFERENCE_AUDIO_PATH = "/kaggle/working/reference.wav"
    subprocess.run(["wget", "-q", "-O", REFERENCE_AUDIO_PATH, REFERENCE_AUDIO_URL], check=False)

if not os.path.exists(REFERENCE_AUDIO_PATH):
    raise SystemExit(
        f"Reference audio not found at {REFERENCE_AUDIO_PATH}.\n"
        "Upload backend/data/andrew_ng_ref.wav as a Kaggle Dataset, or set "
        "REFERENCE_AUDIO_URL at the top of this script."
    )

# ─────────────────────────────────────────────────────────────────────────────
# MODEL
# ─────────────────────────────────────────────────────────────────────────────
import torch
from chatterbox.tts import ChatterboxTTS

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE == "cpu":
    print("\nWARNING: no GPU detected. Check Settings, Accelerator, GPU T4.")
    print("On CPU this will be too slow to be usable.\n")
else:
    print(f"GPU: {torch.cuda.get_device_name(0)}")

print("Loading Chatterbox...")
MODEL = ChatterboxTTS.from_pretrained(device=DEVICE)
print("Model ready.")

# ─────────────────────────────────────────────────────────────────────────────
# SERVER
# Same request and response contract as run_chatterbox_server.py, so the
# backend cannot tell the difference between local and remote.
# ─────────────────────────────────────────────────────────────────────────────
import io
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="Chatterbox TTS (Kaggle GPU)")


class SpeechRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "andrew_ng_ref"
    speed: float = 1.0


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": DEVICE,
        "watermarking": WATERMARKING,
        "voice": "andrew_ng_ref",
    }


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Input text cannot be empty")

    started = time.time()
    try:
        kwargs = {"audio_prompt_path": REFERENCE_AUDIO_PATH}
        # Speed is applied at synthesis, never by resampling finished audio,
        # which would shift pitch and formants and undo the point of cloning.
        if abs(req.speed - 1.0) > 0.01:
            try:
                kwargs["cfg_weight"] = max(0.2, min(1.0, 0.5 / req.speed))
                wav = MODEL.generate(text, **kwargs)
            except TypeError:
                wav = MODEL.generate(text, audio_prompt_path=REFERENCE_AUDIO_PATH)
        else:
            wav = MODEL.generate(text, **kwargs)

        buffer = io.BytesIO()
        sf.write(buffer, wav.squeeze(0).cpu().numpy(), MODEL.sr,
                 format="WAV", subtype="PCM_16")
        buffer.seek(0)
        print(f"  synthesised {len(text)} chars in {time.time() - started:.1f}s")
        return Response(content=buffer.read(), media_type="audio/wav")
    except Exception as exc:  # noqa: BLE001
        print(f"  generation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────
import nest_asyncio
import uvicorn

nest_asyncio.apply()


def _serve():
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


threading.Thread(target=_serve, daemon=True).start()
time.sleep(4)

print("\nOpening tunnel...")
tunnel = subprocess.Popen(
    ["./cloudflared", "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
)

public_url = None
for line in tunnel.stdout:
    if "trycloudflare.com" in line:
        for token in line.split():
            if token.startswith("https://") and "trycloudflare" in token:
                public_url = token.strip()
                break
    if public_url:
        break

if not public_url:
    raise SystemExit("Tunnel failed to start. Check that Internet is enabled in notebook settings.")

print("\n" + "=" * 68)
print("TTS SERVER READY")
print("=" * 68)
print(f"\nDevice:       {DEVICE}")
print(f"Watermarking: {'enabled' if WATERMARKING else 'DISABLED'}")
print(f"\nPut this in your local .env:\n")
print(f"    CHATTERBOX_URL={public_url}/v1/audio/speech")
print(f"\nThen restart the backend. Verify with:\n")
print(f"    curl {public_url}/health")
print("\nKeep this notebook tab open. Kaggle stops idle sessions, and the")
print("URL changes every time this cell is re-run.")
print("=" * 68 + "\n")

# Hold the cell open so the session stays alive.
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    tunnel.terminate()
    print("Stopped.")
