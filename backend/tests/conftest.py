import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import Principal, principal
from app.db import database
from app.main import app
from app.models import Base, Tenant


@pytest.fixture
def system(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    options = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool} if url == "sqlite://" else {}
    engine = create_engine(url, **options)
    if url == "sqlite://":
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([Tenant(id="alpha", name="Alpha"), Tenant(id="beta", name="Beta")])
        session.commit()

    def session_dependency():
        with factory() as session:
            yield session

    monkeypatch.setattr("app.main.session_factory", lambda: factory)
    app.dependency_overrides[database] = session_dependency
    user = Principal("operator-a", {"operator", "approver"}, {"alpha"})
    app.dependency_overrides[principal] = lambda: user
    with TestClient(app) as client:
        yield client, user, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def enrolled(system):
    client, user, factory = system
    token = client.post("/api/tenants/alpha/enrollments").json()["token"]
    device = client.post("/api/agent/enroll", json={"token": token, "hostname": "PC-01", "os_version": "Windows 11"}).json()
    headers = {"Authorization": "Bearer " + device["token"]}
    return client, user, factory, device["device_id"], headers


@pytest.fixture
def approved(enrolled):
    client, user, factory, device_id, headers = enrolled
    definition = client.post("/api/tenants/alpha/definitions", json={"name": "Inventory", "kind": "powershell", "script": "Write-Output 'ok'"}).json()
    user.subject = "approver-b"
    response = client.post(f"/api/tenants/alpha/definitions/{definition['id']}/approve")
    assert response.status_code == 200
    return client, user, factory, device_id, headers, definition["id"]
