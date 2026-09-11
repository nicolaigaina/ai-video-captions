"""Caption job processing pipeline.

Runs the full video captioning workflow:
  1. Probe video for dimensions and duration (ffprobe)
  2. Transcribe audio with word-level timestamps (faster-whisper)
  3. Generate ASS subtitle file
  4. Burn subtitles into video (ffmpeg)
  5. Clean up temp files and mark job completed
"""

import json
import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

# Default Whisper model size; override via env var to trade speed vs accuracy.
# "base" often mis-decodes Hindi audio into Urdu script; "small" doesn't.
_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")


# ---------------------------------------------------------------------------
# Low-level helpers (each independently mockable)
# ---------------------------------------------------------------------------

def probe_video(video_path: str) -> tuple[int, int, float]:
    """Return (width, height, duration_seconds) for *video_path* via ffprobe.

    Raises:
        RuntimeError: if ffprobe is not installed or returns a non-zero exit code.
        ValueError: if the probe output cannot be parsed.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found; please install ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr.strip()}") from exc

    data = json.loads(result.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError(f"No video stream found in {video_path!r}")

    width = int(video_stream["width"])
    height = int(video_stream["height"])

    # Duration may live on the stream or the container (format) level.
    duration_str = video_stream.get("duration") or data.get("format", {}).get("duration")
    if duration_str is None:
        raise ValueError(f"Could not determine duration of {video_path!r}")
    duration = float(duration_str)

    return width, height, duration


def transcribe_audio(video_path: str) -> dict:
    """Transcribe *video_path* using faster-whisper with word-level timestamps.

    Returns a dict with keys:
        language  (str)   – detected language code, e.g. "en"
        segments  (list)  – list of segment dicts, each containing:
            start, end, text, words (list of word dicts with start/end/word)

    The model size is controlled by the ``WHISPER_MODEL_SIZE`` environment
    variable (default: "base").
    """
    # Import here so tests can mock at the module level without importing
    # faster-whisper at module load time (it is a heavy optional dependency).
    from faster_whisper import WhisperModel  # type: ignore[import]

    model = WhisperModel(_WHISPER_MODEL_SIZE, compute_type="int8")
    segments_iter, info = model.transcribe(video_path, word_timestamps=True)

    segments = []
    for seg in segments_iter:
        words = []
        for w in (seg.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })

    return {
        "language": info.language,
        "segments": segments,
    }


def generate_ass_from_transcript(
    transcript: dict,
    duration: float,
    output_path: str,
    caption_style: str,
    caption_position: int,
    language: str,
    video_width: int,
    video_height: int,
) -> bool:
    """Generate an ASS subtitle file from a transcript dict.

    This is a thin wrapper around ``subtitles.generate_ass()``.
    Returns True on success.
    """
    import subtitles

    return subtitles.generate_ass(
        transcript,
        0,
        duration,
        output_path,
        caption_style=caption_style,
        caption_position=caption_position,
        language=language,
        video_width=video_width,
        video_height=video_height,
    )


def burn_subtitles(video_path: str, ass_path: str, output_path: str) -> bool:
    """Burn ASS subtitles into *video_path* and write to *output_path*.

    Uses libx264 with veryfast preset and CRF 18 for high quality output.
    Audio is stream-copied without re-encoding.

    Returns True on success.

    Raises:
        RuntimeError: if ffmpeg is not installed or returns a non-zero exit code.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found; please install ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr[-500:]}") from exc

    _ = result  # success
    return True


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_caption_job(
    storage,
    job_id: str,
    video_path: str,
    caption_style: str,
    caption_position: int,
    data_dir: str,
) -> None:
    """Run the full captioning pipeline for a job.

    Progress milestones:
        5   – job started, probing video
        40  – transcription complete
        50  – ASS file generated
        90  – subtitles burned into video
        100 – completed

    All exceptions are caught; on failure the job is marked "failed" with the
    exception message stored in ``error_message``.
    """
    # Derived paths
    ass_path = os.path.join(data_dir, "temp", job_id, "subtitles.ass")
    output_dir = os.path.join(data_dir, "output", job_id)
    output_path = os.path.join(output_dir, "captioned.mp4")

    start_time = time.time()

    try:
        # ------------------------------------------------------------------
        # Phase 1: probe
        # ------------------------------------------------------------------
        storage.update_status(
            job_id,
            status="processing",
            phase="transcribing",
            progress=5,
        )

        width, height, duration = probe_video(video_path)
        storage.update_status(job_id, duration=duration)

        # ------------------------------------------------------------------
        # Phase 2: transcribe
        # ------------------------------------------------------------------
        transcript = transcribe_audio(video_path)
        language = transcript.get("language", "en")
        storage.update_status(job_id, language=language, progress=40)

        # ------------------------------------------------------------------
        # Phase 3: generate ASS
        # ------------------------------------------------------------------
        storage.update_status(job_id, phase="burning", progress=50)

        os.makedirs(os.path.dirname(ass_path), exist_ok=True)
        generate_ass_from_transcript(
            transcript=transcript,
            duration=duration,
            output_path=ass_path,
            caption_style=caption_style,
            caption_position=caption_position,
            language=language,
            video_width=width,
            video_height=height,
        )

        # ------------------------------------------------------------------
        # Phase 4: burn subtitles
        # ------------------------------------------------------------------
        storage.update_status(job_id, phase="finalizing", progress=90)

        os.makedirs(output_dir, exist_ok=True)
        burn_subtitles(video_path, ass_path, output_path)

        # ------------------------------------------------------------------
        # Phase 5: clean up temp files and finalise
        # ------------------------------------------------------------------
        temp_job_dir = os.path.join(data_dir, "temp", job_id)
        if os.path.isdir(temp_job_dir):
            shutil.rmtree(temp_job_dir, ignore_errors=True)

        storage.update_status(
            job_id,
            status="completed",
            progress=100,
            output_path=output_path,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s failed: %s", job_id, exc)
        storage.update_status(job_id, status="failed", error=str(exc))
