# Training the "ZEMARK" wake word (Mac Apple Silicon)

This guide sets up a **custom, always-on wake word** — the made-up word
**ZEMARK** — so the assistant listens locally on raw audio frames instead of
running full speech-to-text on everything you say. You only need to do this once.

ZEMARK ships with three wake backends (see `zemark/config.py` → `WakeConfig`):

| Backend         | `ZEMARK_WAKE_BACKEND` | Setup            | Cost           | Notes |
| --------------- | --------------------- | ---------------- | -------------- | ----- |
| STT phrase      | `stt_phrase` (default)| none             | free           | Works day one. Runs inside the STT pipeline; no `.ppn`/`.onnx`, no tuning. |
| Porcupine       | `porcupine`           | 5 min in console | free (personal)| Fastest, lowest CPU. Needs a `.ppn` + access key. |
| openWakeWord    | `openwakeword`        | ~1 h in Colab    | fully free/local | Trains a `.onnx` from synthetic speech. No account, no key. |

The default `stt_phrase` backend already recognizes "zemark" (and the aliases in
`ZEMARK_WAKE_ALIASES`) with **zero setup** — if that is good enough for you, you
can stop here. The two frame backends below are for lower latency and lower CPU
usage from a dedicated wake model.

---

## 0. Install the wake extras

From the `jarvis/` project root, in your virtualenv:

```bash
pip install -e ".[wake]"
```

This pulls in `pvporcupine`, `openwakeword`, `onnxruntime`, `sounddevice`, and
`numpy`. On **Apple Silicon** always use the **onnx** runtime for openWakeWord —
`tflite-runtime` has no reliable arm64 wheel, and `OpenWakeWordDetector` in
`zemark/wake/frame.py` already forces `inference_framework="onnx"` for exactly
this reason.

Create the models directory (env can override it via `ZEMARK_MODELS_DIR`; default
is `jarvis/models/`):

```bash
mkdir -p models
```

---

## A) Picovoice Porcupine — the fast path

Porcupine is an on-device keyword spotter. You type your word in a web console,
it trains in seconds, and you download a small platform-specific `.ppn` file.

### A.1 Create a free account and generate the model

1. Sign up at the **Picovoice Console**: <https://console.picovoice.ai/>.
2. Copy your **AccessKey** from the console home page — this is your
   `PICOVOICE_ACCESS_KEY`.
3. Open **Porcupine → Wake Word**.
4. In the keyword box, type **`zemark`** (lower-case is fine) and pick a language
   (English). If the phrase is accepted, training runs in a few seconds.
5. **Select the platform: `macOS (arm64)`** — Porcupine models are
   platform-specific, and an Intel/`x86_64` or Linux `.ppn` will **not** load on
   an Apple-Silicon Mac.
6. Click **Download**. You get a ZIP; inside is a file like
   `zemark_en_mac_v3_0_0.ppn`.

> **Free-tier terms.** Custom keywords from the Console are licensed for
> **non-commercial, personal, and evaluation use only**, and console-trained
> models run on Linux (x86_64), macOS, and Windows. The AccessKey is free but
> may require periodic re-validation. Review the current terms in the console
> before any commercial use. See the tutorial:
> <https://picovoice.ai/blog/console-tutorial-custom-wake-word/> and the docs:
> <https://picovoice.ai/docs/quick-start/console-porcupine/>.

### A.2 Install the model and set the environment

Put the `.ppn` where the config expects it:

```bash
cp ~/Downloads/zemark_en_mac_v3_0_0.ppn models/zemark_mac.ppn
```

Then set (e.g. in `jarvis/.env`, which `config.py` auto-loads):

```bash
ZEMARK_WAKE_BACKEND=porcupine
PICOVOICE_ACCESS_KEY=your-access-key-from-the-console
ZEMARK_PORCUPINE_PPN=models/zemark_mac.ppn
```

