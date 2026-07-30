from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.storage import JsonStorage


def test_delivery_claim_is_atomic(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: storage.claim_delivery("same"), range(8)))

    assert results.count("CLAIMED") == 1
    assert results.count("PROCESSING") == 7
