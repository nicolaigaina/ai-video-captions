"""ASS subtitle generation with word-by-word animations.

Creates styled ASS (Advanced SubStation Alpha) subtitle files with per-word
highlight animations.  Supports 6 animation types (highlight, karaoke, scale,
bounce, and their RTL-safe variants) across Latin, CJK, Cyrillic, Arabic,
Devanagari, Thai, and Hebrew scripts.

Ported from autoshorts ``backend/clips/subtitles.py`` — only the core
``generate_ass`` function.  Transcription and burn-in live in ``caption_job.py``.
"""

import os
import sys

import pysubs2

try:
    from arabic_reshaper import reshape as _arabic_reshape  # type: ignore[import]
    from bidi.algorithm import get_display as _bidi_get_display  # type: ignore[import]
except Exception:  # pragma: no cover - optional runtime dependency
    _arabic_reshape = None
    _bidi_get_display = None

from caption_styles import get_caption_style, get_output_format
from subtitle_utils import (
    escape_ass_text,
    get_subtitle_layout,
    is_latin_language,
    is_rtl_language,
    strip_emojis,
)


RTL_EMBED_START = "\u202b"  # Right-to-Left Embedding
RTL_EMBED_END = "\u202c"    # Pop directional formatting
RLM = "\u200f"              # Right-to-Left mark


