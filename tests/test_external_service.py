"""Service contracts for durable external identifiers."""

from pathlib import Path
from uuid import UUID

import pytest

from axiom.durable import ExternalRequest, Outcome
from axiom.service import Service


def create(path: Path, mode: str) -> Service:
    """Open a small Service with deterministic admission boundaries."""
    return Service(
        path,
        n=8,
        width=0,
        mode=mode,
        queue_capacity=16,
        query_reserve=0,
        max_batch=4,
        max_operations=32,
        batch_wait_ms=0,
    )


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_registration_receipt_and_external_insert_queries_snapshot(
    tmp_path: Path, mode: str
) -> None:
    job = UUID("00112233-4455-6677-8899-aabbccddeeff")
    with create(tmp_path / f"external-{mode}.db", mode) as service:
        worker_slot = service.register_identifier("worker-1").result(5)
        job_slot = service.register_identifier(job).result(5)
        assert (worker_slot, job_slot) == (0, 1)
        assert service.register_identifier("worker-1").result(5) == worker_slot

        inserted = service.submit_external(
            ExternalRequest(1, "insert", "worker-1", job)
        ).result(5)
        assert inserted == Outcome(1, True, 1)
        assert service.partner_external("worker-1").result(5) == (1, job)
        assert service.has_edge_external(job, "worker-1").result(5) == (1, True)

        snapshot = service.read_snapshot_external(
            ["worker-1", job],
            [("worker-1", job), (job, "worker-1")],
            expected_version=1,
        ).result(5)
        assert snapshot.version == 1
        assert snapshot.partners == (job, "worker-1")
        assert snapshot.has_edges == (True, True)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_external_batch_retry_is_deduplicated_and_versioned(
    tmp_path: Path, mode: str
) -> None:
    with create(tmp_path / f"batch-{mode}.db", mode) as service:
        for value in ("a", "b", "c", "d"):
            service.register_identifier(value).result(5)

        batch = [
            ExternalRequest(1, "insert", "a", "b"),
            ExternalRequest(2, "insert", "c", "d"),
        ]
        expected = (Outcome(1, True, 1), Outcome(2, True, 2))
        assert service.submit_external_batch(batch).result(5) == expected
        # Endpoint order is normalized before retry comparison; sequence and
        # typed identity payload still refer to the exact committed operations.
        retry = [
            ExternalRequest(1, "insert", "b", "a"),
            ExternalRequest(2, "insert", "d", "c"),
        ]
        assert service.submit_external_batch(retry).result(5) == expected
        assert service.status().result(5)["sequence"] == 2
        snapshot = service.read_snapshot_external(
            ["a", "b", "c", "d"], [("a", "b"), ("c", "d")], expected_version=2
        ).result(5)
        assert snapshot.version == 2
        assert snapshot.partners == ("b", "a", "d", "c")
        assert snapshot.has_edges == (True, True)
        assert service.check().result(5)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_unknown_external_id_failure_does_not_poison_service(
    tmp_path: Path, mode: str
) -> None:
    with create(tmp_path / f"unknown-{mode}.db", mode) as service:
        with pytest.raises(KeyError, match="not registered"):
            service.partner_external("unknown").result(5)
        with pytest.raises(KeyError, match="not registered"):
            service.submit_external(ExternalRequest(1, "insert", "known", "other"))

        # Rejected lookups and updates must not poison the owner or consume the
        # next durable mutation sequence.
        assert service.metrics()["state"] == "open"
        service.register_identifier("known").result(5)
        service.register_identifier("other").result(5)
        assert service.submit_external(
            ExternalRequest(1, "insert", "known", "other")
        ).result(5) == Outcome(1, True, 1)
        assert service.status().result(5)["sequence"] == 1
        assert service.partner_external("known").result(5) == (1, "other")
