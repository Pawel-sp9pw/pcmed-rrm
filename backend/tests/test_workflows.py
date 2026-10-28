import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from app.models import Audit, Device, Enrollment, Job, now


def queue(approved):
    client, user, factory, device_id, headers, definition_id = approved
    response = client.post("/api/tenants/alpha/jobs", json={"device_ids": [device_id], "definition_id": definition_id})
    assert response.status_code == 201
    return response.json()[0]["id"]


def test_enrollment_single_use_hashed_and_expires(system):
    client, user, factory = system
    response = client.post("/api/tenants/alpha/enrollments")
    token = response.json()["token"]
    payload = {"token": token, "hostname": "PC", "os_version": "Windows"}
    with factory() as session:
        record = session.scalar(select(Enrollment))
        assert record.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert record.expires_at > now()
    enrolled = client.post("/api/agent/enroll", json=payload)
    assert enrolled.status_code == 201
    assert client.post("/api/agent/enroll", json=payload).status_code == 401
    expired = client.post("/api/tenants/alpha/enrollments").json()["token"]
    with factory() as session:
        record = session.scalar(select(Enrollment).where(Enrollment.used.is_(False)))
        record.expires_at = now() - 1
        session.commit()
    assert client.post("/api/agent/enroll", json=payload | {"token": expired}).status_code == 401


@pytest.mark.parametrize("resource", ["devices", "definitions", "jobs", "gateways", "audit"])
def test_cross_client_reads_denied(system, resource):
    client, *_ = system
    assert client.get(f"/api/tenants/beta/{resource}").status_code == 403
    assert [tenant["id"] for tenant in client.get("/api/tenants").json()] == ["alpha"]


def test_viewer_cannot_write(system):
    client, user, _ = system
    user.roles = {"viewer"}
    assert client.post("/api/tenants/alpha/enrollments").status_code == 403
    assert client.post("/api/tenants", json={"name": "Hidden"}).status_code == 403


def test_approval_is_separate_person_and_immutable(enrolled):
    client, user, _, device_id, _ = enrolled
    definition = client.post("/api/tenants/alpha/definitions", json={"name": "Script", "kind": "bat", "script": "echo ok"}).json()
    path = f"/api/tenants/alpha/definitions/{definition['id']}"
    assert client.post(path + "/approve").status_code == 403
    assert client.post("/api/tenants/alpha/jobs", json={"device_ids": [device_id], "definition_id": definition["id"]}).status_code == 409
    assert client.patch(path, json={"script": "changed"}).status_code == 404
    assert definition["spec"]["sha256"] == hashlib.sha256(b"echo ok").hexdigest()
    user.subject = "second-person"
    assert client.post(path + "/approve").status_code == 200
    assert client.post(path + "/approve").status_code == 409


def test_invalid_installer_and_extra_fields(system):
    client, *_ = system
    base = {"name": "Installer", "kind": "exe", "sha256": "a" * 64}
    for url in ("http://packages.example.test/a.exe", "https://evil.test/a.exe", "https://packages.example.test@evil.test/a.exe"):
        assert client.post("/api/tenants/alpha/definitions", json=base | {"url": url}).status_code == 422
    assert client.post("/api/tenants/alpha/definitions", json=base | {"url": "https://packages.example.test/a.exe", "shell": True}).status_code == 422


def test_claim_result_idempotency_and_no_replay(approved):
    job_id = queue(approved)
    client, user, factory, device_id, headers, _ = approved
    claim = client.post("/api/agent/next", headers=headers).json()
    assert claim["id"] == job_id
    assert client.post("/api/agent/next", headers=headers).status_code == 204
    body = {"claim": claim["claim"], "state": "succeeded", "exit_code": 0, "output": "ok"}
    assert client.post(f"/api/agent/results/{job_id}", headers=headers, json=body).status_code == 200
    assert client.post(f"/api/agent/results/{job_id}", headers=headers, json=body).status_code == 200
    assert client.post(f"/api/agent/results/{job_id}", headers=headers, json=body | {"output": "changed"}).status_code == 409
    assert client.post("/api/agent/next", headers=headers).status_code == 204
    with factory() as session:
        actions = list(session.scalars(select(Audit.action)))
        assert actions.count("job.succeeded") == 1
        assert "job.claimed" in actions
        assert session.get(Device, device_id).token_hash != headers["Authorization"].split()[1]


def test_lost_claim_becomes_unknown_and_can_receive_late_result(approved):
    job_id = queue(approved)
    client, _, factory, _, headers, _ = approved
    claim = client.post("/api/agent/next", headers=headers).json()
    with factory() as session:
        session.get(Job, job_id).deadline = now() - 1
        session.commit()
    assert client.post("/api/agent/next", headers=headers).status_code == 204
    assert client.get("/api/tenants/alpha/jobs").json()[0]["state"] == "unknown"
    assert client.post(f"/api/agent/results/{job_id}", headers=headers,
                       json={"claim": claim["claim"], "state": "unknown", "output": "restart"}).status_code == 200


