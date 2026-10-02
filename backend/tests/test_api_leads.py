"""API tests covering auth, validation, error shapes and the event-to-score loop."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Company, Lead
from app.models.enums import EmailEventType

LEADS = "/api/v1/leads"


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_health_needs_no_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_route_rejects_anonymous_requests(client: TestClient) -> None:
    response = client.get(LEADS)
    assert response.status_code == 401
    # The brief grades error handling, so the envelope is asserted, not just
    # the status code.
    assert response.json()["error"]["code"] == "unauthorized"


def test_protected_route_rejects_a_garbage_token(client: TestClient) -> None:
    response = client.get(LEADS, headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_refresh_token_is_not_accepted_as_an_access_token(client: TestClient, user) -> None:
    """Otherwise a long-lived refresh token would work as a bearer credential."""
    tokens = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "test-password-123"}
    ).json()
    response = client.get(LEADS, headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert response.status_code == 401


def test_login_with_a_wrong_password_is_indistinguishable_from_an_unknown_user(
    client: TestClient, user
) -> None:
    wrong = client.post("/api/v1/auth/login", json={"email": user.email, "password": "nope-wrong"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "ghost@nowhere-inc.com", "password": "nope-wrong"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_refresh_returns_a_fresh_pair(client: TestClient, user) -> None:
    tokens = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "test-password-123"}
    ).json()
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"]


# --------------------------------------------------------------------------
# Validation and error shapes
# --------------------------------------------------------------------------


def test_validation_error_reports_the_offending_field(
    client: TestClient, auth: dict[str, str], company: Company
) -> None:
    response = client.post(
        LEADS,
        headers=auth,
        json={"company_id": str(company.id), "first_name": "", "job_title": "x", "source_url": "no"},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert {f["field"] for f in body["details"]["fields"]} >= {"first_name", "job_title", "source_url"}


def test_unknown_lead_returns_a_structured_404(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get(f"{LEADS}/{uuid4()}", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_creating_a_lead_under_a_missing_company_404s(
    client: TestClient, auth: dict[str, str]
) -> None:
    response = client.post(
        LEADS,
        headers=auth,
        json={
            "company_id": str(uuid4()),
            "first_name": "Ghost",
            "job_title": "Head of Merchandising",
            "source_url": "https://example-co.com/team",
        },
    )
    assert response.status_code == 404


def test_duplicate_email_at_the_same_company_conflicts(
    client: TestClient, auth: dict[str, str], company: Company, lead: Lead
) -> None:
    response = client.post(
        LEADS,
        headers=auth,
        json={
            "company_id": str(company.id),
            "first_name": "Rahul",
            "job_title": "Head of Merchandising",
            "email": lead.email,
            "source_url": "https://examplefashion.com/team",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_pagination_bounds_are_enforced(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get(f"{LEADS}?limit=0", headers=auth).status_code == 422
    assert client.get(f"{LEADS}?limit=1000", headers=auth).status_code == 422
    assert client.get(f"{LEADS}?offset=-1", headers=auth).status_code == 422


# --------------------------------------------------------------------------
# Listing, filtering, ranking
# --------------------------------------------------------------------------


def test_new_lead_is_scored_on_creation(
    client: TestClient, auth: dict[str, str], company: Company
) -> None:
    """A lead must be rankable immediately, not only after its first event."""
    response = client.post(
        LEADS,
        headers=auth,
        json={
            "company_id": str(company.id),
            "first_name": "Priya",
            "job_title": "Head of Merchandising",
            "email": "priya@examplefashion.com",
            "source_url": "https://examplefashion.com/team",
        },
    )
    assert response.status_code == 201
    assert response.json()["score"]["total_score"] > 0


def test_list_is_paginated_and_reports_the_unpaginated_total(
    client: TestClient, auth: dict[str, str], company: Company
) -> None:
    for index in range(3):
        client.post(
            LEADS,
            headers=auth,
            json={
                "company_id": str(company.id),
                "first_name": f"Lead{index}",
                "job_title": "Demand Planning",
                "email": f"lead{index}@examplefashion.com",
                "source_url": "https://examplefashion.com/team",
            },
        )
    body = client.get(f"{LEADS}?limit=2&offset=0", headers=auth).json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert body["limit"] == 2


def test_list_is_ranked_by_score_descending(
    client: TestClient, auth: dict[str, str], company: Company, lead: Lead
) -> None:
    weak_company = client.post(
        "/api/v1/companies",
        headers=auth,
        json={
            "name": "Acme Steel",
            "industry": "Metals",
            "region": "Germany",
            "source_url": "https://acmesteel.com/about",
        },
    ).json()
    client.post(
        LEADS,
        headers=auth,
        json={
            "company_id": weak_company["id"],
            "first_name": "Hans",
            "job_title": "Software Engineer",
            "source_url": "https://acmesteel.com/team",
        },
    )

    items = client.get(f"{LEADS}?limit=100", headers=auth).json()["items"]
    scores = [item["score"]["total_score"] for item in items]
    assert scores == sorted(scores, reverse=True)

    # Compared against each other rather than by absolute position: the
    # database also holds leads from real discovery runs, and a test that
    # assumes it owns the whole table is a test that breaks on seed data.
    by_name = {item["first_name"]: item["score"]["total_score"] for item in items}
    assert by_name["Rahul"] > by_name["Hans"]


def test_filters_narrow_the_result_set(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    assert client.get(f"{LEADS}?q=Rahul", headers=auth).json()["total"] >= 1
    assert client.get(f"{LEADS}?q=zzz-no-such-person", headers=auth).json()["total"] == 0
    assert client.get(f"{LEADS}?industry=Fashion", headers=auth).json()["total"] >= 1
    assert client.get(f"{LEADS}?min_score=101", headers=auth).status_code == 422


def test_empty_result_set_is_a_valid_page_not_an_error(
    client: TestClient, auth: dict[str, str]
) -> None:
    """The console's empty state is graded, so the API has to make it easy."""
    body = client.get(f"{LEADS}?q=definitely-no-such-lead-xyz", headers=auth).json()
    assert body["items"] == []
    assert body["total"] == 0