These map to `WakeConfig.porcupine_access_key` and
`WakeConfig.porcupine_model_path`. The path may be relative to `jarvis/` or
absolute. Skip to [Verify](#verify) below.

---

## B) openWakeWord — fully local and free

openWakeWord trains a small neural detector from **synthetic speech** (generated
with Piper TTS), so you never record yourself and never need an account or key.
Training runs **in Google Colab on Linux** — **not** on your Mac (the Piper/data
pipeline targets Linux GPU). The Mac only ever runs the exported `.onnx`.

### B.1 Train in the official Colab notebook

1. Open the official notebook from the openWakeWord repo,
   `notebooks/automatic_model_training.ipynb`, in **Google Colab**:
   <https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb>.
   (In Colab: *File → Open notebook → GitHub →* paste `dscripka/openWakeWord`.)
2. Set the runtime to a **T4 GPU** (*Runtime → Change runtime type → T4 GPU*).
3. In the config cell, set the target phrase and model name:

   ```yaml
   target_phrase: "zemark"
   model_name: "ZEMARK"
   ```

   (Newer notebook revisions use the `TARGET_PHRASE` / `MODEL_NAME` form-field
   variables — set both to `zemark` / `ZEMARK` accordingly. You can add a second
   pronunciation variant, e.g. `"ze mark"`, to improve recall.)
4. **Run all cells** and walk away. It generates synthetic positive/negative
   clips with Piper, trains, and validates. On a free T4 this takes roughly
   10–90 minutes depending on the notebook edition.
5. The final cell **exports and auto-downloads `ZEMARK.onnx`** (and a `.tflite`
   for Home Assistant users — you don't need it here).

Reference: the training utility and config are documented in the repo README —
<https://github.com/dscripka/openWakeWord>.

### B.2 Install the model and set the environment

```bash
cp ~/Downloads/ZEMARK.onnx models/ZEMARK.onnx
```

Then set:

```bash
ZEMARK_WAKE_BACKEND=openwakeword
ZEMARK_OWW_ONNX=models/ZEMARK.onnx
```

This maps to `WakeConfig.openwakeword_model_path`. On macOS arm64 leave the
runtime as **onnx** (the default in `frame.py`) — do not try to switch to tflite.

---

## Verify

Use the bundled tester. It loads your config, builds the exact same backend the
app uses (`build_wake(cfg.wake)`), opens the mic at the detector's native sample
rate, and prints a live trigger line plus a running max score:

```bash
python scripts/test_wake.py
```

Speak **"ZEMARK"** a few times from a normal distance. You should see:

```
[TRIGGER] wake word detected!   (max score so far: 0.83)
```

Ctrl+C to stop. If the backend is `stt_phrase`, the script tells you there is
nothing to tune (the phrase matcher runs inside the STT pipeline) and exits.

---

## Threshold tuning

Both frame backends compare a per-frame confidence against
`ZEMARK_WAKE_THRESHOLD` (`WakeConfig.threshold`, default `0.5`). For Porcupine
this is passed as `sensitivity`; for openWakeWord it is the score cutoff.

Watch the **running max score** the tester prints:

- **Missing your voice (false negatives)?** Note the max score you reach when you
  say "zemark" and set the threshold a bit below it. Lower = more sensitive.

  ```bash
  ZEMARK_WAKE_THRESHOLD=0.35
  ```

- **Triggering on other speech (false positives)?** Raise it toward the max score
  that random speech produces.

  ```bash
  ZEMARK_WAKE_THRESHOLD=0.6
  ```

Good starting points: **Porcupine ~0.5–0.6**, **openWakeWord ~0.4–0.5**. Re-run
`scripts/test_wake.py` after each change (it re-reads the env). The
`ZEMARK_WAKE_REFRACTORY` seconds (default `2.0`) debounce so one utterance fires
once — increase it if a single "zemark" double-triggers.

---

## Apple-Silicon troubleshooting

- **16 kHz mono audio requirement.** Both detectors expect **16 kHz, mono,
  int16** PCM. Porcupine also fixes the block size to its `frame_length`;
  openWakeWord expects **1280 samples (80 ms) @ 16 kHz**. `test_wake.py` reads
  `detector.sample_rate` / `detector.frame_length` and configures `sounddevice`
  to match, so let it drive the capture rather than forcing 44.1/48 kHz.
- **Microphone permissions.** macOS gates the mic per-app. Grant access to your
  **terminal / IDE** under *System Settings → Privacy & Security → Microphone*,
  then fully restart that app. A silent all-zero signal (max score stuck at
  `0.00`) is almost always a denied permission.
- **`PortAudioError` / no input device.** `sounddevice` needs PortAudio:
  `brew install portaudio` then reinstall: `pip install --force-reinstall sounddevice`.
  List devices with `python -c "import sounddevice as sd; print(sd.query_devices())"`.
- **onnx vs tflite.** Use **onnx** on Apple Silicon. `tflite-runtime` has no
  reliable arm64 wheel; `OpenWakeWordDetector` already pins
  `inference_framework="onnx"`. If you see a tflite import error, you are on the
  wrong runtime — reinstall `onnxruntime` and keep `ZEMARK_OWW_ONNX` pointing at
  the `.onnx` (not a `.tflite`).
- **Porcupine `.ppn` fails to load.** Almost always the wrong platform — re-download
  the **macOS (arm64)** build from the console. Also confirm `PICOVOICE_ACCESS_KEY`
  is set and current.
- **Wrong model directory.** Paths in `ZEMARK_PORCUPINE_PPN` / `ZEMARK_OWW_ONNX`
  are resolved from wherever you launch Python (relative) or as absolute paths.
  Run the tester from the `jarvis/` root, or use absolute paths.

---

## Sources

- Picovoice — Creating a Custom Wake Word with Porcupine:
  <https://picovoice.ai/blog/console-tutorial-custom-wake-word/>
- Picovoice Console (Porcupine) docs:
  <https://picovoice.ai/docs/quick-start/console-porcupine/>
- Picovoice Porcupine repo (platform support):
  <https://github.com/Picovoice/porcupine>
- openWakeWord repo & training utility:
  <https://github.com/dscripka/openWakeWord>
- openWakeWord `automatic_model_training.ipynb`:
  <https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb>
