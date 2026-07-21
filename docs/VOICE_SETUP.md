# Voice Setup

Getting cloned-voice output and hands-free voice conversation working, with no
local GPU.

## How the pieces fit

```
  you speak
      │
      ▼
  browser speech recognition          (Chrome, sends audio to Google)
      │  transcript
      ▼
  frontend  ──POST /api/v1/chat/stream──►  backend
      │                                        │
      │  ◄── SSE: delta + sentence events ─────┘
      │
      │  per completed sentence
      ▼
  frontend ──POST /api/v1/chat/tts──► backend ──► Chatterbox on Kaggle T4
      │                                                    │
      │  ◄──────────── WAV audio ──────────────────────────┘
      ▼
  audio plays while later sentences are still being generated
```

The important property: **synthesis for sentence one starts while sentence
three is still being written.** Without that overlap the floor is 8 to 30
seconds before any audio; with it, roughly two.

---

## Part 1: The cloned voice on Kaggle

### Why not locally

Chatterbox is a neural TTS model. On CPU it takes 10 to 30 seconds per
sentence, so a ten-sentence answer means minutes before the first word. It
needs a GPU, and this machine has none.

Kaggle gives free T4 sessions with about 30 GPU hours a week, which is more
than enough.

### 1.1 Prepare the voice sample

`backend/data/andrew_ng_ref.wav` is gitignored on purpose: a biometric sample
of a real, identifiable person should not sit in a repository that may become
public. See `docs/POSTURE.md`.

What makes a good reference:

- 10 to 30 seconds of clean speech
- One speaker, no music, no overlap
- Normal speaking pace
- WAV, mono, 24kHz or higher

### 1.2 Upload it to Kaggle

1. Kaggle, **Datasets**, **New Dataset**
2. Upload the wav
3. Title: `andrew-ng-voice`
4. **Visibility: Private**
5. Create

### 1.3 Run the notebook

1. **Code**, **New Notebook**
2. **Settings, Accelerator, GPU T4 x2**
3. **Settings, Internet, On.** The tunnel cannot open without it, and this is
   the most common reason the last cell fails.
4. **Add Input**, attach your `andrew-ng-voice` dataset
5. Upload `notebooks/kaggle_tts_server.ipynb`, or paste
   `notebooks/kaggle_tts_server.py` into one cell
6. Run all cells

Cell 5 plays a test clip. **Listen to it before continuing.** If it does not
sound like the reference, the problem is the sample, not the wiring.

The last cell prints:

```
CHATTERBOX_URL=https://something-random.trycloudflare.com/v1/audio/speech
```

### 1.4 Connect it

In your local `.env`:

```bash
CHATTERBOX_URL=https://something-random.trycloudflare.com/v1/audio/speech
```

Restart the backend, then check from your laptop:

```bash
curl https://something-random.trycloudflare.com/health
# {"status":"ok","device":"cuda","watermarking":true,"voice":"andrew_ng_ref"}
```

`"device":"cuda"` is the part that matters. If it says `cpu`, the accelerator
was not enabled and it will be unusably slow.

### 1.5 Verify the whole chain

```bash
python scripts/smoke_test.py
```

Look for `cloned voice ok, device=cuda`.

---

## Part 2: Using voice in the app

### Read aloud

The speaker icon in the chat header. Answers are spoken as they generate,
sentence by sentence.

### Hands-free conversation

The headphones icon beside the message box. This opens voice mode, which cycles
through:

```
listening ──► thinking ──► speaking ──► listening
```

- **listening**: microphone open, waiting for you
- **thinking**: your words were transcribed and sent
- **speaking**: the answer is being spoken as it arrives
- Escape, or the close button, exits

Speech recognition stops while the tutor is speaking, so it does not transcribe
its own voice.

### Requirements

- **Chrome or Edge.** `webkitSpeechRecognition` is not in Firefox or Safari.
- **Microphone permission.**
- **HTTPS, or localhost.** Browsers refuse microphone access on plain HTTP from
  a remote origin, so a deployed frontend must be served over HTTPS.

---

## Part 3: When the voice service is down

A tunnel-backed GPU session is ephemeral: it expires after about nine hours and
the URL changes on restart. This is treated as a normal state, not an error.

The frontend checks `/api/v1/chat/tts/status` on load, and if a synthesis
request returns 502 it switches to the **browser's own speech synthesis** for
the rest of the answer. Generic voice instead of the clone, but voice mode
keeps working end to end.

To restore the cloned voice: re-run the notebook, copy the new URL into `.env`,
restart the backend.

### Avoiding the URL churn

ngrok's free tier includes one static domain, which gives a permanent address:

```python
!pip install -q pyngrok
from pyngrok import ngrok
ngrok.set_auth_token("YOUR_TOKEN")
tunnel = ngrok.connect(PORT, domain="your-static-domain.ngrok-free.app")
print(tunnel.public_url)
```

Then `CHATTERBOX_URL` never changes and only the notebook needs restarting.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Notebook: tunnel fails to start | Internet disabled | Settings, Internet, On |
| `/health` reports `device: cpu` | No accelerator | Settings, Accelerator, GPU T4 x2 |
| Notebook: reference audio not found | Dataset not attached | Add Input, attach `andrew-ng-voice`. The cell lists what it can see |
| Test clip sounds wrong | Poor reference sample | Cleaner audio, one speaker, 10 to 30s |
| Generic voice instead of cloned | TTS unreachable, fallback active | `curl <url>/health`; session probably expired |
| No audio at all | Read aloud off, or browser blocked autoplay | Enable read aloud; click the page once first |
| Microphone does nothing | Not Chrome, or permission denied, or plain HTTP | Use Chrome over HTTPS or localhost, allow the mic |
| Voice mode stuck on "listening" | Recognition heard nothing | Speak closer, check the mic. Escape exits |
| First sentence slow, rest fast | Model warming up | Expected on the first request after idle |
| Audio choppy between sentences | Synthesis slower than playback | Lower `RETRIEVAL_NEIGHBOR_WINDOW` for shorter answers, or accept the gap |

---

## Deployment

**Do not point a public deployment at a Kaggle tunnel.** Sessions expire, the
URL rotates, and it is a shared free resource.

`docs/POSTURE.md` also commits to not serving the cloned voice publicly: it is
a clone of a real person's voice, and a local demo is defensible where a public
service is not.

For a public deployment, pick one:

1. **Browser speech synthesis only.** Leave `CHATTERBOX_URL` unset. Voice works
   with a generic voice, costs nothing, needs no infrastructure. This is the
   recommended default.
2. **A hosted TTS provider** with a non-cloned voice. Cartesia and ElevenLabs
   both stream with low time-to-first-byte. Point `CHATTERBOX_URL` at an
   adapter matching the same request contract.
3. **Your own GPU host** running `run_chatterbox_server.py`. Full control,
   ongoing cost, and the likeness question in POSTURE.md still applies.

The cloned voice stays a local capability, shown in a recorded demo rather than
served from a URL.
