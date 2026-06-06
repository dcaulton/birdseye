from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from birdseye.db.models import Base
from birdseye.db.session import get_db
from birdseye.main import app

postgres_container = PostgresContainer(
    image="postgis/postgis:16-3.4", username="postgres", password="postgres", dbname="birdseye_test"
)

TestingSessionLocal = None
engine = None


@pytest.fixture(scope="session", autouse=True)  # type: ignore[misc]
def setup_test_database() -> Generator[None, None, None]:
    """Start PostGIS container once per test session."""
    postgres_container.start()
    connection_url = postgres_container.get_connection_url()

    global TestingSessionLocal, engine
    engine = create_engine(connection_url, echo=False)
    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db() -> Generator:  # type: ignore[type-arg]
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield

    postgres_container.stop()


@pytest.fixture  # type: ignore[misc]
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def db():
    """Yields a database session connected to the test PostGIS container.
    This fixture is intended for integration tests only.
    """
    if TestingSessionLocal is None:
        raise RuntimeError(
            "TestingSessionLocal is not initialized. Make sure setup_test_database ran first."
        )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
