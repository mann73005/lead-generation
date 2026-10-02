"""Role separation: what a member can see, and what only an admin can do.

These are the tests that make roles real rather than decorative. A console
where the filter is applied in the UI and not the API is not multi-user, it is
single-user with extra steps.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Company, Lead, User
from app.models.enums import UserRole
from app.services.lead_scores import apply_score

API = "/api/v1"


@pytest.fixture
def member_lead(db: Session, company: Company, member: User) -> Lead:
    record = Lead(
        owner_id=member.id,
        company_id=company.id,
        first_name="Meera",
        last_name="Owner",
        job_title="Head of Merchandising",
        email="meera@examplefashion.com",
        source_url="https://examplefashion.com/team",
    )
    db.add(record)
    db.flush()
    apply_score(db, record, reason="Lead created")
    return record


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------


def test_a_member_sees_only_their_own_leads(
    client: TestClient, member_auth: dict[str, str], member_lead: Lead, lead: Lead
) -> None:
    """`lead` belongs to the admin, `member_lead` to the member."""
    names = {
        item["first_name"]
        for item in client.get(f"{API}/leads?limit=100", headers=member_auth).json()["items"]
    }
    assert "Meera" in names
    assert "Rahul" not in names


def test_an_admin_sees_everybody_s_leads(
    client: TestClient, auth: dict[str, str], member_lead: Lead, lead: Lead
) -> None:
    names = {
        item["first_name"]
        for item in client.get(f"{API}/leads?limit=100", headers=auth).json()["items"]
    }
    assert {"Meera", "Rahul"} <= names


def test_fetching_another_users_lead_is_a_404_not_a_403(
    client: TestClient, member_auth: dict[str, str], lead: Lead
) -> None:
    """Distinguishing "not yours" from "does not exist" turns the endpoint
    into an oracle for which lead ids are real."""
    assert client.get(f"{API}/leads/{lead.id}", headers=member_auth).status_code == 404


def test_a_member_cannot_edit_another_users_lead(
    client: TestClient, member_auth: dict[str, str], lead: Lead
) -> None:
    response = client.patch(
        f"{API}/leads/{lead.id}", headers=member_auth, json={"job_title": "Hijacked"}
    )
    assert response.status_code == 404


def test_a_member_cannot_delete_another_users_lead(
    client: TestClient, member_auth: dict[str, str], lead: Lead
) -> None:
    assert client.delete(f"{API}/leads/{lead.id}", headers=member_auth).status_code == 404


def test_counts_respect_scope(
    client: TestClient, member_auth: dict[str, str], auth: dict[str, str],
    member_lead: Lead, lead: Lead,
) -> None:
    """The paging total has to be scoped too, or it leaks how many leads
    other people hold."""
    member_total = client.get(f"{API}/leads", headers=member_auth).json()["total"]
    admin_total = client.get(f"{API}/leads", headers=auth).json()["total"]
    assert admin_total > member_total


def test_a_new_lead_is_owned_by_its_creator(
    client: TestClient, member_auth: dict[str, str], auth: dict[str, str], company: Company
) -> None:
    created = client.post(
        f"{API}/leads",
        headers=member_auth,
        json={
            "company_id": str(company.id),
            "first_name": "Fresh",
            "job_title": "Demand Planning",
            "source_url": "https://examplefashion.com/team",
        },
    )
    assert created.status_code == 201
    # Visible to its creator...
    assert client.get(f"{API}/leads/{created.json()['id']}", headers=member_auth).status_code == 200
    # ...and to an admin.
    assert client.get(f"{API}/leads/{created.json()['id']}", headers=auth).status_code == 200


def test_icps_and_campaigns_are_scoped_too(
    client: TestClient, member_auth: dict[str, str], auth: dict[str, str]
) -> None:
    admin_icp = client.post(
        f"{API}/icps",
        headers=auth,
        json={
            "name": "Admin ICP",
            "industry": "Fashion",
            "region": "India",
            "titles": ["Head of Merchandising"],
        },
    ).json()

    assert client.get(f"{API}/icps/{admin_icp['id']}", headers=member_auth).status_code == 404
    member_names = {i["name"] for i in client.get(f"{API}/icps", headers=member_auth).json()["items"]}
    assert "Admin ICP" not in member_names


def test_a_member_cannot_run_discovery_on_another_users_icp(
    client: TestClient, member_auth: dict[str, str], auth: dict[str, str]
) -> None:
    icp = client.post(
        f"{API}/icps",
        headers=auth,
        json={
            "name": "Private ICP",
            "industry": "Fashion",
            "region": "India",
            "titles": ["Supply Chain"],
        },
    ).json()
    response = client.post(
        f"{API}/discovery/run", headers=member_auth, json={"icp_id": icp["id"], "count": 1}
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Account management
# --------------------------------------------------------------------------


def test_only_an_admin_can_list_users(
    client: TestClient, auth: dict[str, str], member_auth: dict[str, str]
) -> None:
    assert client.get(f"{API}/users", headers=auth).status_code == 200

    forbidden = client.get(f"{API}/users", headers=member_auth)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_an_admin_can_create_a_user_who_can_then_log_in(
    client: TestClient, auth: dict[str, str]
) -> None:
    created = client.post(
        f"{API}/users",
        headers=auth,
        json={
            "email": "newhire@stylesense.ai",
            "password": "a-strong-password",
            "full_name": "New Hire",
            "role": "member",
        },
    )
    assert created.status_code == 201
    assert created.json()["role"] == UserRole.MEMBER

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "newhire@stylesense.ai", "password": "a-strong-password"},
    )
    assert login.status_code == 200


def test_a_member_cannot_create_users(
    client: TestClient, member_auth: dict[str, str]
) -> None:
    response = client.post(
        f"{API}/users",
        headers=member_auth,
        json={"email": "sneaky@stylesense.ai", "password": "a-strong-password"},
    )
    assert response.status_code == 403


def test_duplicate_emails_are_rejected(client: TestClient, auth: dict[str, str], member: User) -> None:
    response = client.post(
        f"{API}/users",
        headers=auth,
        json={"email": member.email, "password": "a-strong-password"},
    )
    assert response.status_code == 409


def test_short_passwords_are_rejected(client: TestClient, auth: dict[str, str]) -> None:
    response = client.post(
        f"{API}/users", headers=auth, json={"email": "weak@stylesense.ai", "password": "short"}
    )
    assert response.status_code == 422


def test_an_admin_cannot_lock_themselves_out(
    client: TestClient, auth: dict[str, str], user: User
) -> None:
    """Both self-deactivation and self-demotion would leave the console with
    no way back in."""
    assert (
        client.patch(f"{API}/users/{user.id}", headers=auth, json={"is_active": False}).status_code
        == 403
    )
    assert (
        client.patch(f"{API}/users/{user.id}", headers=auth, json={"role": "member"}).status_code
        == 403
    )


def test_deactivating_a_user_stops_their_tokens_working(
    client: TestClient, auth: dict[str, str], member: User, member_auth: dict[str, str]
) -> None:
    """Checked against the database on every request, so revocation is
    immediate rather than waiting for the token to expire."""
    assert client.get(f"{API}/leads", headers=member_auth).status_code == 200

    client.patch(f"{API}/users/{member.id}", headers=auth, json={"is_active": False})
    assert client.get(f"{API}/leads", headers=member_auth).status_code == 401


def test_updating_an_unknown_user_404s(client: TestClient, auth: dict[str, str]) -> None:
    assert client.patch(f"{API}/users/{uuid4()}", headers=auth, json={}).status_code == 404


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


def test_dashboard_scope_differs_by_role(
    client: TestClient, auth: dict[str, str], member_auth: dict[str, str],
    member_lead: Lead, lead: Lead,
) -> None:
    admin_view = client.get(f"{API}/dashboard", headers=auth).json()
    member_view = client.get(f"{API}/dashboard", headers=member_auth).json()

    assert admin_view["scope"] == "all"
    assert member_view["scope"] == "own"
    assert admin_view["total_leads"] > member_view["total_leads"]
    # Per-user breakdown is an admin concern only.
    assert admin_view["by_owner"]
    assert member_view["by_owner"] == []


def test_dashboard_bands_add_up(client: TestClient, auth: dict[str, str], lead: Lead) -> None:
    view = client.get(f"{API}/dashboard", headers=auth).json()
    assert view["hot"] + view["warm"] + view["cold"] == view["total_leads"]
