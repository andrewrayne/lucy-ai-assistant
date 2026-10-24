import io
import json
import zipfile

from app.scheduler.backup import build_zip
from app.tools.documents import to_html
from app.tools.research import parse_questions
from app.tools.youtube import retention_points, srt_to_text, video_id


def test_video_id_from_any_link():
    for link in ["https://youtu.be/FzPrN7pXhGo", "https://www.youtube.com/watch?v=FzPrN7pXhGo&t=10",
                 "https://youtube.com/shorts/FzPrN7pXhGo", "FzPrN7pXhGo"]:
        assert video_id(link) == "FzPrN7pXhGo"


def test_retention_points_pick_nearest_marks():
    rows = [[0.0, 1.0], [0.24, 0.62], [0.5, 0.41], [0.76, 0.30], [1.0, 0.12]]
    assert retention_points(rows) == {"25%": 62, "50%": 41, "75%": 30, "100%": 12}


def test_srt_to_text():
    srt = "1\n00:00:00,000 --> 00:00:02,000\nHello there\n\n2\n00:00:02,000 --> 00:00:04,000\nand welcome\n"
    assert srt_to_text(srt) == "Hello there and welcome"


def test_research_plan_parsing_falls_back_to_topic():
    assert parse_questions('Sure: ["a?", "b?"]', "topic") == ["a?", "b?"]
    assert parse_questions("no json here", "topic") == ["topic"]


def test_document_html_has_title_and_tables():
    html = to_html("Plan", "| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<h1>Plan</h1>" in html and "<table>" in html


def test_backup_zip_has_one_json_per_table():
    data = build_zip({"lessons": [{"id": 1, "content": "x"}], "skills": []}, "2026-10-24")
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(zf.namelist()) == ["README.txt", "lessons.json", "skills.json"]
    assert json.loads(zf.read("lessons.json")) == [{"id": 1, "content": "x"}]
