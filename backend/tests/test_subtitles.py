"""Tests for ASS subtitle generation."""
import os
import tempfile
import pytest

@pytest.fixture
def sample_transcript():
    return {
        "language": "en",
        "segments": [{
            "start": 0.0, "end": 3.0, "text": "Hello world how are you",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "world", "start": 0.6, "end": 1.0},
                {"word": "how", "start": 1.1, "end": 1.4},
                {"word": "are", "start": 1.5, "end": 1.7},
                {"word": "you", "start": 1.8, "end": 2.0},
            ],
        }],
    }

@pytest.fixture
def output_path():
    fd, path = tempfile.mkstemp(suffix=".ass")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)

def test_generate_ass_creates_file(sample_transcript, output_path):
    from subtitles import generate_ass
    result = generate_ass(sample_transcript, 0, 3.0, output_path, caption_style="hormozi", caption_position=10, language="en", video_width=1080, video_height=1920)
    assert result is True
    assert os.path.exists(output_path)
    assert os.path.getsize(output_path) > 0

def test_generate_ass_contains_style_info(sample_transcript, output_path):
    from subtitles import generate_ass
    generate_ass(sample_transcript, 0, 3.0, output_path, caption_style="hormozi", language="en", video_width=1080, video_height=1920)
    with open(output_path, "r") as f:
        content = f.read()
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content

def test_generate_ass_contains_dialogue(sample_transcript, output_path):
    from subtitles import generate_ass
    generate_ass(sample_transcript, 0, 3.0, output_path, caption_style="hormozi", language="en", video_width=1080, video_height=1920)
    with open(output_path, "r") as f:
        content = f.read()
    assert "Dialogue:" in content

def test_generate_ass_different_styles(sample_transcript, output_path):
    from subtitles import generate_ass
    for style in ["hormozi", "mrbeast", "karaoke", "minimal", "bounce", "classic"]:
        result = generate_ass(sample_transcript, 0, 3.0, output_path, caption_style=style, language="en", video_width=1080, video_height=1920)
        assert result is True, f"Style {style} failed"
        assert os.path.getsize(output_path) > 0, f"Style {style} produced empty file"

def test_generate_ass_empty_transcript(output_path):
    from subtitles import generate_ass
    empty = {"language": "en", "segments": []}
    result = generate_ass(empty, 0, 3.0, output_path, caption_style="hormozi", language="en", video_width=1080, video_height=1920)
    assert result is False

def test_generate_ass_non_latin(output_path):
    from subtitles import generate_ass
    transcript = {"language": "ja", "segments": [{"start": 0.0, "end": 2.0, "text": "Hello", "words": [{"word": "Hello", "start": 0.0, "end": 1.0}]}]}
    result = generate_ass(transcript, 0, 2.0, output_path, caption_style="hormozi", language="ja", video_width=1080, video_height=1920)
    assert result is True
    with open(output_path, "r") as f:
        content = f.read()
    # Non-Latin scripts must use the configured font fallback, unless that font
    # is not installed on the host (e.g. on Windows there is no "IBM Plex Sans").
    # The ASS Style Fontname must always be non-empty so libass can render glyphs.
    if "IBM Plex Sans" in content:
        assert "IBM Plex Sans" in content
    else:
        assert "Tahoma" in content

def test_generate_ass_landscape_dimensions(sample_transcript, output_path):
    from subtitles import generate_ass
    result = generate_ass(sample_transcript, 0, 3.0, output_path, caption_style="hormozi", language="en", video_width=1920, video_height=1080)
    assert result is True
    with open(output_path, "r") as f:
        content = f.read()
    assert "PlayResX: 1920" in content
    assert "PlayResY: 1080" in content
