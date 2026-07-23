#!/usr/bin/env python3
"""Live microphone tester for the ZEMARK wake word.

Loads the current config, builds whatever wake backend is configured
(``ZEMARK_WAKE_BACKEND``), and — for the frame-based detectors (Porcupine /
openWakeWord) — streams microphone audio into ``.process()`` and prints a live
trigger message plus a running max score so you can tune
``ZEMARK_WAKE_THRESHOLD``.

If the configured backend is the STT phrase matcher (a ``PhraseMatcher``), there
is nothing to tune here — it runs inside the STT pipeline, not on raw frames —
so the script says so and exits.

Usage
-----
    python scripts/test_wake.py

Say "ZEMARK" a few times. Ctrl+C to stop. See ``docs/wake-training.md`` for the
full setup and threshold-tuning walkthrough.
"""

from __future__ import annotations

import sys

# sounddevice + numpy are hard requirements for this tester; fail with a clear
# message rather than a raw ImportError deep in the stack.
try:
    import numpy as np
    import sounddevice as sd
except Exception as exc:  # pragma: no cover - environment guard
    sys.stderr.write(
        "test_wake.py needs 'sounddevice' and 'numpy'.\n"
        "Install the wake extras from the jarvis/ root:\n"
        '    pip install -e ".[wake]"\n'
        f"(import error: {exc})\n"
    )
    raise SystemExit(1)


def main() -> int:
    # Lazy imports so a bad env doesn't obscure the missing-deps message above.
    from zemark.config import load_config
    from zemark.wake.factory import build_wake

    cfg = load_config()
    backend = cfg.wake.backend

    try:
        detector = build_wake(cfg.wake)
    except Exception as exc:
        sys.stderr.write(f"Could not build wake backend {backend!r}: {exc}\n")
        return 1

    # Frame detectors expose sample_rate + frame_length + process(); the phrase
    # matcher does not. Detect by capability.
    is_frame_detector = (
        hasattr(detector, "sample_rate")
        and hasattr(detector, "frame_length")
        and hasattr(detector, "process")
    )

    if not is_frame_detector:
        print(
            f"Wake backend is '{backend}' (phrase matcher) — nothing to tune here.\n"
            "The STT phrase backend runs inside the speech-to-text pipeline, not on\n"
            "raw audio frames, so there is no microphone score to tune. It already\n"
            f"recognizes '{cfg.wake.word}' and its aliases with no setup.\n\n"
            "To tune a frame detector instead, set ZEMARK_WAKE_BACKEND=porcupine or\n"
            "openwakeword (see docs/wake-training.md) and re-run this script."
        )
        # PhraseMatcher may or may not have close(); be defensive.
        _maybe_close(detector)
        return 0

    sample_rate = int(detector.sample_rate)
    frame_length = int(detector.frame_length)

    print(
        f"Wake backend: {backend}\n"
        f"Sample rate:  {sample_rate} Hz (mono, int16)\n"
        f"Frame size:   {frame_length} samples "
        f"({frame_length / sample_rate * 1000:.0f} ms)\n"
        f"Threshold:    {cfg.wake.threshold} (ZEMARK_WAKE_THRESHOLD)\n\n"
        "Listening... say \"ZEMARK\". Ctrl+C to stop.\n"
    )

    running_max = 0.0
    triggers = 0

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_length,
        ) as stream:
            while True:
                data, overflowed = stream.read(frame_length)
                if overflowed:
                    # Non-fatal; just note it once in a while.
                    pass
                # data shape is (frame_length, 1) int16 -> flatten to mono 1-D.
                frame = np.asarray(data, dtype=np.int16).reshape(-1)

                # A running loudness proxy so the operator gets feedback even
                # when detectors don't expose a raw score. Normalized RMS in
                # [0, 1] roughly tracks "how strong is the input right now".
                if frame.size:
                    rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
                    level = min(rms / 32768.0 * 4.0, 1.0)
                    running_max = max(running_max, level)

                if detector.process(frame):
                    triggers += 1
                    print(
                        f"[TRIGGER] wake word detected!   "
                        f"(#{triggers}, input level max so far: {running_max:.2f})"
                    )
                    print(
                        "  -> If this fired when you said ZEMARK, great. If it fired on\n"
                        "     other speech, raise ZEMARK_WAKE_THRESHOLD; if it missed you,\n"
                        "     lower it. See docs/wake-training.md."
                    )
    except KeyboardInterrupt:
        print(
            f"\nStopped. {triggers} trigger(s) this session; "
            f"peak input level {running_max:.2f}."
        )
    except Exception as exc:
        sys.stderr.write(f"\nAudio error: {exc}\n")
        if "PortAudio" in str(exc) or "device" in str(exc).lower():
            sys.stderr.write(
                "Check macOS mic permissions (System Settings -> Privacy & Security\n"
                "-> Microphone) and that PortAudio is installed (brew install portaudio).\n"
            )
        _maybe_close(detector)
        return 1

    _maybe_close(detector)
    return 0


def _maybe_close(detector) -> None:
    close = getattr(detector, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
