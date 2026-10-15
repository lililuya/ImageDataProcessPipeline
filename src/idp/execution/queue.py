from psycopg.types.json import Jsonb

from idp.catalog.postgres import Catalog
from idp.domain.identity import canonical_bytes
from idp.execution.operators import OperatorSpec


class Queue:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def enqueue(self, spec: OperatorSpec, inputs: list[str], dependencies: tuple[str, ...] = ()) -> str:
        key = spec.task_key(inputs)
        record = {"spec": spec.model_dump(mode="json"), "inputs": inputs,
                  "dependencies": sorted(set(dependencies))}
        with self.catalog.connect() as conn:
            conn.execute("INSERT INTO jobs(task_key,resource,record) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                         (key, spec.resource, Jsonb(record)))
            old = conn.execute("SELECT record FROM jobs WHERE task_key=%s", (key,)).fetchone()
            if old["record"] != record:
                raise ValueError("TASK_DEPENDENCY_CONFLICT")
            for dep in sorted(set(dependencies)):
                conn.execute("INSERT INTO job_dependencies VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, dep))
        return key

    def claim(self, owner: str, resource: str, ttl: float = 60) -> dict | None:
        if not owner.strip() or resource not in {"cpu", "gpu", "api"} or not 0 < ttl <= 86400:
            raise ValueError("INVALID_CLAIM")
        with self.catalog.connect() as conn:
            return conn.execute("""
              WITH picked AS (
                SELECT j.task_key FROM jobs j
                WHERE j.resource=%s AND (j.state='pending' OR
                  (j.state='leased' AND j.lease_expires_at <= clock_timestamp()))
                AND NOT EXISTS (
                  SELECT 1 FROM job_dependencies d JOIN jobs p ON p.task_key=d.dependency_key
                  WHERE d.task_key=j.task_key AND p.state<>'succeeded')
                ORDER BY j.created_at,j.task_key FOR UPDATE OF j SKIP LOCKED LIMIT 1
              )
              UPDATE jobs j SET state='leased',owner=%s,attempt_token=attempt_token+1,
                lease_expires_at=clock_timestamp()+(%s * interval '1 second')
              FROM picked p WHERE j.task_key=p.task_key RETURNING j.*
            """, (resource, owner, ttl)).fetchone()

    def heartbeat(self, task_key: str, owner: str, token: int, ttl: float = 60) -> None:
        if not 0 < ttl <= 86400:
            raise ValueError("INVALID_TTL")
        with self.catalog.connect() as conn:
            changed = conn.execute("""UPDATE jobs SET lease_expires_at=clock_timestamp()+(%s * interval '1 second')
              WHERE task_key=%s AND owner=%s AND attempt_token=%s AND state='leased'
              AND lease_expires_at>clock_timestamp() RETURNING task_key""", (ttl, task_key, owner, token)).fetchone()
            if not changed:
                raise ValueError("LEASE_LOST")

    def complete(self, task_key: str, owner: str, token: int, result: dict) -> None:
        canonical_bytes(result)
        with self.catalog.connect() as conn:
            changed = conn.execute("""UPDATE jobs SET state='succeeded',result=%s,lease_expires_at=NULL
              WHERE task_key=%s AND owner=%s AND attempt_token=%s AND state='leased'
              AND lease_expires_at>clock_timestamp() RETURNING task_key""", (Jsonb(result), task_key, owner, token)).fetchone()
            if not changed:
                raise ValueError("LEASE_LOST")
