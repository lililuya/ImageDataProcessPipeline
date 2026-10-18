"""M1本地T2I发布：冻结输入，校验实际sidecar，再提交ready。

文件写入不覆盖现有内容；失败重放复用已校验文件。完整分片/关联图/训练器适配后续实现。
"""

import hashlib
import os
import tempfile
from pathlib import Path

from PIL import Image
import psycopg
from psycopg.types.json import Jsonb

from idp.catalog.postgres import Catalog
from idp.domain.identity import canonical_bytes, digest
from idp.domain.models import SourceRecord, View
from idp.releases.models import ReleasePlan
from idp.storage.local import LocalStore


def _checksum(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _manifest_bytes(rows: list[dict]) -> bytes:
    return b"".join(canonical_bytes(row) + b"\n" for row in rows)


class Releases:
    def __init__(self, catalog: Catalog, store: LocalStore, root: Path):
        self.catalog, self.store, self.root = catalog, store, root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, release_id: str) -> Path:
        # 沿用存储层摘要和路径验证，不允许样本ID进入文件路径。
        self.store.path(release_id)
        path = self.root / release_id.removeprefix("sha256:")
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("RELEASE_PATH_ESCAPE")
        return path

    def _sources(self, conn, release_id: str, lock: bool = False):
        rows = conn.execute("""SELECT s.source_id,s.license_status,s.record
            FROM source_records s JOIN release_sources r USING(source_id)
            WHERE r.release_id=%s ORDER BY s.source_id""" + (" FOR SHARE OF s" if lock else ""),
                            (release_id,)).fetchall()
        if not rows or any(r["license_status"] != "approved" for r in rows):
            raise ValueError("SOURCE_NOT_APPROVED")
        for row in rows:
            source = SourceRecord.model_validate(row["record"])
            if source.license_status != "approved" or not source.evidence_ref:
                raise ValueError("SOURCE_EVIDENCE_REQUIRED")

    def freeze(self, plan: ReleasePlan) -> dict:
        frozen = plan.frozen_payload()
        plan = ReleasePlan.model_validate(frozen)
        recipe_digest = digest(plan.selection.model_dump(mode="json"))
        rows = []
        with self.catalog.connect() as conn:
            for member in plan.members:
                sample, caption = member.sample, member.caption
                image = sample.images[0]
                registered = conn.execute("""SELECT v.record,v.asset_id,v.output_checksum,
                    a.record AS asset,j.state FROM views v JOIN assets a USING(asset_id)
                    JOIN jobs j USING(task_key) WHERE v.view_id=%s""", (image.view_id,)).fetchone()
                if not registered or registered["state"] != "succeeded":
                    raise ValueError("COMMITTED_VIEW_REQUIRED")
                view = View.model_validate(registered["record"])
                if (view.asset_id != image.asset_id or view.output_checksum != image.checksum
                        or registered["asset"]["access_domain"] != plan.access_domain):
                    raise ValueError("VIEW_OR_ACCESS_DOMAIN_MISMATCH")
                for source_id in member.source_ids:
                    source = conn.execute("SELECT * FROM source_records WHERE source_id=%s FOR SHARE",
                                          (source_id,)).fetchone()
                    if (not source or source["asset_id"] != image.asset_id
                            or source["license_status"] != "approved"):
                        raise ValueError("SOURCE_NOT_APPROVED")
                    declaration = SourceRecord.model_validate(source["record"])
                    if declaration.license_status != "approved" or not declaration.evidence_ref:
                        raise ValueError("SOURCE_EVIDENCE_REQUIRED")
                stem = digest(sample.sample_id).removeprefix("sha256:")
                record = sample.model_dump(mode="json")
                record["images"][0]["uri"] = f"files/{stem}.png"
                record.update(caption_uri=f"files/{stem}.txt", caption_checksum=_checksum(caption.text.encode("utf-8")),
                              width=view.width, height=view.height, split=member.split,
                              recipe_digest=recipe_digest, annotation_refs=[caption.annotation_id],
                              review_refs=[digest({"annotation": caption.annotation_id, "reviewer": caption.reviewer,
                                                   "version": caption.review_version})],
                              source_refs=list(member.source_ids),
                              sampling={"weight": member.sampling_weight, "augmentation": plan.augmentation})
                rows.append(record)
            checksum = _checksum(_manifest_bytes(rows))
            release_id = digest({"plan": frozen, "manifest_checksum": checksum})
            existing = conn.execute("SELECT release_id FROM releases WHERE release_id=%s", (release_id,)).fetchone()
            if not existing:
                # 同一个发布的并发freeze串行化，避免重复事件或成员。
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                             (self.catalog.schema + ":freeze:" + release_id,))
                existing = conn.execute("SELECT release_id FROM releases WHERE release_id=%s", (release_id,)).fetchone()
            if not existing:
                for member in plan.members:
                    caption = member.caption
                    conn.execute("INSERT INTO captions VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                 (caption.annotation_id, caption.view_id, caption.checksum,
                                  Jsonb(caption.model_dump(mode="json"))))
                conn.execute("""INSERT INTO releases(release_id,plan,manifest,manifest_checksum)
                    VALUES(%s,%s,%s,%s)""", (release_id, Jsonb(frozen), Jsonb(rows), checksum))
                for member in plan.members:
                    image = member.sample.images[0]
                    conn.execute("INSERT INTO release_members VALUES(%s,%s,%s,%s,%s,%s)",
                                 (release_id, member.sample.sample_id, image.asset_id, image.view_id,
                                  member.caption.annotation_id, member.split))
                    for source_id in member.source_ids:
                        conn.execute("INSERT INTO release_sources VALUES(%s,%s) ON CONFLICT DO NOTHING",
                                     (release_id, source_id))
                conn.execute("INSERT INTO release_events(release_id,state,token,actor) VALUES(%s,'draft',0,'freeze')",
                             (release_id,))
        return {"release_id": release_id, "manifest_checksum": checksum, "members": len(rows)}

    def _record(self, release_id: str) -> dict:
        self.directory(release_id)
        with self.catalog.connect() as conn:
            row = conn.execute("SELECT * FROM releases WHERE release_id=%s", (release_id,)).fetchone()
        if not row:
            raise ValueError("RELEASE_NOT_FOUND")
        return row

    def inspect(self, release_id: str) -> dict:
        row = self._record(release_id)
        return {key: row[key] for key in ("release_id", "state", "manifest_checksum", "build_token", "last_error")} | {
            "members": len(row["manifest"])}

    def _transition(self, release_id: str, token: int, state: str, reason: str | None = None):
        with self.catalog.connect() as conn:
            # 最终状态与来源检查同事务，避免撤回在ready检查与提交之间穿过。
            if state == "ready":
                self._sources(conn, release_id, lock=True)
            changed = conn.execute("""UPDATE releases SET state=%s,last_error=%s
                WHERE release_id=%s AND build_token=%s AND state<>'withdrawn' RETURNING release_id""",
                                   (state, reason, release_id, token)).fetchone()
            if not changed:
                raise ValueError("RELEASE_BUILD_TOKEN_LOST")
            conn.execute("INSERT INTO release_events(release_id,state,token,actor,reason) VALUES(%s,%s,%s,'builder',%s)",
                         (release_id, state, token, reason))

    def _file(self, directory: Path, relative: str) -> Path:
        path = directory / relative
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError("RELEASE_PATH_ESCAPE")
        return path

    def _write(self, directory: Path, relative: str, source: Path | bytes, checksum: str):
        target = self._file(directory, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if self.store.hash_file(target) != checksum:
                raise ValueError("EXISTING_EXPORT_CHECKSUM_MISMATCH")
            return
        fd, name = tempfile.mkstemp(prefix=".release-staging-", dir=self.root)
        staged = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                if isinstance(source, bytes):
                    output.write(source)
                else:
                    with source.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if self.store.hash_file(staged) != checksum:
                raise ValueError("EXPORT_INPUT_CHECKSUM_MISMATCH")
            try:
                os.link(staged, target)
            except FileExistsError:
                if self.store.hash_file(target) != checksum:
                    raise ValueError("EXISTING_EXPORT_CHECKSUM_MISMATCH")
            if os.name == "posix":
                directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            staged.unlink(missing_ok=True)

    def build(self, release_id: str) -> dict:
        lock_key = self.catalog.schema + ":build:" + release_id
        with self.catalog.connect() as lock_conn:
            acquired = lock_conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok",
                                         (lock_key,)).fetchone()["ok"]
            lock_conn.commit()
            if not acquired:
                raise ValueError("RELEASE_BUILD_BUSY")
            try:
                row = self._record(release_id)
                if row["state"] == "withdrawn":
                    raise ValueError("RELEASE_WITHDRAWN")
                if row["state"] == "ready":
                    return self.verify(release_id)
                with self.catalog.connect() as conn:
                    token = conn.execute("""UPDATE releases SET build_token=build_token+1
                        WHERE release_id=%s RETURNING build_token""", (release_id,)).fetchone()["build_token"]
                try:
                    self._transition(release_id, token, "building")
                    with self.catalog.connect() as conn:
                        self._sources(conn, release_id)
                    directory = self.directory(release_id)
                    directory.mkdir(exist_ok=True)
                    plan = ReleasePlan.model_validate(row["plan"])
                    for member, record in zip(plan.members, row["manifest"]):
                        image = member.sample.images[0]
                        self._write(directory, record["images"][0]["uri"], self.store.path(image.checksum), image.checksum)
                        self._write(directory, record["caption_uri"], member.caption.text.encode("utf-8"), record["caption_checksum"])
                    self._write(directory, "manifest.jsonl", _manifest_bytes(row["manifest"]), row["manifest_checksum"])
                    self._transition(release_id, token, "validating")
                    result = self._verify_files(row)
                    self._transition(release_id, token, "ready")
                    return result | {"state": "ready"}
                except (ValueError, OSError, psycopg.Error):
                    self._transition(release_id, token, "failed", "BUILD_OR_VALIDATION_FAILED")
                    raise
            finally:
                lock_conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock_key,))

    def _verify_files(self, row: dict) -> dict:
        directory = self.directory(row["release_id"])
        manifest = self._file(directory, "manifest.jsonl")
        if self.store.hash_file(manifest) != row["manifest_checksum"]:
            raise ValueError("MANIFEST_CHECKSUM_MISMATCH")
        if manifest.read_bytes() != _manifest_bytes(row["manifest"]):
            raise ValueError("MANIFEST_CONTENT_MISMATCH")
        expected = {"manifest.jsonl"}
        for record in row["manifest"]:
            expected.update((record["images"][0]["uri"], record["caption_uri"]))
            # 使用同一个实际解码/sidecar读取路径；不生成预览。
            loaded = self._load_one(directory, record)
            loaded["image"].close()
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if not p.is_dir()}
        if actual != expected or any(p.is_symlink() for p in directory.rglob("*")):
            raise ValueError("UNEXPECTED_OR_MISSING_EXPORT_FILES")
        return {"release_id": row["release_id"], "manifest_checksum": row["manifest_checksum"],
                "loaded": len(row["manifest"]), "adapter": "t2i-sidecar-v1"}

    def _load_one(self, directory: Path, record: dict) -> dict:
        image = record["images"][0]
        path = self._file(directory, image["uri"])
        caption_path = self._file(directory, record["caption_uri"])
        if self.store.hash_file(path) != image["checksum"]:
            raise ValueError("IMAGE_CHECKSUM_MISMATCH")
        caption_bytes = caption_path.read_bytes()
        if _checksum(caption_bytes) != record["caption_checksum"]:
            raise ValueError("CAPTION_CHECKSUM_MISMATCH")
        caption = caption_bytes.decode("utf-8")
        if not caption.strip():
            raise ValueError("CAPTION_REQUIRED")
        with Image.open(path) as decoded:
            if (decoded.format != "PNG" or decoded.mode != image["mode"]
                    or decoded.size != (record["width"], record["height"])
                    or decoded.width * decoded.height > 100_000_000
                    or getattr(decoded, "n_frames", 1) != 1):
                raise ValueError("IMAGE_FORMAT_MODE_OR_SIZE_MISMATCH")
            decoded.load()
            pixels = decoded.copy()
        return {"sample_id": record["sample_id"], "split": record["split"], "image": pixels, "caption": caption}

    def verify(self, release_id: str) -> dict:
        row = self._record(release_id)
        if row["state"] != "ready":
            raise ValueError("RELEASE_NOT_READY")
        with self.catalog.connect() as conn:
            self._sources(conn, release_id)
        return self._verify_files(row) | {"state": "ready"}

    def iter_samples(self, release_id: str, split: str | None = None):
        if split not in {None, "train", "validation", "test"}:
            raise ValueError("INVALID_SPLIT")
        self.verify(release_id)
        row = self._record(release_id)
        for record in row["manifest"]:
            if split is None or record["split"] == split:
                yield self._load_one(self.directory(release_id), record)