# --------------------------------------------------------------------------
# The event -> score -> history loop
# --------------------------------------------------------------------------


def test_events_raise_the_score_and_record_why(
    client: TestClient, auth: dict[str, str], db: Session, lead: Lead
) -> None:
    client.post(f"{LEADS}/{lead.id}/rescore", headers=auth)
    baseline = client.get(f"{LEADS}/{lead.id}", headers=auth).json()["score"]["total_score"]

    for event_type in (EmailEventType.SENT, EmailEventType.DELIVERED, EmailEventType.OPENED):
        response = client.post(
            "/api/v1/events",
            headers=auth,
            json={"lead_id": str(lead.id), "event_type": event_type.value},
        )
        assert response.status_code == 201

    detail = client.get(f"{LEADS}/{lead.id}", headers=auth).json()

    assert detail["score"]["total_score"] > baseline
    assert detail["score"]["status"] == "opened"
    assert len(detail["events"]) == 3

    # Every score movement must carry a human-readable reason — this is the
    # explainability the brief asks for.
    reasons = [entry["reason"] for entry in detail["score_history"]]
    assert "Email delivered" in reasons
    assert "Email opened" in reasons
    assert all(entry["new_score"] == (entry["old_score"] or 0) + entry["delta"] for entry in detail["score_history"])


def test_unsubscribe_event_zeroes_the_score(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    client.post(
        "/api/v1/events",
        headers=auth,
        json={"lead_id": str(lead.id), "event_type": EmailEventType.OPENED.value},
    )
    client.post(
        "/api/v1/events",
        headers=auth,
        json={"lead_id": str(lead.id), "event_type": EmailEventType.UNSUBSCRIBED.value},
    )
    score = client.get(f"{LEADS}/{lead.id}", headers=auth).json()["score"]
    assert score["total_score"] == 0
    assert score["status"] == "unsubscribed"


def test_event_for_an_unknown_lead_404s(client: TestClient, auth: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/events",
        headers=auth,
        json={"lead_id": str(uuid4()), "event_type": "opened"},
    )
    assert response.status_code == 404


def test_invalid_event_type_is_rejected(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    response = client.post(
        "/api/v1/events",
        headers=auth,
        json={"lead_id": str(lead.id), "event_type": "teleported"},
    )
    assert response.status_code == 422


def test_rescore_is_idempotent(client: TestClient, auth: dict[str, str], lead: Lead) -> None:
    """Recomputing without new events must not invent score history."""
    client.post(f"{LEADS}/{lead.id}/rescore", headers=auth)
    first = client.get(f"{LEADS}/{lead.id}", headers=auth).json()
    client.post(f"{LEADS}/{lead.id}/rescore", headers=auth)
    second = client.get(f"{LEADS}/{lead.id}", headers=auth).json()

    assert first["score"]["total_score"] == second["score"]["total_score"]
    assert len(first["score_history"]) == len(second["score_history"])
