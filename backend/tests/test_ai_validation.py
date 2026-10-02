"""Tests for the gate between model output and the database.

Every rule here exists because something got through without it.
"""

import pytest

from app.ai.schemas import ExtractedLead
from app.ai.validation import validate_candidates

VISITED = {"https://example-fashion.com/leadership", "https://trade-press.com/news/appointment"}


def make(**overrides) -> ExtractedLead:
    base = {
        "first_name": "Rahul",
        "last_name": "Sharma",
        "job_title": "Head of Merchandising",
        "source_url": "https://example-fashion.com/leadership",
        "company_name": "Example Fashion",
    }
    return ExtractedLead(**{**base, **overrides})


def run(*candidates: ExtractedLead):
    return validate_candidates(list(candidates), visited_urls=VISITED)


def reasons(outcome) -> set[str]:
    return {r.reason for r in outcome.rejections}


# --------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------


def test_a_valid_candidate_is_accepted() -> None:
    assert len(run(make()).accepted) == 1


def test_citation_to_an_unvisited_page_is_rejected() -> None:
    """The core grounding rule: a source we never read is a fabrication."""
    outcome = run(make(source_url="https://never-opened.com/team"))
    assert outcome.accepted == []
    assert reasons(outcome) == {"unvisited_source_url"}


def test_citation_matching_is_tolerant_of_trailing_slash_and_www() -> None:
    assert len(run(make(source_url="https://www.example-fashion.com/leadership/")).accepted) == 1


# --------------------------------------------------------------------------
# Who counts as a lead
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["N/A", "unknown", "John Doe", "???", "x"])
def test_placeholder_names_are_rejected(name: str) -> None:
    assert run(make(first_name=name)).accepted == []


@pytest.mark.parametrize(
    "title",
    [
        "Research Scientist",
        "PhD Candidate",
        "Demand Forecasting Researcher",
        "Marketing Intern",
        "Professor of Supply Chain",
    ],
)
def test_non_buying_roles_are_rejected(title: str) -> None:
    """Regression guard: one arXiv PDF on demand forecasting, published by a
    fashion retailer, once yielded four "leads" who were all paper authors."""
    outcome = run(make(job_title=title))
    assert outcome.accepted == []
    assert reasons(outcome) == {"not_a_buying_role"}


def test_an_operating_role_at_the_same_company_still_passes() -> None:
    assert len(run(make(job_title="Chief Supply Chain Officer")).accepted) == 1


def test_vague_titles_are_rejected() -> None:
    assert run(make(job_title="Employee")).accepted == []


def test_the_same_person_twice_in_one_batch_is_deduplicated() -> None:
    outcome = run(make(), make(job_title="Head of Merchandising, India"))
    assert len(outcome.accepted) == 1
    assert reasons(outcome) == {"duplicate_in_batch"}


# --------------------------------------------------------------------------
# Field-level stripping — the lead survives, the bad value does not
# --------------------------------------------------------------------------


@pytest.mark.parametrize("email", ["info@example.com", "careers@example.com", "hr@example.com"])
def test_role_mailboxes_are_stripped_but_the_lead_is_kept(email: str) -> None:
    outcome = run(make(email=email))
    assert len(outcome.accepted) == 1
    assert outcome.accepted[0].email is None
    assert {s.reason for s in outcome.strips} == {"role_mailbox"}


def test_a_personal_address_is_kept() -> None:
    assert run(make(email="rahul.sharma@example.com")).accepted[0].email == "rahul.sharma@example.com"


def test_malformed_email_is_stripped() -> None:
    outcome = run(make(email="rahul(at)example.com"))
    assert outcome.accepted[0].email is None
    assert {s.reason for s in outcome.strips} == {"malformed_email"}


def test_a_linkedin_field_that_is_not_linkedin_is_stripped() -> None:
    outcome = run(make(linkedin_url="https://twitter.com/rahul"))
    assert outcome.accepted[0].linkedin_url is None


def test_ungrounded_signal_is_dropped_without_losing_the_lead() -> None:
    """A good contact whose personalisation hook cannot be verified is still a
    good contact — the hook goes, not the person."""
    outcome = run(
        make(observed_signal="Opened 20 new stores", signal_source_url="https://made-up.com/news")
    )
    assert len(outcome.accepted) == 1
    assert outcome.accepted[0].observed_signal is None
    assert {s.reason for s in outcome.strips} == {"ungrounded_signal"}


def test_a_grounded_signal_is_kept_with_its_citation() -> None:
    outcome = run(
        make(
            observed_signal="Appointed a new head of supply chain",
            signal_source_url="https://trade-press.com/news/appointment",
        )
    )
    accepted = outcome.accepted[0]
    assert accepted.observed_signal
    assert accepted.signal_source_url == "https://trade-press.com/news/appointment"


def test_a_signal_with_no_citation_falls_back_to_the_lead_source() -> None:
    outcome = run(make(observed_signal="Launched a new capsule collection"))
    assert outcome.accepted[0].signal_source_url == "https://example-fashion.com/leadership"
