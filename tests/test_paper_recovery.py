"""Public-API recovery equivalence for durable paper matcher modes."""

from pathlib import Path

import pytest

from axiom.durable import Durable, Outcome, Request

MODES = ("basic", "multilevel")
PARTITIONS = (1, 2, 4, 12)
VERTICES = 12


def stream() -> tuple[Request, ...]:
    """A deterministic trace with collisions, removals, and idempotent updates."""
    edges = (
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),
        (8, 9),
        (10, 11),
        (0, 2),
        (1, 3),
        (2, 4),
        (3, 5),
        (4, 6),
        (5, 7),
    )
    requests = [
        Request(index, "insert", left, right)
        for index, (left, right) in enumerate(edges, 1)
    ]
    requests.extend(
        (
            Request(13, "delete", 0, 1),
            Request(14, "insert", 8, 10),
            Request(15, "delete", 3, 5),
            Request(16, "insert", 0, 1),
            Request(17, "insert", 0, 1),
            Request(18, "delete", 9, 11),
            Request(19, "insert", 2, 6),
            Request(20, "delete", 2, 6),
        )
    )
    return tuple(requests)


def observe(store: Durable) -> tuple:
    """Capture topology, matching partners, version, and a successful audit."""
    status = store.status()
    vertices = tuple(range(status["vertices"]))
    edges = tuple(
        (left, right)
        for left in vertices
        for right in range(left + 1, status["vertices"])
    )
    snapshot = store.read_snapshot(vertices, edges)
    topology = tuple(
        edge for edge, present in zip(edges, snapshot.has_edges, strict=True) if present
    )
    matching = tuple(
        (left, right)
        for left, right in enumerate(snapshot.partners)
        if right is not None and left < right
    )
    assert snapshot.version == status["version"]
    assert len(matching) == status["matching"]
    assert store.check()
    return (
        status["sequence"],
        status["version"],
        status["edges"],
        topology,
        snapshot.partners,
        matching,
    )


def history(store: Durable) -> tuple:
    """Read and validate the complete persisted sequence using public history."""
    page = store.history(start=1, limit=128)
    assert not page.has_more
    assert len(page.records) == page.latest_sequence
    assert tuple(record.sequence for record in page.records) == tuple(
        range(1, page.latest_sequence + 1)
    )
    return tuple(
        (
            record.sequence,
            record.operation,
            record.u,
            record.v,
            record.changed,
            record.version,
        )
        for record in page.records
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("partition", PARTITIONS)
def test_durable_trace_has_identical_state_and_outcomes_after_restart(
    tmp_path: Path, mode: str, partition: int
) -> None:
    path = tmp_path / f"{mode}-{partition}.sqlite"
    requests = stream()
    outcomes: list[Outcome] = []

    with Durable(
        path,
        n=VERTICES,
        width=0,
        mode=mode,
        max_batch=len(requests),
    ) as store:
        for offset in range(0, len(requests), partition):
            outcomes.extend(store.apply(requests[offset : offset + partition]))
        expected_state = observe(store)
        expected_history = history(store)

    with Durable(path, mode=mode) as recovered:
        assert observe(recovered) == expected_state
        assert history(recovered) == expected_history
        assert recovered.check()

    # The same complete input trace must have the same externally visible
    # outcomes independent of transaction partitioning.
    baseline_path = tmp_path / f"{mode}-single-operation-baseline.sqlite"
    if partition != 1:
        with Durable(
            baseline_path,
            n=VERTICES,
            width=0,
            mode=mode,
            max_batch=len(requests),
        ) as baseline:
            baseline_outcomes = tuple(
                outcome
                for request in requests
                for outcome in baseline.apply((request,))
            )
            baseline_state = observe(baseline)
            baseline_history = history(baseline)
        assert tuple(outcomes) == baseline_outcomes
        assert expected_state == baseline_state
        assert expected_history == baseline_history


@pytest.mark.parametrize("mode", MODES)
def test_mixed_durable_batch_recovers_as_one_complete_sequence(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"mixed-{mode}.sqlite"
    requests = (
        Request(1, "insert", 0, 1),
        Request(2, "insert", 2, 3),
        Request(3, "delete", 0, 1),
        Request(4, "insert", 0, 1),
        Request(5, "delete", 8, 9),  # valid no-op remains in durable history
        Request(6, "insert", 1, 2),
    )

    with Durable(path, n=VERTICES, width=0, mode=mode, max_batch=8) as store:
        expected_outcomes = store.apply(requests)
        assert tuple(outcome.sequence for outcome in expected_outcomes) == tuple(
            range(1, len(requests) + 1)
        )
        expected_state = observe(store)
        expected_history = history(store)
        assert len(expected_history) == len(requests)
        assert expected_history[4][4] is False

    with Durable(path, mode=mode) as recovered:
        assert observe(recovered) == expected_state
        assert history(recovered) == expected_history
        assert recovered.check()
