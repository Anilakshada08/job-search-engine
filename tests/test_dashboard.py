import json

import pytest

from jobhunt import dashboard

HTML = """<!doctype html><html><head><meta charset=utf8></head><body>
<script type="application/json" id="tracker-data">
{"updated": "x", "jobs": [{"id": "a-b", "company": "A", "role": "B", "status": "Interview", "link": "https://x/1"}], "runs": []}
</script><script>render()</script></body></html>"""


def _job(**kw):
    base = {"id": "acme-angular-dev", "company": "Acme", "role": "Angular Dev", "status": "Ready",
            "link": "https://acme/jobs/2", "notes": "has <b> tag"}
    base.update(kw)
    return base


def test_append_keeps_existing_status_and_escapes_lt(tmp_path):
    p = tmp_path / "d.html"
    p.write_text(HTML, encoding="utf-8")
    added = dashboard.update_file(p, [_job()], {"at": "t", "mode": "Cloud", "reviewed": 3, "summary": "s", "gaps": []})
    assert added == ["acme-angular-dev"]
    html = p.read_text(encoding="utf-8")
    body = dashboard.TRACKER_RE.search(html).group(2)
    assert "<" not in body                                   # safe inside <script>
    data = dashboard.read_tracker(html)
    assert data["jobs"][0]["status"] == "Interview"          # untouched
    assert data["jobs"][1]["notes"] == "has <b> tag"         # round-trips via <
    assert data["runs"][-1]["ready"] == 1
    assert html.endswith("<script>render()</script></body></html>")


def test_duplicate_link_and_id_handling(tmp_path):
    p = tmp_path / "d.html"
    p.write_text(HTML, encoding="utf-8")
    added = dashboard.update_file(p, [_job(link="https://x/1"), _job(id="a-b", link="https://new")],
                                  {"at": "t", "mode": "Cloud", "reviewed": 0, "summary": "", "gaps": []})
    assert added == ["a-b-2"]


def test_rejects_unknown_status():
    data = json.loads('{"jobs": [], "runs": []}')
    with pytest.raises(ValueError):
        dashboard.append(data, [_job(status="Interview")], {})
