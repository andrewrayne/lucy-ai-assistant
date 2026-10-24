from app.voice import voice_parts


def test_voice_turn_has_recording_and_transcript():
    parts = voice_parts(b"OggS...", "audio/ogg", "what's the weather")
    assert parts[0].inline_data.mime_type == "audio/ogg" and parts[0].inline_data.data == b"OggS..."
    assert "what's the weather" in parts[1].text and "Listen to all of it" in parts[1].text
