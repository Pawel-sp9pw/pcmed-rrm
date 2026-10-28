import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from . import schemas
from .auth import Principal, agent, digest, gateway, principal
from .config import settings
from .db import database, session_factory
from .models import Audit, Definition, Device, Enrollment, Gateway, Job, Tenant, identifier, now


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    session_factory().kw["bind"].dispose()


app = FastAPI(title="PC MED RMM", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


def audit(session: Session, actor: str, action: str, target: str, tenant_id: str | None = None):
    session.add(Audit(actor=actor, action=action, target=target, tenant_id=tenant_id))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if response.status_code in {401, 403}:
        with session_factory()() as session:
            audit(session, "unattributed-request", f"http.{response.status_code}", request.url.path[:200])
            session.commit()
    return response


def scoped(session: Session, model, object_id: str, tenant_id: str, lock=False):
    statement = select(model).where(model.id == object_id, model.tenant_id == tenant_id)
    if lock:
        statement = statement.with_for_update()
    found = session.scalar(statement)
    if not found:
        raise HTTPException(404, "Object not found")
    return found


def tenant_exists(session: Session, tenant_id: str):
    if not session.get(Tenant, tenant_id):
        raise HTTPException(404, "Client not found")


def expire_jobs(session: Session, tenant_id: str, device_id: str | None = None):
    statement = select(Job).where(Job.tenant_id == tenant_id, Job.state == "running", Job.deadline < now())
    if device_id:
        statement = statement.where(Job.device_id == device_id)
    for job in session.scalars(statement.with_for_update()):
        job.state = "unknown"
        audit(session, "system", "job.expired", job.id, tenant_id)


def job_view(job: Job):
    return {key: getattr(job, key) for key in (
        "id", "device_id", "definition_id", "kind", "state", "created_at", "started_at", "finished_at", "exit_code", "output")}


def definition_view(definition: Definition):
    return {key: getattr(definition, key) for key in (
        "id", "name", "kind", "spec", "timeout_seconds", "created_by", "approved_by", "status")}


@app.get("/healthz")
def health(session: Session = Depends(database)):
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/me")
def me(user: Principal = Depends(principal)):
    return {"subject": user.subject, "roles": sorted(user.roles), "tenant_ids": sorted(user.tenants)}


@app.get("/api/tenants")
def tenants(user: Principal = Depends(principal), session: Session = Depends(database)):
    statement = select(Tenant).order_by(Tenant.name)
    if "platform_admin" not in user.roles:
        statement = statement.where(Tenant.id.in_(user.tenants))
    return [{"id": tenant.id, "name": tenant.name} for tenant in session.scalars(statement)]


@app.post("/api/tenants", status_code=201)
def create_tenant(body: schemas.Name, user: Principal = Depends(principal), session: Session = Depends(database)):
    if "platform_admin" not in user.roles:
        raise HTTPException(403, "Platform administrator required")
    if session.scalar(select(Tenant).where(Tenant.name == body.name)):
        raise HTTPException(409, "Client name already exists")
    tenant = Tenant(name=body.name)
    session.add(tenant)
    session.flush()
    audit(session, user.subject, "tenant.created", tenant.id, tenant.id)
    session.commit()
    return {"id": tenant.id, "name": tenant.name}


@app.post("/api/tenants/{tenant_id}/enrollments", status_code=201)
def create_enrollment(tenant_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    tenant_exists(session, tenant_id)
    token = secrets.token_urlsafe(32)
    enrollment = Enrollment(tenant_id=tenant_id, token_hash=digest(token), expires_at=now() + 900)
    session.add(enrollment)
    session.flush()
    audit(session, user.subject, "enrollment.created", enrollment.id, tenant_id)
    session.commit()
    return {"token": token, "expires_at": enrollment.expires_at}


@app.get("/api/tenants/{tenant_id}/gateways")
def gateways(tenant_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id)
    return [{"id": relay.id, "name": relay.name, "revoked": relay.revoked}
            for relay in session.scalars(select(Gateway).where(Gateway.tenant_id == tenant_id))]


@app.post("/api/tenants/{tenant_id}/gateways", status_code=201)
def create_gateway(tenant_id: str, body: schemas.Name, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    tenant_exists(session, tenant_id)
    token = secrets.token_urlsafe(32)
    relay = Gateway(tenant_id=tenant_id, name=body.name, token_hash=digest(token))
    session.add(relay)
    session.flush()
    audit(session, user.subject, "gateway.created", relay.id, tenant_id)
    session.commit()
    return {"id": relay.id, "token": token}


@app.post("/api/tenants/{tenant_id}/gateways/{gateway_id}/revoke")
def revoke_gateway(tenant_id: str, gateway_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    relay = scoped(session, Gateway, gateway_id, tenant_id, lock=True)
    relay.revoked = True
    audit(session, user.subject, "gateway.revoked", gateway_id, tenant_id)
    session.commit()
    return {"status": "revoked"}


@app.post("/api/agent/enroll", status_code=201)
def enroll(body: schemas.Enroll, gateway_token: str | None = Header(default=None, alias="X-PCMED-Gateway"),
           session: Session = Depends(database)):
    relay = gateway(gateway_token, session)
    record = session.scalar(select(Enrollment).where(Enrollment.token_hash == digest(body.token)).with_for_update())
    if not record or record.used or record.expires_at <= now():
        raise HTTPException(401, "Invalid or expired enrollment token")
    if relay and record.tenant_id != relay.tenant_id:
        raise HTTPException(403, "Gateway belongs to another client")
    record.used = True
    token = secrets.token_urlsafe(32)
    device = Device(tenant_id=record.tenant_id, hostname=body.hostname, os_version=body.os_version,
                    token_hash=digest(token), gateway_id=relay.id if relay else None)
    session.add(device)
    session.flush()
    audit(session, f"agent:{device.id}", "agent.enrolled", device.id, device.tenant_id)
    session.commit()
    return {"device_id": device.id, "token": token}


@app.get("/api/tenants/{tenant_id}/devices")
def devices(tenant_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200),
            user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id)
    rows = session.scalars(select(Device).where(Device.tenant_id == tenant_id).order_by(Device.hostname, Device.id).offset(offset).limit(limit))
    return [{"id": device.id, "hostname": device.hostname, "os_version": device.os_version,
             "agent_version": device.agent_version, "last_seen": device.last_seen, "gateway_id": device.gateway_id,
             "revoked": device.revoked, "online": not device.revoked and device.last_seen >= now() - settings().online_seconds}
            for device in rows]


@app.post("/api/tenants/{tenant_id}/devices/{device_id}/revoke")
def revoke_device(tenant_id: str, device_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    device = scoped(session, Device, device_id, tenant_id, lock=True)
    device.revoked = True
    session.execute(update(Job).where(Job.device_id == device.id, Job.state == "queued").values(state="cancelled", finished_at=now()))
    audit(session, user.subject, "agent.revoked", device.id, tenant_id)
    session.commit()
    return {"status": "revoked"}


@app.post("/api/agent/heartbeat")
def heartbeat(body: schemas.Heartbeat, device: Device = Depends(agent), session: Session = Depends(database)):
    device.last_seen = now()
    device.agent_version = body.agent_version
    session.commit()
    return {"status": "ok"}


@app.get("/api/tenants/{tenant_id}/definitions")
def definitions(tenant_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id)
    return [definition_view(definition) for definition in session.scalars(select(Definition).where(Definition.tenant_id == tenant_id).order_by(Definition.id))]


@app.post("/api/tenants/{tenant_id}/definitions", status_code=201)
def create_definition(tenant_id: str, body: schemas.DefinitionInput, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    tenant_exists(session, tenant_id)
    definition = Definition(tenant_id=tenant_id, name=body.name, kind=body.kind,
                            spec=body.model_dump(include={"url", "sha256", "script", "arguments"}),
                            timeout_seconds=body.timeout_seconds, created_by=user.subject)
    session.add(definition)
    session.flush()
    audit(session, user.subject, "definition.created", definition.id, tenant_id)
    session.commit()
    return definition_view(definition)


@app.post("/api/tenants/{tenant_id}/definitions/{definition_id}/approve")
def approve(tenant_id: str, definition_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, approval=True)
    definition = scoped(session, Definition, definition_id, tenant_id, lock=True)
    if definition.created_by == user.subject:
        raise HTTPException(403, "Another person must approve this executable content")
    if definition.status != "draft":
        raise HTTPException(409, "Definition is not a draft")
    definition.status = "approved"
    definition.approved_by = user.subject
    audit(session, user.subject, "definition.approved", definition.id, tenant_id)
    session.commit()
    return definition_view(definition)


@app.post("/api/tenants/{tenant_id}/definitions/{definition_id}/revoke")
def revoke_definition(tenant_id: str, definition_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, approval=True)
    definition = scoped(session, Definition, definition_id, tenant_id, lock=True)
    definition.status = "revoked"
    session.execute(update(Job).where(Job.definition_id == definition.id, Job.state == "queued").values(state="cancelled", finished_at=now()))
    audit(session, user.subject, "definition.revoked", definition.id, tenant_id)
    session.commit()
    return definition_view(definition)


def validated_targets(session: Session, tenant_id: str, device_ids: list[str]):
    unique_ids = set(device_ids)
    found = list(session.scalars(select(Device).where(Device.tenant_id == tenant_id, Device.id.in_(unique_ids), Device.revoked.is_(False))
                                 .order_by(Device.id).with_for_update()))
    if len(found) != len(unique_ids):
        raise HTTPException(404, "One or more devices are unavailable")
    return found


@app.post("/api/tenants/{tenant_id}/jobs", status_code=201)
def dispatch(tenant_id: str, body: schemas.Dispatch, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    targets = validated_targets(session, tenant_id, body.device_ids)
    definition = scoped(session, Definition, body.definition_id, tenant_id, lock=True)
    if definition.status != "approved":
        raise HTTPException(409, "Only approved definitions can run")
    jobs = []
    for device in targets:
        job = Job(tenant_id=tenant_id, device_id=device.id, definition_id=definition.id, kind=definition.kind,
                  spec=definition.spec, timeout_seconds=definition.timeout_seconds)
        session.add(job)
        session.flush()
        audit(session, user.subject, "job.queued", job.id, tenant_id)
        jobs.append(job)
    session.commit()
    return [job_view(job) for job in jobs]


@app.post("/api/tenants/{tenant_id}/messages", status_code=201)
def message(tenant_id: str, body: schemas.Message, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    jobs = []
    for device in validated_targets(session, tenant_id, body.device_ids):
        job = Job(tenant_id=tenant_id, device_id=device.id, kind="message", spec={"title": body.title, "body": body.body}, timeout_seconds=120)
        session.add(job)
        session.flush()
        audit(session, user.subject, "message.queued", job.id, tenant_id)
        jobs.append(job)
    session.commit()
    return [job_view(job) for job in jobs]


@app.get("/api/tenants/{tenant_id}/jobs")
def jobs(tenant_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200),
         user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id)
    expire_jobs(session, tenant_id)
    session.commit()
    return [job_view(job) for job in session.scalars(select(Job).where(Job.tenant_id == tenant_id).order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit))]


@app.post("/api/tenants/{tenant_id}/jobs/{job_id}/cancel")
def cancel(tenant_id: str, job_id: str, user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id, write=True)
    job = scoped(session, Job, job_id, tenant_id, lock=True)
    if job.state != "queued":
        raise HTTPException(409, "Only queued jobs can be cancelled")
    job.state = "cancelled"
    job.finished_at = now()
    audit(session, user.subject, "job.cancelled", job.id, tenant_id)
    session.commit()
    return job_view(job)


@app.post("/api/agent/next")
def next_job(device: Device = Depends(agent), session: Session = Depends(database)):
    device = session.scalar(select(Device).where(Device.id == device.id).with_for_update().execution_options(populate_existing=True))
    if device.revoked:
        raise HTTPException(401, "Agent revoked")
    expire_jobs(session, device.tenant_id, device.id)
    if session.scalar(select(Job.id).where(Job.device_id == device.id, Job.state == "running")):
        session.commit()
        return Response(status_code=204)
    job = session.scalar(select(Job).where(Job.device_id == device.id, Job.state == "queued")
                         .order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
    if not job:
        session.commit()
        return Response(status_code=204)
    if job.definition_id:
        definition = scoped(session, Definition, job.definition_id, device.tenant_id)
        if definition.status != "approved":
            job.state = "cancelled"
            job.finished_at = now()
            audit(session, "system", "job.cancelled", job.id, job.tenant_id)
            session.commit()
            return Response(status_code=204)
    job.state = "running"
    job.claim = identifier()
    job.started_at = now()
    job.deadline = now() + job.timeout_seconds + 120
    audit(session, f"agent:{device.id}", "job.claimed", job.id, device.tenant_id)
    session.commit()
    return {"id": job.id, "claim": job.claim, "kind": job.kind, "spec": job.spec, "timeout_seconds": job.timeout_seconds}


@app.post("/api/agent/results/{job_id}")
def result(job_id: str, body: schemas.Result, device: Device = Depends(agent), session: Session = Depends(database)):
    job = scoped(session, Job, job_id, device.tenant_id, lock=True)
    if job.device_id != device.id or job.claim != body.claim:
        raise HTTPException(403, "Claim does not belong to this device")
    if job.finished_at is not None:
        if job.state == body.state and job.exit_code == body.exit_code and job.output == body.output:
            return {"status": "recorded"}
        raise HTTPException(409, "Result already recorded")
    if job.state not in {"running", "unknown"}:
        raise HTTPException(409, "Job is not running")
    job.state, job.exit_code, job.output, job.finished_at = body.state, body.exit_code, body.output, now()
    audit(session, f"agent:{device.id}", "job." + body.state, job.id, device.tenant_id)
    session.commit()
    return {"status": "recorded"}


@app.get("/api/agent/artifact-ticket/{job_id}/{claim}")
def artifact_ticket(job_id: str, claim: str, device: Device = Depends(agent), session: Session = Depends(database)):
    job = scoped(session, Job, job_id, device.tenant_id)
    if job.device_id != device.id or job.claim != claim or job.state != "running" or job.kind not in {"msi", "exe"}:
        raise HTTPException(403, "No installer access for this claim")
    definition = scoped(session, Definition, job.definition_id, device.tenant_id)
    if definition.status != "approved":
        raise HTTPException(403, "Definition revoked")
    return {"url": job.spec["url"], "sha256": job.spec["sha256"]}


@app.get("/api/tenants/{tenant_id}/audit")
def events(tenant_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200),
           user: Principal = Depends(principal), session: Session = Depends(database)):
    user.allow(tenant_id)
    return [{key: getattr(event, key) for key in ("id", "actor", "action", "target", "created_at")}
            for event in session.scalars(select(Audit).where(Audit.tenant_id == tenant_id).order_by(Audit.created_at.desc(), Audit.id).offset(offset).limit(limit))]