def test_gateway_scoped_and_revocable(enrolled):
    client, user, factory, _, headers = enrolled
    relay = client.post("/api/tenants/alpha/gateways", json={"name": "LAN"}).json()
    via_relay = headers | {"X-PCMED-Gateway": relay["token"]}
    assert client.post("/api/agent/heartbeat", headers=via_relay, json={"agent_version": "0.1"}).status_code == 200
    user.roles = {"platform_admin"}
    other = client.post("/api/tenants/beta/gateways", json={"name": "Other"}).json()
    assert client.post("/api/agent/heartbeat", headers=headers | {"X-PCMED-Gateway": other["token"]}, json={"agent_version": "0.1"}).status_code == 403
    token = client.post("/api/tenants/alpha/enrollments").json()["token"]
    assert client.post("/api/agent/enroll", headers={"X-PCMED-Gateway": other["token"]},
                       json={"token": token, "hostname": "PC", "os_version": "Win"}).status_code == 403
    assert client.post(f"/api/tenants/alpha/gateways/{relay['id']}/revoke").status_code == 200
    assert client.post("/api/agent/heartbeat", headers=via_relay, json={"agent_version": "0.1"}).status_code == 401


def test_revocation_cancels_queued_and_stops_agent(approved):
    job_id = queue(approved)
    client, _, _, device_id, headers, definition_id = approved
    assert client.post(f"/api/tenants/alpha/definitions/{definition_id}/revoke").status_code == 200
    assert client.post("/api/agent/next", headers=headers).status_code == 204
    assert client.get("/api/tenants/alpha/jobs").json()[0]["state"] == "cancelled"
    assert client.post(f"/api/tenants/alpha/devices/{device_id}/revoke").status_code == 200
    assert client.post("/api/agent/heartbeat", headers=headers, json={"agent_version": "0.1"}).status_code == 401


def test_cross_client_batch_atomic(approved):
    client, user, factory, device_id, headers, definition_id = approved
    user.roles = {"platform_admin"}
    token = client.post("/api/tenants/beta/enrollments").json()["token"]
    other = client.post("/api/agent/enroll", json={"token": token, "hostname": "B", "os_version": "Win"}).json()
    assert client.post("/api/tenants/alpha/jobs", json={"device_ids": [device_id, other["device_id"]], "definition_id": definition_id}).status_code == 404
    assert client.get("/api/tenants/alpha/jobs").json() == []


def test_result_claim_bound_to_device(approved):
    job_id = queue(approved)
    client, _, _, _, headers, _ = approved
    claim = client.post("/api/agent/next", headers=headers).json()
    token = client.post("/api/tenants/alpha/enrollments").json()["token"]
    other = client.post("/api/agent/enroll", json={"token": token, "hostname": "B", "os_version": "Win"}).json()
    response = client.post(f"/api/agent/results/{job_id}", headers={"Authorization": "Bearer " + other["token"]},
                           json={"claim": claim["claim"], "state": "succeeded"})
    assert response.status_code == 403


def test_message_is_plain_text_job(enrolled):
    client, _, _, device_id, headers = enrolled
    response = client.post("/api/tenants/alpha/messages", json={"device_ids": [device_id], "title": "Service", "body": "<script>test</script>"})
    assert response.status_code == 201
    job = client.post("/api/agent/next", headers=headers).json()
    assert job["kind"] == "message"
    assert job["spec"]["body"] == "<script>test</script>"


def test_artifact_ticket_requires_active_installer_claim(enrolled):
    client, user, _, device_id, headers = enrolled
    definition = client.post("/api/tenants/alpha/definitions", json={"name": "MSI", "kind": "msi", "url": "https://packages.example.test/a.msi", "sha256": "f" * 64}).json()
    user.subject = "approver-b"
    client.post(f"/api/tenants/alpha/definitions/{definition['id']}/approve")
    job_id = client.post("/api/tenants/alpha/jobs", json={"device_ids": [device_id], "definition_id": definition["id"]}).json()[0]["id"]
    claim = client.post("/api/agent/next", headers=headers).json()["claim"]
    path = f"/api/agent/artifact-ticket/{job_id}/{claim}"
    assert client.get(path, headers=headers).json()["sha256"] == "f" * 64
    client.post(f"/api/tenants/alpha/definitions/{definition['id']}/revoke")
    assert client.get(path, headers=headers).status_code == 403


def test_postgres_concurrent_claims(approved):
    client, _, factory, _, headers, _ = approved
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL; exercised by CI")
    queue(approved)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post("/api/agent/next", headers=headers).status_code, range(2)))
    assert sorted(statuses) == [200, 204]


def test_powershell_hash_includes_utf8_bom(system):
    client, *_ = system
    script = "Write-Output 'Zażółć gęślą jaźń'"
    response = client.post("/api/tenants/alpha/definitions", json={"name": "Unicode", "kind": "powershell", "script": script})
    assert response.status_code == 201
    assert response.json()["spec"]["sha256"] == hashlib.sha256(script.encode("utf-8-sig")).hexdigest()


def test_postgres_concurrent_enrollment(system):
    client, _, factory = system
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Enrollment row locks require PostgreSQL")
    token = client.post("/api/tenants/alpha/enrollments").json()["token"]
    payload = {"token": token, "hostname": "PC", "os_version": "Windows"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post("/api/agent/enroll", json=payload).status_code, range(2)))
    assert sorted(statuses) == [201, 401]


def test_postgres_enqueue_and_revocation_are_serialized(approved):
    client, _, factory, device_id, _, definition_id = approved
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Device row locks require PostgreSQL")
    with ThreadPoolExecutor(max_workers=2) as pool:
        queued = pool.submit(client.post, "/api/tenants/alpha/jobs", json={"device_ids": [device_id], "definition_id": definition_id})
        revoked = pool.submit(client.post, f"/api/tenants/alpha/devices/{device_id}/revoke")
        assert queued.result().status_code in {201, 404}
        assert revoked.result().status_code == 200
    assert all(job["state"] != "queued" for job in client.get("/api/tenants/alpha/jobs").json())
