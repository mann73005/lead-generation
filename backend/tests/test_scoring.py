"""Scoring engine tests.

These run without a database: the engine is a pure function, so the ORM
objects are built in memory and never flushed.
"""

import pytest

from app.models import Company, EmailEvent, Lead
from app.models.enums import EmailEventType, LeadStatus
from app.models.icp import ICP
from app.services.scoring import (
    ScoringConfig,
    compute_score,
    derive_status,
    load_scoring_config,
    match_title,
)


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


@pytest.fixture
def icp() -> ICP:
    return ICP(
        name="Fashion India",
        industry="Fashion",
        region="India",
        employee_min=10,
        employee_max=500,
        titles=["Head of Merchandising", "Demand Planning", "Supply Chain"],
    )


@pytest.fixture
def company() -> Company:
    return Company(
        name="Example Fashion",
        industry="Fashion & Apparel Retail",
        region="India",
        employee_count=250,
        source_url="https://example.com/about",
    )


@pytest.fixture
def lead(company: Company) -> Lead:
    return Lead(
        first_name="Rahul",
        last_name="Sharma",
        job_title="Head of Merchandising",
        email="rahul@example.com",
        linkedin_url="https://linkedin.com/in/example",
        source_url="https://example.com/team",
        company=company,
    )


def events(*types: str) -> list[EmailEvent]:
    return [EmailEvent(event_type=t) for t in types]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_config_loads_and_validates(config: ScoringConfig) -> None:
    assert config.fit.max + config.engagement.max <= 100
    assert config.bands.hot > config.bands.warm > config.bands.cold


def test_config_rejects_ceilings_that_exceed_100() -> None:
    """A miswritten config must fail at load time, not silently compress ranks."""
    base = load_scoring_config().model_dump()
    base["fit"]["max"] = 80
    base["engagement"]["max"] = 40
    with pytest.raises(ValueError, match="exceeds 100"):
        ScoringConfig.model_validate(base)


# --------------------------------------------------------------------------
# Title matching
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job_title", "expected"),
    [
        ("Head of Merchandising", "exact"),
        ("Head of Merchandising, India", "exact"),
        ("Senior Demand Planning Manager", "exact"),
        ("Merchandising Manager", "partial"),
        ("Supply Chain Analyst", "exact"),
        ("Chief Marketing Officer", None),
        ("Software Engineer", None),
        ("", None),
        (None, None),
    ],
)
def test_match_title(job_title: str | None, expected: str | None, icp: ICP) -> None:
    assert match_title(job_title, icp.titles) == expected


def test_title_stopwords_do_not_create_false_partials(icp: ICP) -> None:
    """"Head of Marketing" shares only the word "head" with the targets."""
    assert match_title("Head of Marketing", icp.titles) is None


# --------------------------------------------------------------------------
# Fit
# --------------------------------------------------------------------------


def test_perfect_fit_with_no_engagement(lead: Lead, company: Company, icp: ICP) -> None:
    result = compute_score(lead, company, icp)
    # 20 industry + 12 region + 8 size + 15 title + 3 email + 2 linkedin = 60
    assert result.fit_score == 60
    assert result.engagement_score == 0
    assert result.total_score == 60
    assert result.status is LeadStatus.NEW


def test_fit_is_capped_at_configured_max(lead: Lead, company: Company, icp: ICP, config: ScoringConfig) -> None:
    result = compute_score(lead, company, icp, config=config)
    assert result.fit_score <= config.fit.max


def test_unrelated_lead_scores_near_zero(icp: ICP) -> None:
    company = Company(name="Acme Steel", industry="Metals", region="Germany", employee_count=9000, source_url="https://acme.de")
    lead = Lead(first_name="Hans", job_title="Software Engineer", source_url="https://acme.de/team", company=company)
    result = compute_score(lead, company, icp)
    assert result.total_score == 0
    assert result.breakdown["fit"] == {}


def test_company_size_outside_band_loses_only_that_component(lead: Lead, icp: ICP) -> None:
    company = Company(name="Tiny Fashion", industry="Fashion", region="India", employee_count=4, source_url="https://x.com")
    result = compute_score(lead, company, icp)
    assert "company_size_match" not in result.breakdown["fit"]
    assert "industry_match" in result.breakdown["fit"]


def test_no_icp_awards_only_contactability(lead: Lead, company: Company, config: ScoringConfig) -> None:
    """Without an ICP, "matches the target industry" is unanswerable, not true.

    Regression guard: an earlier version read employee_min/employee_max off a
    missing ICP as `None`, read that as an unbounded band, and handed every
    company the size points for free.
    """
    result = compute_score(lead, company, icp=None)
    assert set(result.breakdown["fit"]) <= {"has_email", "has_linkedin"}
    assert result.fit_score == config.fit.weights.has_email + config.fit.weights.has_linkedin


def test_icp_with_no_size_band_awards_no_size_points(lead: Lead, company: Company) -> None:
    unbounded = ICP(
        name="Loose", industry="Fashion", region="India",
        employee_min=None, employee_max=None, titles=["Head of Merchandising"],
    )
    result = compute_score(lead, company, unbounded)
    assert "company_size_match" not in result.breakdown["fit"]


def test_missing_email_reduces_fit(company: Company, icp: ICP) -> None:
    with_email = Lead(first_name="A", job_title="Head of Merchandising", email="a@x.com", source_url="https://x.com", company=company)
    without = Lead(first_name="B", job_title="Head of Merchandising", source_url="https://x.com", company=company)
    assert compute_score(with_email, company, icp).fit_score > compute_score(without, company, icp).fit_score


# --------------------------------------------------------------------------
# Engagement
# --------------------------------------------------------------------------


