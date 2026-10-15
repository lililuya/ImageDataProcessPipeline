from concurrent.futures import ThreadPoolExecutor

import pytest

from idp.storage.local import LocalStore


def test_streaming_concurrent_put_and_corruption(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(b"large-object" * 100000)
    store = LocalStore(tmp_path / "objects")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.put(source), range(8)))
    assert len(set(results)) == 1
    checksum, destination, size = results[0]
    assert size == source.stat().st_size
    assert source.read_bytes() == destination.read_bytes()
    assert not list(store.root.glob(".staging-*"))
    destination.write_bytes(b"external corruption")
    with pytest.raises(ValueError, match="CHECKSUM_MISMATCH"):
        store.put(source)
    assert destination.read_bytes() == b"external corruption"
    with pytest.raises(ValueError, match="INVALID_CHECKSUM"):
        store.path("../../outside")
