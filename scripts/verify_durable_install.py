"""Exercise installed checkpoint v2; invoke with Python -I to exclude checkout."""

from pathlib import Path
from tempfile import TemporaryDirectory

from axiom.durable import Durable, ExpiredError, Outcome, Request


def verify() -> None:
    """Compact past history capacity, reopen exact state, retry and reject expiry."""
    with TemporaryDirectory() as directory:
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


if __name__ == "__main__":
    verify()
