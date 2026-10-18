"""字节重复只有一个资产；快照保留其独立来源成员，不作语义去重。"""

from psycopg.types.json import Jsonb

from idp.catalog.postgres import Catalog
from idp.domain.identity import digest


def snapshot_exact(catalog: Catalog, batch_id: str | None = None) -> dict:
    with catalog.connect() as conn:
        rows = conn.execute("""SELECT asset_id,source_id FROM source_records
            WHERE (%s::text IS NULL OR batch_id=%s) ORDER BY asset_id,source_id""",
                            (batch_id, batch_id)).fetchall()
        groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(row["asset_id"], []).append(row["source_id"])
        payload = {"algorithm": "sha256-bytes-v1", "batch_id": batch_id,
                   "groups": [{"asset_id": key, "source_ids": members}
                              for key, members in groups.items()]}
        snapshot_id = digest(payload)
        conn.execute("INSERT INTO exact_duplicate_snapshots(snapshot_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                     (snapshot_id, Jsonb(payload)))
    return {"snapshot_id": snapshot_id, "unique_assets": len(groups), "source_records": len(rows),
            "duplicate_groups": sum(len(items) > 1 for items in groups.values()),
            "duplicate_sources": len(rows) - len(groups)}