def _rtl_visual_fallback_enabled() -> bool:
    """Whether to use visual-order RTL fallback for ASS rendering.

    Some ffmpeg/libass builds (common on Windows) lack full bidi/shaping
    support. In that case we pre-compose RTL text in visual order so burn-in
    still appears readable.
    """
    override = os.environ.get("ASS_RTL_VISUAL_FALLBACK", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return sys.platform == "win32"


def _shape_rtl_text_for_visual_fallback(text: str) -> str:
    """Return visually-correct RTL text for renderers without bidi/shaping.

    Preferred path uses arabic-reshaper + python-bidi. If unavailable, we keep
    the older best-effort char reversal fallback.
    """
    if _arabic_reshape is not None and _bidi_get_display is not None:
        return _bidi_get_display(_arabic_reshape(text))
    return text[::-1]


def _is_font_available(font_name: str) -> bool:
    """Best-effort check whether *font_name* resolves to an installed font.

    On Windows we check the standard font registry (%SystemRoot%\\Fonts),
    matching both the bare family name and the Plex-style family variants.
    On POSIX systems libass typically falls back gracefully, so we keep the
    original family name unless we can positively confirm it is installed.

    Note: this is only used to pick a *fallback* family name for libass when a
    font such as "IBM Plex Sans" is configured but not present on the system
    (common on Windows). The ASS ``Fontname`` value is what libass matches, so
    it must reference a font that actually exists.
    """
    if sys.platform == "win32":
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        if not os.path.isdir(fonts_dir):
            return False
        try:
            entries = set(os.listdir(fonts_dir))
        except OSError:
            return False
        needle = font_name.lower().replace(" ", "")
        stem_candidates = {e.split(".")[0].replace(" ", "").lower() for e in entries}
        return any(needle in candidate for candidate in stem_candidates)
    return True


def generate_ass(
    transcript: dict,
    clip_start: float,
    clip_end: float,
    output_path: str,
    *,
    caption_style: str = "hormozi",
    caption_position: int = 10,
    language: str = "en",
    video_width: int | None = None,
    video_height: int | None = None,
) -> bool:
    """Generate an ASS subtitle file with styled word-by-word animations.

    Args:
        transcript: Dict with ``segments`` containing word-level timestamps.
        clip_start: Start time of clip in seconds.
        clip_end: End time of clip in seconds.
        output_path: Path to write the ``.ass`` file.
        caption_style: Style ID (hormozi, mrbeast, karaoke, minimal, bounce, classic).
        caption_position: Position as percentage from bottom (5-50).
        language: Language code for font selection (Latin vs fallback).
        video_width: Actual video width (``None`` = default vertical 1080).
        video_height: Actual video height (``None`` = default vertical 1920).

    Returns:
        ``True`` if successful, ``False`` if no words found in the clip range.
    """
    # ------------------------------------------------------------------
    # Style and resolution setup
    # ------------------------------------------------------------------
    style_config = get_caption_style(caption_style)

    if video_width and video_height:
        play_res_x = video_width
        play_res_y = video_height
        # Scale relative to vertical reference (1920px height)
        dimension_scale = max(video_height / 1920, 0.35)
    else:
        format_config = get_output_format("vertical")
        play_res_x = format_config.width
        play_res_y = format_config.height
        dimension_scale = 1.0

    # Prefer auto-detected language from transcript over caller's default
    language = transcript.get("language", language)
    rtl_language = is_rtl_language(language)

    # ------------------------------------------------------------------
    # Extract and flatten words within the clip range
    # ------------------------------------------------------------------
    clip_segments: list[dict] = []
    for segment in transcript.get("segments", []):
        for word_info in segment.get("words", []):
            if (
                word_info.get("end") is not None
                and word_info.get("start") is not None
                and word_info["end"] > clip_start
                and word_info["start"] < clip_end
            ):
                word_text = strip_emojis(word_info["word"].strip())
                if not word_text:
                    continue
                clip_segments.append(
                    {
                        "word": word_text,
                        "start": word_info["start"],
                        "end": word_info["end"],
                    }
                )

    if not clip_segments:
        return False

    # ------------------------------------------------------------------
    # Character-based grouping with multi-line support
    # ------------------------------------------------------------------
    max_chars_per_line, font_scale = get_subtitle_layout(language, style_config.font_size)
    max_lines = 2

    subtitles: list[tuple[float, float, list[tuple]]] = []
    current_lines: list[list[tuple]] = [[]]
    current_line_chars: list[int] = [0]
    current_start: float | None = None
    current_end: float | None = None

    for seg in clip_segments:
        word = seg["word"]
        seg_start = seg["start"]
        seg_end = seg["end"]

        if not word:
            continue

        # Convert absolute timestamps to relative (clip-based)
        start_rel = max(0.0, seg_start - clip_start)
        end_rel = max(0.0, seg_end - clip_start)

        if end_rel <= 0:
            continue

        word_length = len(word)

        # Start a new subtitle group if no words yet
        if not any(current_lines):
            current_start = start_rel
            current_end = end_rel
            current_lines = [[(word, start_rel, end_rel)]]
            current_line_chars = [word_length]
        else:
            current_line_idx = len(current_lines) - 1
            current_line = current_lines[current_line_idx]
            current_chars = current_line_chars[current_line_idx]

            # Calculate characters if we add this word (including space)
            chars_with_word = current_chars + (1 if current_line else 0) + word_length

            if chars_with_word <= max_chars_per_line:
                # Word fits on current line
                current_line.append((word, start_rel, end_rel))
                current_line_chars[current_line_idx] = chars_with_word
                current_end = end_rel
            elif current_line_idx + 1 < max_lines:
                # Start new line within current subtitle group
                current_lines.append([(word, start_rel, end_rel)])
                current_line_chars.append(word_length)
                current_end = end_rel
            else:
                # Current subtitle group is full — finalise and start new
                flattened_words = []
                for line_idx, line in enumerate(current_lines):
                    for word_tuple in line:
                        flattened_words.append(word_tuple + (line_idx,))
                subtitles.append((current_start, current_end, flattened_words))

                current_start = start_rel
                current_end = end_rel
                current_lines = [[(word, start_rel, end_rel)]]
                current_line_chars = [word_length]

    # Flush the last subtitle group
    if any(current_lines):
        flattened_words = []
        for line_idx, line in enumerate(current_lines):
            for word_tuple in line:
                flattened_words.append(word_tuple + (line_idx,))
        subtitles.append((current_start, current_end, flattened_words))

    # ------------------------------------------------------------------
    # Create ASS subtitle file
    # ------------------------------------------------------------------
    subs = pysubs2.SSAFile()

    subs.info["WrapStyle"] = 3
    subs.info["ScaledBorderAndShadow"] = "yes"
    subs.info["PlayResX"] = play_res_x
    subs.info["PlayResY"] = play_res_y
    subs.info["ScriptType"] = "v4.00+"

    # ---- helper: parse ASS colour string to pysubs2.Color ----
    def _parse_ass_color(ass_color: str) -> pysubs2.Color:
        color_hex = ass_color.replace("&H", "").replace("&", "")
        color_hex = color_hex.zfill(8)
        alpha = int(color_hex[0:2], 16)
        blue = int(color_hex[2:4], 16)
        green = int(color_hex[4:6], 16)
        red = int(color_hex[6:8], 16)
        return pysubs2.Color(red, green, blue, alpha)

    # ---- style definition ----
    style_name = "Default"
    new_style = pysubs2.SSAStyle()

    if rtl_language:
        # Force a known Arabic-script-capable system font on Windows.
        # This avoids broken shaping/isolated glyph fallbacks with display fonts.
        new_style.fontname = "Tahoma" if sys.platform == "win32" else style_config.font_name_fallback
    elif is_latin_language(language):
        new_style.fontname = style_config.font_name
    else:
        # The configured fallback family (e.g. "IBM Plex Sans") is not always
        # installed — especially on Windows, where libass has no match and the
        # Arabic/Persian glyphs would render as blank / missing boxes. When we
        # can confirm the configured fallback is absent, switch to a font known
        # to ship with the OS and cover Arabic-script (Tahoma has full Arabic
        # + Persian support and is always present on Windows/macOS).
        new_style.fontname = style_config.font_name_fallback
        if not _is_font_available(style_config.font_name_fallback):
            new_style.fontname = "Tahoma"

    new_style.fontsize = int(style_config.font_size * font_scale * dimension_scale)
    new_style.primarycolor = _parse_ass_color(style_config.primary_color)
    new_style.bold = style_config.bold
    new_style.italic = style_config.italic
    new_style.outline = round(style_config.outline_size * font_scale * dimension_scale, 1)
    new_style.outlinecolor = _parse_ass_color(style_config.outline_color)
    new_style.shadow = round(style_config.shadow_depth * font_scale * dimension_scale, 1)
    new_style.shadowcolor = _parse_ass_color(style_config.shadow_color)
    new_style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    new_style.marginl = int(40 * dimension_scale)
    new_style.marginr = int(40 * dimension_scale)
    new_style.marginv = int(play_res_y * caption_position / 100)
    new_style.spacing = 0.5

    subs.styles[style_name] = new_style

    # ---- animation settings ----
    highlight_color = style_config.highlight_color
    animation_type = style_config.animation_type
    rtl_visual_fallback = rtl_language and _rtl_visual_fallback_enabled()

    def _format_word_for_display(raw_word: str) -> str:
        """Prepare one word for ASS text with stable bidi behaviour."""
        text_word = raw_word if rtl_language else raw_word.upper()
        if rtl_visual_fallback:
            text_word = _shape_rtl_text_for_visual_fallback(text_word)
        escaped = escape_ass_text(text_word)
        if rtl_language and not rtl_visual_fallback:
            # Wrap each token so inline ASS tags do not break RTL ordering.
            return f"{RLM}{escaped}{RLM}"
        return escaped

    # ------------------------------------------------------------------
    # Generate per-word subtitle events
    # ------------------------------------------------------------------
    for line_start, line_end, word_list in subtitles:
        if rtl_visual_fallback:
            # In visual fallback mode, per-word styling often breaks Arabic
            # shaping/joining on some libass builds. Render one fully-shaped
            # event per subtitle group for readability.
            lines: dict[int, list[str]] = {}
            for w, _, _, line_idx in word_list:
                lines.setdefault(line_idx, []).append(w)

            rendered_lines: list[str] = []
            for line_idx in sorted(lines.keys()):
                raw_line = " ".join(lines[line_idx])
                shaped_line = _shape_rtl_text_for_visual_fallback(raw_line)
                rendered_lines.append(escape_ass_text(shaped_line))

            text = "\\N".join(rendered_lines)
            event = pysubs2.SSAEvent(
                start=pysubs2.make_time(s=line_start),
                end=pysubs2.make_time(s=line_end),
                text=text,
                style=style_name,
            )
            subs.events.append(event)
            continue

        for idx, (word, word_start, _, _) in enumerate(word_list):
            # Event end = next word's start, or line end for last word
            if idx < len(word_list) - 1:
                event_end = word_list[idx + 1][1]
            else:
                event_end = line_end

            # Build full-line text with animation tags for the current word
            text_parts: list[str] = []
            prev_line_idx = None

            indexed_words = [
                (i, w, w_start, w_end, line_idx)
                for i, (w, w_start, w_end, line_idx) in enumerate(word_list)
            ]

            if rtl_visual_fallback:
                # Reorder words per visual line for renderers without bidi.
                display_sequence: list[tuple[int, str, float, float, int]] = []
                line_ids = sorted({line_idx for _, _, _, _, line_idx in indexed_words})
                for line_id in line_ids:
                    line_items = [item for item in indexed_words if item[4] == line_id]
                    line_items.reverse()
                    display_sequence.extend(line_items)
            else:
                display_sequence = indexed_words

            for original_idx, w, w_start, w_end, line_idx in display_sequence:
                # Line break when moving to a new display line
                if prev_line_idx is not None and line_idx != prev_line_idx:
                    text_parts.append("\\N")

                w_display = _format_word_for_display(w)

                if original_idx == idx:
                    # Current word — apply style-specific highlight
                    word_color = highlight_color

                    if animation_type == "karaoke":
                        if rtl_language:
                            text_parts.append(f"{{\\c{word_color}}}{w_display}{{\\r}}")
                        else:
                            duration_cs = (
                                int((w_end - w_start) * 100) if w_end > w_start else 30
                            )
                            text_parts.append(
                                f"{{\\kf{duration_cs}\\c{word_color}}}{w_display}{{\\r}}"
                            )
                    elif animation_type == "scale":
                        text_parts.append(
                            f"{{\\fscx110\\fscy110\\c{word_color}}}{w_display}{{\\r}}"
                        )
                    elif animation_type == "bounce":
                        bounce_pct = 120 if font_scale >= 1.0 else 112
                        text_parts.append(
                            f"{{\\t(0,50,\\fscx{bounce_pct}\\fscy{bounce_pct})"
                            f"\\t(50,100,\\fscx100\\fscy100)"
                            f"\\c{word_color}}}{w_display}{{\\r}}"
                        )
                    else:
                        # Default highlight: simple colour change
                        text_parts.append(f"{{\\c{word_color}}}{w_display}{{\\r}}")
                else:
                    # Not currently speaking — default style colour
                    text_parts.append(w_display)

                prev_line_idx = line_idx

            # Join words with spacing
            if style_config.word_spacing != 100 and not rtl_language:
                space = f"{{\\fscx{style_config.word_spacing}}} {{\\fscx100}}"
                text = space.join(text_parts)
            else:
                text = " ".join(text_parts)

            if rtl_language and not rtl_visual_fallback:
                # Force line paragraph direction to RTL for libass bidi.
                text = f"{RTL_EMBED_START}{text}{RTL_EMBED_END}"

            # Apply letter spacing if non-zero
            if style_config.letter_spacing != 0 and not rtl_language:
                text = f"{{\\fsp{style_config.letter_spacing}}}{text}"

            event = pysubs2.SSAEvent(
                start=pysubs2.make_time(s=word_start),
                end=pysubs2.make_time(s=event_end),
                text=text,
                style=style_name,
            )
            subs.events.append(event)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    try:
        subs.save(output_path)
    except Exception as exc:
        raise IOError(f"Failed to save subtitle file: {exc}") from exc

    return True
