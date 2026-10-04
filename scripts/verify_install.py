"""Verify installed Basic/Multilevel matching, Packed storage and durability."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from axiom import Matcher, Packed
from axiom.durable import Durable, Outcome, Request
from axiom.service import Service
from axiom.witness import Witness


def verify() -> None:
    """Exercise both matching modes and their installed durable path."""
    witness = Witness()
    for mode in ("basic", "multilevel"):
        graph, replay = Packed(16), Packed(16)
        graph.ring()
        replay.ring()
        matcher = Matcher(16, graph=graph, mode=mode)
        recovered = Matcher(16, graph=replay, mode=mode)
        for target in (matcher, recovered):
            target.insert(0, 4)
            with target.batch():
                target.delete(0, 1)
                target.insert(0, 1)
        if (
            not matcher.maximal()
            or not graph.check()
            or witness.capture(matcher) != witness.capture(recovered)
        ):
            raise RuntimeError(f"installed {mode} matching/storage replay failed")

    if os.name != "posix":
        print("Windows wheel verified: paper modes and Packed storage only")
        return

    with TemporaryDirectory() as directory:
        for mode in ("basic", "multilevel"):
            path = Path(directory) / f"{mode}.db"
            with Durable(path, n=16, mode=mode, width=0, max_batch=4) as store:
                outcomes = store.apply(
                    [Request(1, "insert", 0, 1), Request(2, "delete", 0, 1)]
                )
                if outcomes != (Outcome(1, True, 1), Outcome(2, True, 2)):
                    raise RuntimeError(f"installed durable {mode} outcomes differ")
                if not store.check() or store.status().get("mode") != mode:
                    raise RuntimeError(f"installed durable {mode} audit failed")
            with Durable(path, mode=mode) as recovered:
                if (
                    recovered.status().get("sequence") != 2
                    or recovered.has_edge(0, 1) != (2, False)
                    or not recovered.check()
                ):
                    raise RuntimeError(f"installed durable {mode} recovery failed")

        path = Path(directory) / "service.db"
        with Service(path, n=16, width=0, mode="basic", queue_capacity=4) as service:
            outcome = service.submit(Request(1, "insert", 0, 1)).result(10)
            if outcome != Outcome(1, True, 1):
                raise RuntimeError("installed Service acknowledgment differs")
            if service.partner(0).result(10) != (1, 1):
                raise RuntimeError("installed Service query differs")
            if not service.check().result(10):
                raise RuntimeError("installed Service invariant audit failed")


if __name__ == "__main__":
    verify()
