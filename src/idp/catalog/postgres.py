import hashlib
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from idp.domain.models import Asset, SourceRecord

MIGRATIONS = (
    """
    CREATE TABLE assets (
      asset_id text PRIMARY KEY CHECK (asset_id ~ '^sha256:[0-9a-f]{64}$'),
      record jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE source_records (
      source_id text PRIMARY KEY,
      asset_id text NOT NULL REFERENCES assets(asset_id),
      source_name text NOT NULL, batch_id text NOT NULL, original_id text NOT NULL,
      license_status text NOT NULL CHECK (license_status IN ('unknown','approved','withdrawn')),
      record jsonb NOT NULL,
      UNIQUE(source_name,batch_id,original_id,asset_id)
    );
    CREATE TABLE jobs (
      task_key text PRIMARY KEY, resource text NOT NULL CHECK(resource IN ('cpu','gpu','api')),
      record jsonb NOT NULL, state text NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending','leased','succeeded','retry_wait','quarantined','cancelled')),
      attempt_token bigint NOT NULL DEFAULT 0, owner text,
      lease_expires_at timestamptz, result jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE job_dependencies (
      task_key text REFERENCES jobs(task_key), dependency_key text REFERENCES jobs(task_key),
      PRIMARY KEY(task_key,dependency_key), CHECK(task_key<>dependency_key)
    );
    CREATE INDEX jobs_claim_idx ON jobs(resource,state,created_at);
    """,
    """
    CREATE TABLE source_events (
      event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      source_id text NOT NULL REFERENCES source_records(source_id),
      actor text NOT NULL, reason text NOT NULL, status text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX source_asset_status_idx ON source_records(asset_id,license_status);
    """,
)


class Catalog:
    def __init__(self, dsn: str, schema: str = "idp"):
        if not schema.isidentifier() or not schema.isascii():
            raise ValueError("INVALID_CATALOG_SCHEMA")
        self.dsn, self.schema = dsn, schema

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=10) as conn:
            conn.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
            yield conn

    def migrate(self, target: int = len(MIGRATIONS)) -> None:
        if not 1 <= target <= len(MIGRATIONS):
            raise ValueError("INVALID_MIGRATION_TARGET")
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("idp-migrate:" + self.schema,))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version int PRIMARY KEY, checksum text NOT NULL)")
            applied = conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
            if [r["version"] for r in applied] != list(range(1, len(applied) + 1)):
                raise ValueError("NONCONTIGUOUS_MIGRATION_HISTORY")
            if len(applied) > target:
                raise ValueError("DATABASE_NEWER_THAN_TARGET")
            for i, body in enumerate(MIGRATIONS[:target], 1):
                checksum = hashlib.sha256(body.encode()).hexdigest()
                if i <= len(applied):
                    if applied[i - 1]["checksum"] != checksum:
                        raise ValueError("MIGRATION_CHECKSUM_MISMATCH")
                    continue
                conn.execute(body)
                conn.execute("INSERT INTO schema_migrations VALUES (%s,%s)", (i, checksum))

    def register(self, asset: Asset, source: SourceRecord) -> None:
        if source.asset_id != asset.asset_id:
            raise ValueError("SOURCE_ASSET_MISMATCH")
        with self.connect() as conn:
            conn.execute("INSERT INTO assets(asset_id,record) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                         (asset.asset_id, Jsonb(asset.model_dump(mode="json"))))
            # 重放不恢复撤回状态，也不静默改变先前来源证据。
            conn.execute("INSERT INTO source_records VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (source.source_id, source.asset_id, source.source_name, source.batch_id,
                          source.original_id, source.license_status, Jsonb(source.model_dump(mode="json"))))

    def source_available(self, asset_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT EXISTS(SELECT 1 FROM source_records WHERE asset_id=%s AND license_status='approved') AS available",
                                (asset_id,)).fetchone()["available"]

    def withdraw(self, source_id: str, actor: str, reason: str) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("ACTOR_AND_REASON_REQUIRED")
        with self.connect() as conn:
            changed = conn.execute("UPDATE source_records SET license_status='withdrawn' WHERE source_id=%s RETURNING source_id",
                                   (source_id,)).fetchone()
            if not changed:
                raise ValueError("SOURCE_NOT_FOUND")
            conn.execute("INSERT INTO source_events(source_id,actor,reason,status) VALUES(%s,%s,%s,'withdrawn')",
                         (source_id, actor, reason))
