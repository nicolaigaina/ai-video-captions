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
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

# Default Whisper model size; override via env var to trade speed vs accuracy.
_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")


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


def transcribe_audio(
    video_path: str,
    *,
    duration_seconds: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
    forced_language: str | None = None,
) -> dict:
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

    decoded_audio = None

    def _materialize_transcript(segments_iter, info_obj) -> dict:
        segments = []
        for seg in segments_iter:
            if duration_seconds and duration_seconds > 0 and progress_callback:
                ratio = min(max(float(seg.end) / duration_seconds, 0.0), 1.0)
                progress_callback(ratio)

            words = []
            raw_words = seg.words or []
            for w in raw_words:
                words.append({"word": w.word, "start": w.start, "end": w.end})

            # Some languages/files can return segment text without word-level
            # timestamps. Build a best-effort synthetic word timeline so subtitle
            # generation can still proceed.
            if not words:
                segment_text = (seg.text or "").strip()
                tokens = [t for t in segment_text.split() if t]
                if tokens:
                    seg_start = float(seg.start)
                    seg_end = float(seg.end)
                    seg_duration = max(seg_end - seg_start, 0.01)
                    token_duration = seg_duration / len(tokens)
                    for idx, token in enumerate(tokens):
                        start = seg_start + (idx * token_duration)
                        end = seg_start + ((idx + 1) * token_duration)
                        if idx == len(tokens) - 1:
                            end = seg_end
                        words.append({"word": token, "start": start, "end": end})

            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": words,
            })

        return {
            "language": info_obj.language,
            "segments": segments,
        }

    def _has_content(transcript_obj: dict) -> bool:
        for segment in transcript_obj.get("segments", []):
            if (segment.get("text") or "").strip():
                return True
            if segment.get("words"):
                return True
        return False

    transcribe_kwargs: dict = {"word_timestamps": True}
    if forced_language:
        transcribe_kwargs["language"] = forced_language
    if transcribe_kwargs.get("language") == "fa":
        transcribe_kwargs["task"] = "transcribe"
        transcribe_kwargs["initial_prompt"] = "این یک گفتار فارسی است. لطفاً متن را دقیق پیاده‌سازی کن."

    try:
        # Normal path: let faster-whisper decode the media file itself.
        segments_iter, info = model.transcribe(video_path, **transcribe_kwargs)
    except TypeError as exc:
        # Compatibility fallback for environments where PyAV does not accept
        # faster-whisper's metadata_errors argument.
        if "metadata_errors" not in str(exc):
            raise

        import numpy as np  # type: ignore[import]

        logger.warning(
            "Falling back to ffmpeg PCM decode due to PyAV incompatibility: %s",
            exc,
        )

        decode_cmd = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            video_path,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ]

        try:
            decoded = subprocess.run(
                decode_cmd,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as ffmpeg_exc:
            raise RuntimeError("ffmpeg not found; please install ffmpeg") from ffmpeg_exc
        except subprocess.CalledProcessError as ffmpeg_exc:
            stderr = (ffmpeg_exc.stderr or b"").decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg audio decode failed: {stderr[-500:]}") from ffmpeg_exc

        pcm = np.frombuffer(decoded.stdout, dtype=np.int16)
        if pcm.size == 0:
            raise RuntimeError("Failed to decode audio track from video")

        decoded_audio = pcm.astype(np.float32) / 32768.0
        segments_iter, info = model.transcribe(decoded_audio, **transcribe_kwargs)

    transcript = _materialize_transcript(segments_iter, info)

    if not _has_content(transcript):
        retry_language = forced_language or "fa"
        logger.warning(
            "Transcription returned no usable speech; retrying with language='%s' and permissive decode settings",
            retry_language,
        )
        retry_kwargs = {
            "word_timestamps": True,
            "language": retry_language,
            "vad_filter": False,
            "beam_size": 1,
            "best_of": 1,
            "condition_on_previous_text": False,
        }
        if retry_language == "fa":
            retry_kwargs["task"] = "transcribe"
            retry_kwargs["initial_prompt"] = "این یک گفتار فارسی است. لطفاً متن را دقیق پیاده‌سازی کن."
        if decoded_audio is not None:
            segments_iter, info = model.transcribe(decoded_audio, **retry_kwargs)
        else:
            segments_iter, info = model.transcribe(video_path, **retry_kwargs)
        transcript = _materialize_transcript(segments_iter, info)

    return transcript


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


def burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    *,
    duration_seconds: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> bool:
    """Burn ASS subtitles into *video_path* and write to *output_path*.

    Uses libx264 with veryfast preset and CRF 18 for high quality output.
    Audio is stream-copied without re-encoding.

    Returns True on success.

    Raises:
        RuntimeError: if ffmpeg is not installed or returns a non-zero exit code.
    """
    ass_filter_path = os.path.abspath(ass_path).replace("\\", "/")
    ass_filter_path = (
        ass_filter_path
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"ass='{ass_filter_path}'",
        "-progress", "pipe:1",
        "-nostats",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]

    output_lines: list[str] = []

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                output_lines.append(line)
                if len(output_lines) > 200:
                    output_lines.pop(0)

                if (
                    progress_callback
                    and duration_seconds
                    and duration_seconds > 0
                    and line.startswith("out_time_ms=")
                ):
                    try:
                        out_time_ms = int(line.split("=", 1)[1])
                    except (TypeError, ValueError):
                        continue

                    ratio = min(max((out_time_ms / 1_000_000) / duration_seconds, 0.0), 1.0)
                    progress_callback(ratio)

        return_code = process.wait()
        if return_code != 0:
            tail = "\n".join(output_lines)[-1200:]
            raise RuntimeError(f"ffmpeg failed: {tail}")

        if progress_callback:
            progress_callback(1.0)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found; please install ffmpeg") from exc

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
    *,
    forced_language: str | None = None,
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

    def _run_with_heartbeat(
        work: Callable[[], object],
        heartbeat: Callable[[], None],
        interval_seconds: float = 10.0,
    ) -> object:
        result: dict[str, object] = {"value": None}
        error: dict[str, Exception | None] = {"value": None}

        def _target() -> None:
            try:
                result["value"] = work()
            except Exception as exc:  # noqa: BLE001
                error["value"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()

        while thread.is_alive():
            thread.join(timeout=interval_seconds)
            if thread.is_alive():
                heartbeat()

        if error["value"] is not None:
            raise error["value"]

        return result["value"]

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
        transcribe_progress = 5
        transcribe_started_at = time.time()
        # Heuristic wall-time estimate so long CPU transcribes do not look frozen
        # at 5% before first decoded segment arrives.
        transcribe_expected_seconds = max(duration * 4.0, 60.0)

        def _on_transcribe_progress(ratio: float) -> None:
            nonlocal transcribe_progress
            transcribe_progress = min(40, max(5, int(5 + ratio * 35)))
            storage.update_status(job_id, phase="transcribing", progress=transcribe_progress)

        transcript = _run_with_heartbeat(
            lambda: transcribe_audio(
                video_path,
                duration_seconds=duration,
                progress_callback=_on_transcribe_progress,
                forced_language=forced_language,
            ),
            lambda: storage.update_status(
                job_id,
                phase="transcribing",
                progress=max(
                    transcribe_progress,
                    min(
                        35,
                        5 + int(((time.time() - transcribe_started_at) / transcribe_expected_seconds) * 30),
                    ),
                ),
            ),
        )
        language = transcript.get("language", "en")
        storage.update_status(job_id, language=language, progress=40)

        # ------------------------------------------------------------------
        # Phase 3: generate ASS
        # ------------------------------------------------------------------
        storage.update_status(job_id, phase="burning", progress=50)

        os.makedirs(os.path.dirname(ass_path), exist_ok=True)
        generated = generate_ass_from_transcript(
            transcript=transcript,
            duration=duration,
            output_path=ass_path,
            caption_style=caption_style,
            caption_position=caption_position,
            language=language,
            video_width=width,
            video_height=height,
        )

        if not generated:
            raise RuntimeError(
                "No speech words were detected in the selected range, so subtitles could not be generated."
            )

        # ------------------------------------------------------------------
        # Phase 4: burn subtitles
        # ------------------------------------------------------------------
        os.makedirs(output_dir, exist_ok=True)
        burn_progress = 50

        def _on_burn_progress(ratio: float) -> None:
            nonlocal burn_progress
            burn_progress = min(89, max(50, int(50 + ratio * 39)))
            storage.update_status(job_id, phase="burning", progress=burn_progress)

        _run_with_heartbeat(
            lambda: burn_subtitles(
                video_path,
                ass_path,
                output_path,
                duration_seconds=duration,
                progress_callback=_on_burn_progress,
            ),
            lambda: storage.update_status(
                job_id,
                phase="burning",
                progress=burn_progress,
            ),
        )

        storage.update_status(job_id, phase="finalizing", progress=90)

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
