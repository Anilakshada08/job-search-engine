from jobhunt.agents.base import DoNotRepeatEntry
from jobhunt.agents.dedup import DedupAgent, match_history
from jobhunt.agents.screener import ScreenerAgent
from jobhunt.integrations.github import ensure_noindex
from jobhunt.models import JobPosting
from jobhunt.textutil import job_ids, title_similarity, within_days


def P(company, title, link="https://example.com/x", source="Dice", **kw):
    return JobPosting(company=company, title=title, link=link, source=source, **kw)


HISTORY = [
    DoNotRepeatEntry(company="Arkhya Tech", title="Javascript Developer / UI Developer",
                     link="https://www.linkedin.com/jobs/view/4473923635/", date="2026-09-30"),
    DoNotRepeatEntry(company="TMS LLC", title="Senior Angular Frontend Developer - Agentic AI"),
]


def test_linkedin_id_match_across_url_shapes():
    p = P("Other Name", "Whatever", link="https://www.linkedin.com/jobs/search/?currentJobId=4473923635&f_TPR=r604800")
    assert match_history(p, HISTORY).company == "Arkhya Tech"


def test_same_company_near_identical_title_on_other_site():
    p = P("TMS", "Sr. Angular Front End Developer - Agentic AI (Remote)")
    assert match_history(p, HISTORY) is not None


def test_end_client_repost_by_staffing_agency():
    p = P("Some Staffing Inc", "Senior Angular Frontend Developer - Agentic AI")
    assert match_history(p, HISTORY) is None
    assert match_history(p, HISTORY, end_client="TMS LLC") is not None


def test_different_role_same_company_not_matched():
    assert match_history(P("TMS LLC", "Data Engineer"), HISTORY) is None


def test_cross_site_collapse_prefers_ats():
    a = P("Acme", "Senior Angular Developer", source="Dice", link="https://dice.com/1")
    b = P("Acme Inc.", "Sr Angular Developer", source="Greenhouse", link="https://boards.greenhouse.io/acme/2")
    out = DedupAgent._collapse([a, b])
    assert len(out) == 1 and out[0].source == "Greenhouse" and out[0].other_sites == ["Dice"]


def test_hard_rules():
    excl = ["capgemini", "capital one", "discover"]
    assert "Excluded" in ScreenerAgent._hard_rule(P("Vendor", "Angular Dev", description="Client: Capital One"), excl)
    assert ScreenerAgent._hard_rule(P("Acme", "Angular Dev", description="Discover new ways to build"), excl) == ""
    assert "Clearance" in ScreenerAgent._hard_rule(P("Acme", "Angular Dev", description="Active Secret clearance required"), excl)
    assert "citizens" in ScreenerAgent._hard_rule(P("Acme", "Angular Dev", description="US citizens only"), excl)


def test_text_helpers():
    assert title_similarity("Sr. Angular Developer", "Senior Angular Developer") >= 0.85
    assert within_days("2 days ago", 7) is True and within_days("30 days ago", 7) is False
    assert within_days("", 7) is None
    assert "li:4473923635" in job_ids("https://www.linkedin.com/jobs/view/angular-dev-at-x-4473923635")


def test_noindex_inserted_once_after_charset():
    html = "<!doctype html><html><head><meta charset=utf8><title>x</title></head></html>"
    out = ensure_noindex(html)
    assert out.startswith('<!doctype html><html><head><meta charset=utf8><meta name="robots"')
    assert ensure_noindex(out) == out
