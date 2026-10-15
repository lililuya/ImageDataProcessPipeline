import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from idp.catalog.postgres import Catalog
from idp.domain.identity import digest
from idp.domain.models import Asset, Contract, SourceRecord, Text
from idp.storage.local import LocalStore


class SourceConfig(Contract):
    batch_id: Text
    source_name: Text
    access_domain: Text
    license_status: Literal["unknown", "approved"] = "unknown"
    evidence_ref: Text | None = None


def ingest(path: Path, original_id: str, config: SourceConfig,
           store: LocalStore, catalog: Catalog) -> str:
    checksum, stored, size = store.put(path)
    now = datetime.now(timezone.utc)
    common = dict(created_at=now, producer_version="ingest-v1", subject_ref=checksum,
                  config_digest=digest(config.model_dump(mode="json")))
    asset = Asset(**common, asset_id=checksum, uri=str(stored), byte_size=size,
                  mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                  access_domain=config.access_domain)
    source = SourceRecord(**common, asset_id=checksum, batch_id=config.batch_id,
                          source_name=config.source_name, original_id=original_id,
                          source_uri=str(path.resolve()), acquired_at=now,
                          license_status=config.license_status, evidence_ref=config.evidence_ref)
    catalog.register(asset, source)
    return checksum
