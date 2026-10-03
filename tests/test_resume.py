from pathlib import Path

import yaml

from jobhunt.agents.tailor import Tailored, apply_route, enforce_truth
from jobhunt.models import ExperienceEntry
from jobhunt.resume import render

PROFILE = yaml.safe_load((Path(__file__).parents[1] / "config" / "profile.example.yaml").read_text(encoding="utf-8"))


def _tailored(**kw):
    base = dict(
        headline="Senior Angular Engineer", summary="Angular developer with NgRx and RxJS.",
        skills=["Angular", "NgRx", "Kubernetes"],
        experience=[ExperienceEntry(title="Principal Architect", company="Invented Co", client="", dates="2010 - Now",
                                    tech=["Angular 16", "Rust"], bullets=["Built Angular apps with NgRx."])],
        education=["PhD"], matched_keywords=["Angular", "NgRx"], gap_keywords=["Kubernetes"],
        match_percent=67, risk="")
    base.update(kw)
    return Tailored(**base)


def test_enforce_truth_restores_base_resume_facts():
    t = _tailored()
    notes = enforce_truth(t, PROFILE)
    e = t.experience[0]
    assert (e.title, e.company, e.dates) == ("Senior Angular Developer", "Example Corp", "Jan 2020 - Present")
    assert "Kubernetes" not in t.skills and "Rust" not in e.tech
    assert t.education == PROFILE["education"]
    assert any("restored" in n for n in notes)


def test_render_and_verify(tmp_path):
    t = _tailored()
    enforce_truth(t, PROFILE)
    pdf, docx, att = tmp_path / "r.pdf", tmp_path / "r.docx", tmp_path / "a.pdf"
    render.render_pdf(t, PROFILE, pdf)
    render.render_docx(t, PROFILE, docx)
    render.render_attachment_pdf(t, PROFILE, att)
    assert render.pdf_pages(pdf) <= 2 and docx.stat().st_size > 0
    assert render.verify_keywords(pdf, ["Angular", "NgRx"]) == []
    assert render.verify_keywords(pdf, ["Kubernetes"]) == ["Kubernetes"]
    assert att.stat().st_size < pdf.stat().st_size or "Helvetica" in render._register_calibri()


def test_apply_route():
    assert apply_route("https://acme.wd5.myworkdayjobs.com/x")[1] is True
    assert apply_route("https://boards.greenhouse.io/acme/jobs/1")[1] is False
    assert apply_route("https://www.linkedin.com/jobs/view/1")[0] == "LinkedIn"
