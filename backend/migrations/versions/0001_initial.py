"""Initial MVP schema. Frozen independently of application models."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("tenants", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True))
    op.create_table("enrollments", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True),
                    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("expires_at", sa.Integer, nullable=False), sa.Column("used", sa.Boolean, nullable=False))
    op.create_table("gateways", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True),
                    sa.Column("name", sa.String(120), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("revoked", sa.Boolean, nullable=False))
    op.create_table("devices", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True),
                    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("hostname", sa.String(120), nullable=False), sa.Column("os_version", sa.String(200), nullable=False),
                    sa.Column("agent_version", sa.String(50), nullable=False), sa.Column("last_seen", sa.Integer, nullable=False),
                    sa.Column("gateway_id", sa.String(36), sa.ForeignKey("gateways.id")), sa.Column("revoked", sa.Boolean, nullable=False),
                    sa.UniqueConstraint("id", "tenant_id"))
    op.create_table("definitions", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True),
                    sa.Column("name", sa.String(120), nullable=False), sa.Column("kind", sa.String(20), nullable=False),
                    sa.Column("spec", sa.JSON, nullable=False), sa.Column("timeout_seconds", sa.Integer, nullable=False),
                    sa.Column("created_by", sa.String(200), nullable=False), sa.Column("approved_by", sa.String(200)),
                    sa.Column("status", sa.String(20), nullable=False), sa.UniqueConstraint("id", "tenant_id"))
    op.create_table("jobs", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True),
                    sa.Column("device_id", sa.String(36), nullable=False), sa.Column("definition_id", sa.String(36)),
                    sa.Column("kind", sa.String(20), nullable=False), sa.Column("spec", sa.JSON, nullable=False),
                    sa.Column("timeout_seconds", sa.Integer, nullable=False), sa.Column("state", sa.String(20), nullable=False),
                    sa.Column("created_at", sa.Integer, nullable=False), sa.Column("started_at", sa.Integer),
                    sa.Column("finished_at", sa.Integer), sa.Column("claim", sa.String(36)), sa.Column("deadline", sa.Integer),
                    sa.Column("exit_code", sa.Integer), sa.Column("output", sa.Text),
                    sa.ForeignKeyConstraint(["device_id", "tenant_id"], ["devices.id", "devices.tenant_id"]),
                    sa.ForeignKeyConstraint(["definition_id", "tenant_id"], ["definitions.id", "definitions.tenant_id"]))
    op.create_index("ix_jobs_dispatch", "jobs", ["device_id", "state", "created_at"])
    op.create_table("audit", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), index=True),
                    sa.Column("created_at", sa.Integer, nullable=False, index=True),
                    sa.Column("actor", sa.String(200), nullable=False), sa.Column("action", sa.String(100), nullable=False),
                    sa.Column("target", sa.String(200), nullable=False))


def downgrade():
    for table in ("audit", "jobs", "definitions", "devices", "gateways", "enrollments", "tenants"):
        op.drop_table(table)
