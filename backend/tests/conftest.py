"""Test fixtures.

Each test runs inside a transaction that is rolled back afterwards, so the
suite exercises the real PostgreSQL schema — constraints, cascades and all —
without leaving anything behind in the database.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.core.security import hash_password
from app.main import app
from app.models import ICP, Company, Lead, User
from app.models.enums import UserRole
from app.providers.mocks import MockEmailProvider, MockLLMProvider
from app.services.lead_scores import apply_score

TEST_PASSWORD = "test-password-123"


@pytest.fixture(autouse=True)
def no_live_providers(monkeypatch):
    """Keep the suite off the network.

    Without this, generating a draft calls Gemini for real: the run took three
    and a half minutes and spent quota from a 20-requests-per-day allowance.
    Tests assert on our own logic, so the model is replaced everywhere it is
    reached. A test that wants a specific model response injects its own mock.
    """
    monkeypatch.setattr("app.services.outreach.get_llm_provider", lambda: MockLLMProvider())
    monkeypatch.setattr("app.providers.get_llm_provider", lambda: MockLLMProvider())
    monkeypatch.setattr("app.services.outreach.get_email_provider", lambda: MockEmailProvider())


@pytest.fixture(scope="session")
def connection():
    conn = engine.connect()
    yield conn
    conn.close()


@pytest.fixture
def db(connection) -> Iterator[Session]:
    outer = connection.begin()
    # create_savepoint lets the application code call commit() normally while
    # the outer transaction still rolls everything back at teardown.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(db: Session) -> User:
    """The default actor: an administrator.

    Most tests are about lead handling rather than visibility, and an admin
    sees everything, which keeps them focused. Role scoping has its own tests
    in test_roles.py using the `member` fixture below.
    """
    record = User(
        email="tester@stylesense.ai",
        hashed_password=hash_password(TEST_PASSWORD),
        role=UserRole.ADMIN,
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def member(db: Session) -> User:
    record = User(
        email="member@stylesense.ai",
        hashed_password=hash_password(TEST_PASSWORD),
        role=UserRole.MEMBER,
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def member_auth(client: TestClient, member: User) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": member.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client: TestClient, user: User) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def icp(db: Session) -> ICP:
    record = ICP(
        name="Fashion India",
        industry="Fashion",
        region="India",
        employee_min=10,
        employee_max=500,
        titles=["Head of Merchandising", "Demand Planning"],
        keywords=[],
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def company(db: Session) -> Company:
    record = Company(
        name="Example Fashion",
        domain="examplefashion.com",
        industry="Fashion",
        region="India",
        employee_count=250,
        source_url="https://examplefashion.com/about",
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def lead(db: Session, company: Company, user: User) -> Lead:
    record = Lead(
        owner_id=user.id,
        company_id=company.id,
        first_name="Rahul",
        last_name="Sharma",
        job_title="Head of Merchandising",
        email="rahul@examplefashion.com",
        source_url="https://examplefashion.com/team",
    )
    db.add(record)
    db.flush()
    # Mirrors POST /leads, which scores on creation — a fixture lead with no
    # score row would be a state the API never actually produces.
    apply_score(db, record, reason="Lead created")
    return record
