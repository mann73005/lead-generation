"""Discovery persistence: deduplication, company matching, ownership.

The agent loop itself is not exercised here — it needs the network. What is
tested is everything that decides whether model output becomes a row.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.discovery import _create_lead, _normalise_name, _upsert_company
from app.ai.schemas import ExtractedLead
from app.models import ICP, Company, DiscoveryRun, Lead, User
from app.models.enums import DiscoveryRunStatus


@pytest.fixture
def run(db: Session, icp: ICP) -> DiscoveryRun:
    record = DiscoveryRun(icp_id=icp.id, requested_count=5, status=DiscoveryRunStatus.RUNNING)
    db.add(record)
    db.flush()
    return record


def candidate(**overrides) -> ExtractedLead:
    base = {
        "first_name": "Preeti",
        "last_name": "Anand Raturi",
        "job_title": "Head of Merchandising",
        "source_url": "https://examplefashion.com/leadership",
        "company_name": "Example Fashion",
        "company_domain": "examplefashion.com",
    }
    return ExtractedLead(**{**base, **overrides})


# --------------------------------------------------------------------------
# Name normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Preeti Anand Raturi", "preeti anand raturi"),
        ("Jean-Luc Picard", "Jean Luc Picard"),
        ("Rahul  Sharma", "Rahul Sharma"),
        ("O'Brien, Sean", "OBrien Sean"),
    ],
)
def test_names_that_mean_the_same_person_normalise_alike(left: str, right: str) -> None:
    assert _normalise_name(left) == _normalise_name(right)


def test_different_people_do_not_collide() -> None:
    assert _normalise_name("Rahul Sharma") != _normalise_name("Rohit Sharma")


def test_initials_are_not_collapsed() -> None:
    """Deliberate: folding "A K Sharma" into "AK Sharma" would also merge two
    different people whose names start alike. The bug this guards against is a
    differently split name, not a differently punctuated initial."""
    assert _normalise_name("A. K. Sharma") != _normalise_name("AK Sharma")


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------


def test_the_same_person_is_not_stored_twice(
    db: Session, company: Company, run: DiscoveryRun
) -> None:
    assert _create_lead(db, company, candidate(), run, model="test") is True
    assert _create_lead(db, company, candidate(), run, model="test") is False
    assert db.scalar(select(Lead).where(Lead.company_id == company.id)) is not None


def test_a_differently_split_name_is_still_the_same_person(
    db: Session, company: Company, run: DiscoveryRun
) -> None:
    """Regression: two runs over one page produced "Preeti Anand"/"Raturi" and
    "Preeti"/"Anand Raturi". Comparing the fields separately read those as two
    people and the console showed the lead twice.

    Where a name is split is a decision the model makes, not a fact about the
    person, so the whole name is the key.
    """
    _create_lead(db, company, candidate(first_name="Preeti", last_name="Anand Raturi"), run, model="t")
    created = _create_lead(
        db, company, candidate(first_name="Preeti Anand", last_name="Raturi"), run, model="t"
    )

    assert created is False
    leads = db.scalars(select(Lead).where(Lead.company_id == company.id)).all()
    assert len(leads) == 1


def test_a_second_sighting_backfills_a_missing_email(
    db: Session, company: Company, run: DiscoveryRun
) -> None:
    """Most pages do not publish an address. When a later run finds one, it is
    worth keeping even though the lead already exists."""
    _create_lead(db, company, candidate(email=None), run, model="t")
    _create_lead(db, company, candidate(email="preeti@examplefashion.com"), run, model="t")

    lead = db.scalar(select(Lead).where(Lead.company_id == company.id))
    assert lead is not None
    assert lead.email == "preeti@examplefashion.com"


def test_two_different_people_at_one_company_both_persist(
    db: Session, company: Company, run: DiscoveryRun
) -> None:
    _create_lead(db, company, candidate(first_name="Preeti", last_name="Raturi"), run, model="t")
    _create_lead(db, company, candidate(first_name="Rohit", last_name="Kumar"), run, model="t")

    leads = db.scalars(select(Lead).where(Lead.company_id == company.id)).all()
    assert len(leads) == 2


def test_a_discovered_lead_inherits_the_profile_owner(
    db: Session, company: Company, run: DiscoveryRun, user: User
) -> None:
    _create_lead(db, company, candidate(), run, model="t", icp_owner_id=user.id)
    lead = db.scalar(select(Lead).where(Lead.company_id == company.id))
    assert lead is not None
    assert lead.owner_id == user.id


# --------------------------------------------------------------------------
# Company matching
# --------------------------------------------------------------------------


def test_a_company_is_matched_on_domain_not_recreated(db: Session, company: Company) -> None:
    matched, created = _upsert_company(
        db, candidate(company_name="Example Fashion Limited"), model="t"
    )
    assert created is False
    assert matched.id == company.id


def test_a_company_is_matched_on_name_when_no_domain_is_known(db: Session, company: Company) -> None:
    matched, created = _upsert_company(
        db, candidate(company_name="example fashion", company_domain=None), model="t"
    )
    assert created is False
    assert matched.id == company.id


def test_an_unknown_company_is_created(db: Session) -> None:
    matched, created = _upsert_company(
        db,
        candidate(company_name="Brand New Apparel", company_domain="brandnewapparel.com"),
        model="t",
    )
    assert created is True
    assert matched.name == "Brand New Apparel"


def test_matching_backfills_blanks_but_does_not_overwrite(db: Session, company: Company) -> None:
    """A later run that happened to read a thinner page must not degrade an
    established record."""
    original_industry = company.industry
    company.employee_count = None
    db.flush()

    matched, _ = _upsert_company(
        db,
        candidate(company_industry="Something Else", company_employee_count=900),
        model="t",
    )
    assert matched.industry == original_industry  # kept
    assert matched.employee_count == 900  # backfilled
