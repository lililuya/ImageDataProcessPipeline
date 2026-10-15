import math

from psycopg.types.json import Jsonb

from idp.catalog.postgres import Catalog
from idp.domain.identity import canonical_bytes
from idp.execution.operators import OperatorSpec
from idp.storage.local import LocalStore

RETRYABLE = {"PROVIDER_TIMEOUT", "RATE_LIMIT", "IO_FAILURE", "WORKER_OOM", "EXECUTION_FAILURE"}
PERMANENT = {"DECODE_CORRUPT_OR_UNSUPPORTED", "PIXEL_LIMIT", "FRAME_LIMIT",
             "SCHEMA_INVALID", "ADAPTER_UNSUPPORTED", "INPUT_CHECKSUM_MISMATCH"}


class Queue:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    @staticmethod
    def _event(conn, key, token, event, actor, reason=None):
        conn.execute("INSERT INTO job_events(task_key,token,event,actor,reason) VALUES(%s,%s,%s,%s,%s)",
                     (key, token, event, actor, reason))

    def enqueue(self, spec: OperatorSpec, inputs: list[str], dependencies: tuple[str, ...] = (),
                max_attempts: int = 3, retry_base: float = 1) -> str:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise ValueError("INVALID_ATTEMPT_LIMIT")
        if not math.isfinite(retry_base) or not 0 <= retry_base <= 300:
            raise ValueError("INVALID_BACKOFF")
        key = spec.task_key(inputs)
        record = {"spec": spec.model_dump(mode="json"), "inputs": inputs,
                  "dependencies": sorted(set(dependencies))}
        with self.catalog.connect() as conn:
            conn.execute("""INSERT INTO jobs(task_key,resource,record,max_attempts,retry_base)
              VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (key, spec.resource, Jsonb(record), max_attempts, retry_base))
            old = conn.execute("SELECT record,max_attempts,retry_base FROM jobs WHERE task_key=%s", (key,)).fetchone()
            if old["record"] != record or old["max_attempts"] != max_attempts or old["retry_base"] != retry_base:
                raise ValueError("TASK_DEPENDENCY_OR_POLICY_CONFLICT")
            for dep in sorted(set(dependencies)):
                conn.execute("INSERT INTO job_dependencies VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, dep))
        return key

    def configure_pool(self, resource: str, concurrency: int, paused: bool = False) -> None:
        if resource not in {"cpu", "gpu", "api"} or type(concurrency) is not int or concurrency < 1:
            raise ValueError("INVALID_POOL")
        with self.catalog.connect() as conn:
            conn.execute("UPDATE resource_pools SET concurrency=%s,paused=%s WHERE resource=%s",
                         (concurrency, paused, resource))

    def claim(self, owner: str, resource: str, ttl: float = 60) -> dict | None:
        claimed = self.claim_batch(owner, resource, 1, ttl)
        return claimed[0] if claimed else None

    def claim_batch(self, owner: str, resource: str, limit: int, ttl: float = 60) -> list[dict]:
        if not owner.strip() or resource not in {"cpu", "gpu", "api"} or not 0 < ttl <= 86400:
            raise ValueError("INVALID_CLAIM")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("INVALID_BATCH_LIMIT")
        with self.catalog.connect() as conn:
            pool = conn.execute("SELECT * FROM resource_pools WHERE resource=%s FOR UPDATE", (resource,)).fetchone()
            if pool["paused"]:
                return []
            expired = conn.execute("""UPDATE jobs SET state='quarantined',last_error='LEASE_EXPIRED',
              owner=NULL,lease_expires_at=NULL WHERE resource=%s AND state='leased'
              AND lease_expires_at<=clock_timestamp() AND attempts>=max_attempts RETURNING task_key,attempt_token""",
                                   (resource,)).fetchall()
            for row in expired:
                self._event(conn, row["task_key"], row["attempt_token"], "quarantined", "scheduler", "LEASE_EXPIRED")
            active = conn.execute("SELECT count(*) AS n FROM jobs WHERE resource=%s AND state='leased' AND lease_expires_at>clock_timestamp()",
                                  (resource,)).fetchone()["n"]
            slots = min(limit, max(0, pool["concurrency"] - active))
            if slots == 0:
                return []
            rows = conn.execute("""
              WITH picked AS (
                SELECT j.task_key FROM jobs j WHERE j.resource=%s AND j.attempts<j.max_attempts
                AND ((j.state IN ('pending','retry_wait') AND j.available_at<=clock_timestamp())
                  OR (j.state='leased' AND j.lease_expires_at<=clock_timestamp()))
                AND NOT EXISTS (
                  SELECT 1 FROM job_dependencies d JOIN jobs p ON p.task_key=d.dependency_key
                  WHERE d.task_key=j.task_key AND p.state<>'succeeded')
                ORDER BY j.created_at,j.task_key FOR UPDATE OF j SKIP LOCKED LIMIT %s
              ) UPDATE jobs j SET state='leased',owner=%s,attempt_token=attempt_token+1,
                attempts=attempts+1,lease_expires_at=clock_timestamp()+(%s * interval '1 second')
              FROM picked p WHERE j.task_key=p.task_key RETURNING j.*
            """, (resource, slots, owner, ttl)).fetchall()
            for row in rows:
                self._event(conn, row["task_key"], row["attempt_token"], "leased", owner)
            return rows

    def heartbeat(self, task_key: str, owner: str, token: int, ttl: float = 60) -> None:
        if not 0 < ttl <= 86400:
            raise ValueError("INVALID_TTL")
        with self.catalog.connect() as conn:
            changed = conn.execute("""UPDATE jobs SET lease_expires_at=clock_timestamp()+(%s * interval '1 second')
              WHERE task_key=%s AND owner=%s AND attempt_token=%s AND state='leased'
              AND lease_expires_at>clock_timestamp() RETURNING task_key""", (ttl, task_key, owner, token)).fetchone()
            if not changed:
                raise ValueError("LEASE_LOST")

    def complete(self, task_key: str, owner: str, token: int, result: dict,
                 artifacts: tuple[str, ...] = (), store: LocalStore | None = None) -> None:
        canonical_bytes(result)
        verified = []
        for checksum in sorted(set(artifacts)):
            if store is None:
                raise ValueError("ARTIFACT_STORE_REQUIRED")
            path = store.path(checksum)
            if store.hash_file(path) != checksum:
                raise ValueError("ARTIFACT_CHECKSUM_MISMATCH")
            verified.append((checksum, str(path), path.stat().st_size))
        with self.catalog.connect() as conn:
            changed = conn.execute("""UPDATE jobs SET state='succeeded',result=%s,lease_expires_at=NULL,last_error=NULL
              WHERE task_key=%s AND owner=%s AND attempt_token=%s AND state='leased'
              AND lease_expires_at>clock_timestamp() RETURNING record""", (Jsonb(result), task_key, owner, token)).fetchone()
            if not changed:
                raise ValueError("LEASE_LOST")
            record = changed["record"]
            conn.execute("INSERT INTO observations(task_key,subject_refs,producer,payload) VALUES(%s,%s,%s,%s)",
                         (task_key, Jsonb(record["inputs"]), Jsonb(record["spec"]), Jsonb(result)))
            for checksum, uri, size in verified:
                conn.execute("INSERT INTO artifacts(checksum,uri,byte_size) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                             (checksum, uri, size))
                conn.execute("INSERT INTO job_artifacts VALUES(%s,%s)", (task_key, checksum))
            self._event(conn, task_key, token, "succeeded", owner)

    def fail(self, task_key: str, owner: str, token: int, code: str) -> str:
        if code not in RETRYABLE | PERMANENT:
            raise ValueError("UNKNOWN_ERROR_CODE")
        with self.catalog.connect() as conn:
            job = conn.execute("""SELECT * FROM jobs WHERE task_key=%s AND owner=%s AND attempt_token=%s
              AND state='leased' AND lease_expires_at>clock_timestamp() FOR UPDATE""", (task_key, owner, token)).fetchone()
            if not job:
                raise ValueError("LEASE_LOST")
            state = "retry_wait" if code in RETRYABLE and job["attempts"] < job["max_attempts"] else "quarantined"
            delay = min(300, job["retry_base"] * 2 ** min(job["attempts"] - 1, 16))
            conn.execute("""UPDATE jobs SET state=%s,last_error=%s,owner=NULL,lease_expires_at=NULL,
              available_at=clock_timestamp()+(%s * interval '1 second') WHERE task_key=%s""",
                         (state, code, delay, task_key))
            self._event(conn, task_key, token, state, owner, code)
            return state

    def replay(self, task_key: str, actor: str, reason: str) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("ACTOR_AND_REASON_REQUIRED")
        with self.catalog.connect() as conn:
            job = conn.execute("""UPDATE jobs SET state='pending',attempts=0,available_at=clock_timestamp(),
              owner=NULL,lease_expires_at=NULL WHERE task_key=%s AND state='quarantined'
              RETURNING attempt_token""", (task_key,)).fetchone()
            if not job:
                raise ValueError("JOB_NOT_QUARANTINED")
            self._event(conn, task_key, job["attempt_token"], "replayed", actor, reason)

    def inspect(self, task_key: str) -> dict:
        with self.catalog.connect() as conn:
            job = conn.execute("""SELECT task_key,state,resource,attempt_token,attempts,max_attempts,
              last_error,lease_expires_at,available_at FROM jobs WHERE task_key=%s""", (task_key,)).fetchone()
            if not job:
                raise ValueError("JOB_NOT_FOUND")
            return job

    def metrics(self) -> dict:
        with self.catalog.connect() as conn:
            rows = conn.execute("""SELECT resource,state,count(*) AS n,
              max(extract(epoch FROM clock_timestamp()-created_at)) AS oldest_created_age_seconds
              FROM jobs GROUP BY resource,state""").fetchall()
            counts = {r["resource"] + ":" + r["state"]: r["n"] for r in rows}
            observations = conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"]
            ages = {r["resource"] + ":" + r["state"]: float(r["oldest_created_age_seconds"]) for r in rows}
            events = conn.execute("SELECT event,count(*) AS n FROM job_events GROUP BY event").fetchall()
            return {"jobs": counts, "observations": observations,
                    "oldest_created_age_seconds": ages,
                    "events": {r["event"]: r["n"] for r in events}}
