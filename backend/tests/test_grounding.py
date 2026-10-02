"""Tests for the grounding check and the template renderer.

The brief asks for "one programmatic check that blocks a token being filled
with an unverifiable claim". These tests are what say it actually blocks.
"""

import pytest

from app.ai.email_builder import render, resolve_tokens
from app.ai.grounding import build_evidence, check_claim
from app.core.policy import load_product_config
from app.models import Company, Lead

SIGNAL = "TechnoSport has appointed Sachin Tandon to head its supply chain operations."


@pytest.fixture
def company() -> Company:
    return Company(
        name="TechnoSport",
        industry="Fashion",
        region="Asia",
        employee_count=400,
        description="activewear and performance apparel brand",
        source_url="https://example-news.com/appointment",
    )


@pytest.fixture
def lead(company: Company) -> Lead:
    return Lead(
        first_name="Sachin",
        last_name="Tandon",
        job_title="Supply Chain Head",
        email="sachin@technosport.example.com",
        source_url="https://example-news.com/appointment",
        company=company,
        raw_data={
            "observed_signal": {
                "text": SIGNAL,
                "source_url": "https://example-news.com/appointment",
            }
        },
    )


@pytest.fixture
def evidence(lead: Lead, company: Company):
    return build_evidence(lead, company)


# --------------------------------------------------------------------------
# What the check lets through
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "TechnoSport appointed a new head of supply chain operations",
        "you lead supply chain operations at TechnoSport",
        "it may be worth looking at how stock moves between channels",
        "your 400-person business",
    ],
)
def test_claims_supported_by_stored_data_pass(claim: str, evidence) -> None:
    assert check_claim(claim, evidence).grounded


def test_ordinary_prose_is_not_second_guessed() -> None:
    """The check polices specifics, not fluency — it must not reject a
    sentence merely for containing words."""
    from app.ai.grounding import Evidence

    thin = Evidence(fields={"company.name": "Acme"})
    assert check_claim("it may be worth exploring whether this helps", thin).grounded


# --------------------------------------------------------------------------
# What it blocks — the whole point
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        # The brief's own example of an unverifiable claim.
        ("TechnoSport recently opened 20 new stores", "20"),
        ("your team manages 1,200 SKUs", "1,200"),
        ("returns fell by 18% last year", "18"),
        ("TechnoSport raised $40M in funding", "40"),
    ],
)
def test_numbers_absent_from_the_evidence_are_blocked(claim, expected, evidence) -> None:
    verdict = check_claim(claim, evidence)
    assert not verdict.grounded
    assert expected in verdict.unsupported


@pytest.mark.parametrize(
    "claim",
    [
        "TechnoSport partnered with Reliance Retail",
        "your expansion into Singapore",
        "the launch of Flying Machine",
    ],
)
def test_proper_nouns_absent_from_the_evidence_are_blocked(claim: str, evidence) -> None:
    assert not check_claim(claim, evidence).grounded


def test_a_number_that_does_appear_is_allowed(evidence) -> None:
    """400 is the stored headcount, so a claim using it is checkable."""
    assert check_claim("your 400 employees", evidence).grounded


def test_commas_in_numbers_do_not_cause_false_blocks() -> None:
    from app.ai.grounding import Evidence

    assert check_claim("1,200 stores", Evidence(fields={"c": "1200 stores"})).grounded
    assert check_claim("1200 stores", Evidence(fields={"c": "1,200 stores"})).grounded


def test_an_empty_value_is_never_grounded(evidence) -> None:
    assert not check_claim("", evidence).grounded
    assert not check_claim("   ", evidence).grounded


# --------------------------------------------------------------------------
# Rendering: a blocked token costs its sentence, not the whole email
# --------------------------------------------------------------------------


def test_a_full_email_renders_from_stored_data(lead: Lead, company: Company) -> None:
    profile = load_product_config()
    tokens = resolve_tokens(lead, company, profile, sender_name="Test Sender", llm=None)
    email = render(profile.template, tokens)

    assert email.subject
    assert "Hi Sachin," in email.body_text
    assert "I noticed" in email.body_text
    assert email.grounding_report["blocked"] == 0
    # No proof point is stored, so the P.S. is omitted rather than invented.
    assert "P.S." not in email.body_text


def test_no_stored_signal_drops_only_that_sentence(company: Company) -> None:
    bare = Lead(
        first_name="Asha",
        job_title="Head of Merchandising",
        source_url="https://example-news.com/team",
        company=company,
        raw_data={},
    )
    profile = load_product_config()
    email = render(
        profile.template,
        resolve_tokens(bare, company, profile, sender_name="Test Sender", llm=None),
    )

    assert "I noticed" not in email.body_text
    assert any("signal" in d for d in email.dropped_sentences)
    # The rest of the email survives: greeting, value proposition, ask, sign-off.
    assert "Hi Asha," in email.body_text
    assert "Would you be open to" in email.body_text


def test_optional_tokens_are_omitted_without_leaving_punctuation(
    lead: Lead, company: Company
) -> None:
    profile = load_product_config()
    email = render(
        profile.template,
        resolve_tokens(lead, company, profile, sender_name="Test Sender", llm=None),
    )
    assert " - ." not in email.body_text
    assert "{{" not in email.body_text
    # Checked line by line: paragraphs are joined with a blank line, so
    # flattening newlines first would manufacture the double space.
    for line in email.body_text.splitlines():
        assert "  " not in line, line
        assert not line.strip().startswith(("-", ",", ".")), line


def test_template_skeleton_is_never_reworded(lead: Lead, company: Company) -> None:
    """The locked copy from Appendix A must survive verbatim."""
    profile = load_product_config()
    email = render(
        profile.template,
        resolve_tokens(lead, company, profile, sender_name="Test Sender", llm=None),
    )
    assert "At StyleSense AI, we help apparel and fashion" in email.body_text
    assert "Would you be open to a 15-minute call" in email.body_text
    assert email.body_text.rstrip().endswith("StyleSense AI")


def test_every_token_records_its_provenance(lead: Lead, company: Company) -> None:
    """Each filled token has to say where it came from — that is what makes the
    generated email auditable after the fact."""
    profile = load_product_config()
    tokens = resolve_tokens(lead, company, profile, sender_name="Test Sender", llm=None)

    filled = {name: t for name, t in tokens.items() if t.value}
    assert filled
    for name, token in filled.items():
        assert token.origin in {"field", "config", "derived", "model"}, name
