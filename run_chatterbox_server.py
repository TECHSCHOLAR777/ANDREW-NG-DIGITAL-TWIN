import os
import sys

# ── PERTH WATERMARKER ────────────────────────────────────────────────────────
# This module embeds an inaudible provenance marker in generated speech so the
# audio can later be identified as synthetic. For a system that clones the
# voice of a real, identifiable person, stripping that marker is exactly the
# thing that looks indefensible if anyone examines the repository.
#
# The previous version replaced `perth` with a mock that returned audio
# unchanged, to work around a "'NoneType' object is not callable" crash. We now
# try the real watermarker first and only fall back if it genuinely cannot
# load, and the fallback announces itself loudly instead of failing silently.
_WATERMARKING = False
try:
    import perth  # noqa: F401
    _WATERMARKING = True
except Exception as _exc:  # noqa: BLE001
    from unittest.mock import MagicMock

    class _PassthroughWatermarker:
        """Fallback only. Produces UNWATERMARKED audio."""

        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, wav, *args, **kwargs):
            return wav

        def encode(self, wav, *args, **kwargs):
            return wav

        def apply_watermark(self, wav, *args, **kwargs):
            return wav

    _mock_perth = MagicMock()
    _mock_perth.PerthImplicitWatermarker = _PassthroughWatermarker
    _mock_perth.DummyWatermarker = _PassthroughWatermarker
    sys.modules["perth"] = _mock_perth
    print(
        "\n"
        "WARNING: the 'perth' watermarker could not be loaded "
        f"({type(_exc).__name__}: {_exc}).\n"
        "         Generated speech will NOT carry a synthetic-audio provenance\n"
        "         marker. Install a working 'perth' before using this voice\n"
        "         anywhere public. Run: pip install resemble-perth\n",
        file=sys.stderr,
    )

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Chatterbox Local TTS Server")

# Global model loading (lazy loading or start load)
model = None

def get_model():
    global model
    if model is None:
        try:
            print("Loading Chatterbox TTS model... (This will load from local cache instantly)")
            from chatterbox.tts import ChatterboxTTS
            import torch
            # Detect device
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Using device: {device}")
            model = ChatterboxTTS.from_pretrained(device=device)
            print("Model loaded successfully!")
        except ImportError:
            print("Error: 'chatterbox-tts' package is not installed.")
            print("Please run: pip install chatterbox-tts torchaudio soundfile")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading model: {e}")
            sys.exit(1)
    return model

class SpeechRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "andrew_ng_ref"
    # Speed is applied at SYNTHESIS time, not by resampling finished audio.
    # The frontend used to set audio.playbackRate, which shifts pitch and
    # formants: on a cloned voice that undoes the very thing cloning is for.
    speed: float = 1.0

@app.post("/v1/audio/speech")
async def text_to_speech(request: SpeechRequest):
    if not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text cannot be empty")
    
    # 1. Ensure model is loaded
    tts_model = get_model()
    
    # 2. Check reference voice path
    # Look for the reference voice file in the backend/data/ folder
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ref_voice_path = os.path.join(base_dir, "backend", "data", f"{request.voice}.wav")
    
    if not os.path.exists(ref_voice_path):
        # Fallback to root data folder or current dir
        ref_voice_path = os.path.join(base_dir, "data", f"{request.voice}.wav")
        if not os.path.exists(ref_voice_path):
            raise HTTPException(
                status_code=404, 
                detail=f"Reference audio file '{request.voice}.wav' not found. Please place it in backend/data/."
            )
            
    print(f"Generating speech for text: '{request.input}' using voice: '{ref_voice_path}'")
    
    # 3. Perform generation
    import soundfile as sf
    import tempfile
    
    # Generate wav tensor
    try:
        # Generate cloned audio. cfg_weight controls pacing in Chatterbox, so
        # a slower request becomes slower speech rather than stretched audio.
        gen_kwargs = {"audio_prompt_path": ref_voice_path}
        if abs(request.speed - 1.0) > 0.01:
            try:
                gen_kwargs["cfg_weight"] = max(0.2, min(1.0, 0.5 / request.speed))
                wav = tts_model.generate(request.input, **gen_kwargs)
            except TypeError:
                # Older builds do not accept cfg_weight; speed is then ignored
                # rather than faked by resampling.
                wav = tts_model.generate(request.input, audio_prompt_path=ref_voice_path)
        else:
            wav = tts_model.generate(request.input, **gen_kwargs)
        
        # Save to temp file
        temp_wav_path = os.path.join(tempfile.gettempdir(), f"chatterbox_{os.urandom(4).hex()}.wav")
        # Convert 2D tensor (1, T) to 1D numpy array and save using soundfile
        wav_numpy = wav.squeeze(0).cpu().numpy()
        sf.write(temp_wav_path, wav_numpy, tts_model.sr, format='WAV', subtype='PCM_16')
        
        # Return file response
        return FileResponse(temp_wav_path, media_type="audio/wav", filename="speech.wav")
    except Exception as e:
        print(f"Speech generation failed: {e}")
        raise HTTPException(status_code=505, detail=f"Generation failed: {str(e)}")

if __name__ == "__main__":
    # Load model on startup
    try:
        get_model()
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=5002)