def test_engagement_accumulates_through_the_funnel(lead: Lead, company: Company, icp: ICP) -> None:
    scores = [
        compute_score(lead, company, icp, events(*seq)).engagement_score
        for seq in (
            (),
            (EmailEventType.SENT,),
            (EmailEventType.SENT, EmailEventType.DELIVERED),
            (EmailEventType.SENT, EmailEventType.DELIVERED, EmailEventType.OPENED),
            (EmailEventType.SENT, EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.REPLIED),
        )
    ]
    assert scores == sorted(scores), f"engagement must be monotonic through the funnel, got {scores}"
    assert scores[0] == 0
    assert scores[-1] > scores[0]


def test_sent_alone_scores_no_engagement(lead: Lead, company: Company, icp: ICP) -> None:
    """Sending is our action, not the lead's — it must not raise their score."""
    assert compute_score(lead, company, icp, events(EmailEventType.SENT)).engagement_score == 0


def test_repeat_opens_are_bonused_but_capped(lead: Lead, company: Company, icp: ICP, config: ScoringConfig) -> None:
    many = events(EmailEventType.DELIVERED, *([EmailEventType.OPENED] * 10))
    detail = compute_score(lead, company, icp, many).breakdown["engagement"]
    assert detail["repeat_opens"] == config.engagement.max_repeat_open_bonus


def test_repeat_opens_never_outrank_a_reply(lead: Lead, company: Company, icp: ICP) -> None:
    serial_opener = compute_score(lead, company, icp, events(EmailEventType.DELIVERED, *([EmailEventType.OPENED] * 10)))
    replier = compute_score(
        lead, company, icp, events(EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.REPLIED), reply_intent="interested"
    )
    assert replier.total_score > serial_opener.total_score


@pytest.mark.parametrize(
    ("intent", "direction"),
    [("interested", 1), ("needs_info", 1), ("not_now", -1), ("wrong_person", -1)],
)
def test_reply_intent_moves_the_score(lead: Lead, company: Company, icp: ICP, intent: str, direction: int) -> None:
    sequence = events(EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.REPLIED)
    neutral = compute_score(lead, company, icp, sequence).total_score
    with_intent = compute_score(lead, company, icp, sequence, reply_intent=intent).total_score
    assert (with_intent - neutral) * direction > 0


def test_engagement_never_goes_negative(lead: Lead, company: Company, icp: ICP) -> None:
    """A hostile reply must not claw back points earned by fit."""
    result = compute_score(
        lead, company, icp, events(EmailEventType.REPLIED), reply_intent="unsubscribe"
    )
    assert result.engagement_score >= 0


# --------------------------------------------------------------------------
# Status derivation and penalties
# --------------------------------------------------------------------------


def test_status_is_the_furthest_point_reached() -> None:
    assert derive_status(events(EmailEventType.SENT, EmailEventType.DELIVERED, EmailEventType.OPENED)) is LeadStatus.OPENED


def test_status_ignores_event_order() -> None:
    forward = events(EmailEventType.SENT, EmailEventType.DELIVERED, EmailEventType.OPENED)
    assert derive_status(forward) is derive_status(list(reversed(forward)))


def test_unknown_event_types_are_ignored_not_fatal() -> None:
    assert derive_status(events(EmailEventType.OPENED, "not_a_real_event")) is LeadStatus.OPENED


def test_unsubscribe_zeroes_an_otherwise_perfect_lead(lead: Lead, company: Company, icp: ICP) -> None:
    result = compute_score(
        lead, company, icp, events(EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.UNSUBSCRIBED)
    )
    assert result.total_score == 0
    assert result.status is LeadStatus.UNSUBSCRIBED
    assert result.breakdown["penalty"] == "unsubscribed"


def test_bounce_caps_the_score(lead: Lead, company: Company, icp: ICP, config: ScoringConfig) -> None:
    result = compute_score(lead, company, icp, events(EmailEventType.BOUNCED))
    assert result.total_score == config.penalties.bounced
    assert result.breakdown["penalty"] == "bounced"


def test_total_stays_within_bounds(lead: Lead, company: Company, icp: ICP) -> None:
    result = compute_score(
        lead, company, icp,
        events(EmailEventType.DELIVERED, *([EmailEventType.OPENED] * 20), EmailEventType.REPLIED),
        reply_intent="interested",
    )
    assert 0 <= result.total_score <= 100


# --------------------------------------------------------------------------
# The property the brief actually cares about
# --------------------------------------------------------------------------


def test_scoring_is_deterministic(lead: Lead, company: Company, icp: ICP) -> None:
    sequence = events(EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.REPLIED)
    first = compute_score(lead, company, icp, sequence, reply_intent="interested")
    second = compute_score(lead, company, icp, sequence, reply_intent="interested")
    assert first == second


def test_score_is_independent_of_event_order(lead: Lead, company: Company, icp: ICP) -> None:
    """Replaying history out of order must not change the result.

    This is what makes "rebuild every score from email_events" safe.
    """
    sequence = events(EmailEventType.DELIVERED, EmailEventType.OPENED, EmailEventType.REPLIED)
    assert compute_score(lead, company, icp, sequence) == compute_score(lead, company, icp, list(reversed(sequence)))


def test_breakdown_explains_the_total(lead: Lead, company: Company, icp: ICP) -> None:
    """The console shows the breakdown as the reason for the score, so the
    parts have to actually add up to the whole."""
    result = compute_score(lead, company, icp, events(EmailEventType.DELIVERED, EmailEventType.OPENED))
    assert result.breakdown["fit_total"] + result.breakdown["engagement_total"] == result.total_score
    assert result.breakdown["penalty"] is None
