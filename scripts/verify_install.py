"""Verify installed paper/native/storage/durability paths without checkout imports."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from axiom import Matcher, Packed
from axiom.durable import Durable, ExpiredError, Outcome, Request
from axiom.engine import Engine
from axiom.service import Service
from axiom.witness import Witness


def verify() -> None:
    """Compact past history capacity, reopen exact state, retry and reject expiry."""
    witness = Witness()
    for mode in ("basic", "multilevel"):
        graph, replay = Packed(16), Packed(16)
        graph.ring()
        replay.ring()
        matcher = Matcher(16, graph=graph, mode=mode)
        recovered = Matcher(16, graph=replay, mode=mode)
        matcher.insert(0, 4)
        recovered.insert(0, 4)
        if not matcher.maximal() or not graph.check():
            raise RuntimeError("installed native paper graph/repair failed")
        if witness.capture(matcher) != witness.capture(recovered):
            raise RuntimeError("installed paper full-state replay differs")
        before = witness.capture(matcher)
        counter = matcher.accountant
        journal = counter.begin()
        counter.record_deletion()
        counter.record_phase_rebuild(7)
        counter.rollback(journal)
        if matcher.accountant is not counter or witness.capture(matcher) != before:
            raise RuntimeError("installed paper scalar undo changed exact state")
        held = matcher.matched_edges, matcher.matched_vertices, matcher.partner_map
        colors = matcher.matchings, matcher.seed_matching, tuple(matcher.matchings)
        matcher.delete(0, 1)
        matcher.insert(0, 1)
        if (
            not all(
                current is original
                for current, original in zip(
                    (
                        matcher.matched_edges,
                        matcher.matched_vertices,
                        matcher.partner_map,
                    ),
                    held,
                    strict=True,
                )
            )
            or matcher.views is not None
            or matcher.classes is not None
            or matcher.matchings is not colors[0]
            or matcher.seed_matching is not colors[1]
            or any(
                current is not original
                for current, original in zip(matcher.matchings, colors[2], strict=True)
            )
            or not matcher.maximal()
        ):
            raise RuntimeError("installed local matching edits replaced their views")
    engine = Engine(16)
    token = engine.begin()
    engine.insert(0, 1)
    with ThreadPoolExecutor(max_workers=1) as reader:
        if reader.submit(engine.committed_partner, 0).result(5) != (0, None):
            raise RuntimeError("installed native query exposed private state")
    engine.commit(token)
    if engine.committed_partner(0) != (1, 1) or not engine.check():
        raise RuntimeError("installed native coupled publication failed")
    image = engine.snapshot()
    token = engine.begin()
    engine.delete(0, 1)
    engine.rollback(token)
    if engine.snapshot() != image or not engine.check():
        raise RuntimeError("installed native rollback changed committed image")
    restored = Engine.restore(image)
    if restored.snapshot() != image or not restored.check():
        raise RuntimeError("installed exact native image roundtrip failed")
    with TemporaryDirectory() as directory:
        legacy = Path(directory) / "legacy.db"
        with Durable(legacy, n=16) as store:
            result = store.apply([Request(1, "delete", 0, 1)])
        with Durable(legacy) as store:
            if store.apply([Request(1, "delete", 0, 1)]) != result or not store.check():
                raise RuntimeError("installed legacy durability/retry failed")
        path = Path(directory) / "graph.db"
        with Durable(
            path,
            n=16,
            width=0,
            max_batch=4,
            max_operations=24,
            checkpoint_interval=8,
            retain_operations=4,
        ) as store:
            for first in range(1, 41, 4):
                result = store.apply(
                    [
                        Request(seq, "insert" if seq % 2 else "delete", 0, 1)
                        for seq in range(first, first + 4)
                    ]
                )
                if result != tuple(
                    Outcome(seq, True, seq) for seq in range(first, first + 4)
                ):
                    raise RuntimeError("installed durable outcomes differ")
            state = store.status()
            partners = tuple(store.partner(u) for u in range(16))
            if state["checkpoint_generation"] != 4 or not store.check():
                raise RuntimeError("installed checkpoint/audit failed")
        with Durable(path) as recovered:
            if (
                recovered.status()["sequence"] != 40
                or tuple(recovered.partner(u) for u in range(16)) != partners
                or recovered.apply([Request(40, "delete", 0, 1)]) != (result[-1],)
                or not recovered.check()
            ):
                raise RuntimeError("installed exact recovery/retry failed")
            try:
                recovered.apply([Request(1, "insert", 0, 1)])
            except ExpiredError:
                pass
            else:
                raise RuntimeError("installed expired retry was admitted")
        with Service(
            path, queue_capacity=4, query_reserve=0, batch_wait_ms=100
        ) as service:
            receipts = [
                service.submit(Request(seq, "insert" if seq % 2 else "delete", 0, 1))
                for seq in range(41, 45)
            ]
            if [receipt.result(5) for receipt in receipts] != [
                Outcome(seq, True, seq) for seq in range(41, 45)
            ]:
                raise RuntimeError("installed service aggregation failed")
            if service.partner(0).result(5) != (44, None):
                raise RuntimeError("installed service coherent query failed")
        with Durable(path) as recovered:
            if recovered.status()["sequence"] != 44 or not recovered.check():
                raise RuntimeError("installed service drain/recovery failed")
            manifest = recovered.backup(Path(directory) / "backup.db")
            if manifest["sequence"] != 44:
                raise RuntimeError("installed backup sequence differs")
        with Durable(Path(directory) / "backup.db") as restored:
            if restored.partner(0) != (44, None) or not restored.check():
                raise RuntimeError("installed backup restore failed")


if __name__ == "__main__":
    verify()
