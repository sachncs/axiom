"""Offer arrivals from a separate process through bounded local datagrams.

This isolates producer GIL scheduling, not a production network protocol.
Producer-missed, IPC-dropped, server-rejected and acknowledged counts stay distinct.
"""

from __future__ import annotations

import argparse
import errno
import json
import multiprocessing
import platform
import resource
import socket
import struct
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import BusyError, Durable, Request
from axiom.service import Service
from benchmarks.durable import certificate
from benchmarks.overload import Schedule
from benchmarks.service import Histogram, live_digest

_PACKET = struct.Struct("<BQ")


@dataclass
class Traffic(ABC):
    """Constant-space deterministic real edits and an exact query reference."""

    vertices: int

    def __post_init__(self):
        """Reject invalid universes before evaluating a trace."""
        if (
            type(self.vertices) is not int
            or not 8 <= self.vertices <= 1000000
            or self.vertices % 2
        ):
            raise ValueError("require bounded even vertices")

    @abstractmethod
    def edge(self, sequence: int) -> tuple[int, int]:
        """Choose the same existing matched edge for each delete/insert pair."""
        raise NotImplementedError

    def partner(self, version: int) -> int | None:
        """Predict vertex-zero's exact committed partner, including genesis."""
        sequence = version - 1
        if sequence % 2 and self.edge(sequence)[0] == 0:
            return None
        return 1


class Hot(Traffic):
    """Exercise one repeatedly deleted and reinserted matched edge."""

    def edge(self, sequence: int) -> tuple[int, int]:
        """Use a fixed working set, preserving the previous benchmark trace."""
        return 0, 1


class Sweep(Traffic):
    """Traverse every matched ring edge before reusing an endpoint pair."""

    def edge(self, sequence: int) -> tuple[int, int]:
        """Derive endpoints from admission sequence, not dropped offer slots."""
        vertex = 2 * (((sequence - 1) // 2) % (self.vertices // 2))
        return vertex, vertex + 1


def _produce(channel, result, started, rate, query_rate, seconds, ipc_batch=1):
    """Send without blocking on IPC or update acknowledgment; return fixed counters."""
    stop = threading.Event()
    counters = [[0, 0, 0], [0, 0, 0]]
    failures = []

    def offer(kind, offered_rate):
        schedule = Schedule(started, offered_rate, seconds, stop)
        sent = dropped = 0
        packet = bytearray()

        def flush():
            nonlocal sent, dropped
            count = len(packet) // _PACKET.size
            try:
                written = channel.send(packet, socket.MSG_DONTWAIT)
                if written != len(packet):
                    raise RuntimeError("partial datagram send")
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS):
                    raise
                dropped += count
            else:
                sent += count
            packet.clear()

        try:
            for due in schedule:
                packet.extend(_PACKET.pack(kind, due))
                if len(packet) == ipc_batch * _PACKET.size:
                    flush()
            if packet:
                flush()
        except BaseException as error:
            failures.append(repr(error))
            stop.set()
        finally:
            counters[kind] = [sent, dropped, schedule.missed]

    threads = [
        threading.Thread(target=offer, args=(0, rate)),
        threading.Thread(target=offer, args=(1, query_rate)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result.send(
            (counters, failures, rss if sys.platform == "darwin" else rss * 1024)
        )
        # Keep the datagram endpoint alive until all reported sends are drained.
        # macOS can reset a receiving socketpair when its peer closes.
        if not result.poll(30) or result.recv() != "drained":
            raise RuntimeError("independent offer receiver did not confirm drain")
    finally:
        channel.close()
        result.close()


def measure(
    path: Path,
    vertices: int,
    rate: int,
    seconds: int,
    *,
    query_rate: int = 1000,
    queue_capacity: int = 512,
    ipc_bytes: int = 16384,
    ipc_batch: int = 1,
    workload: str = "hot",
) -> dict:
    """Reconcile every external offer, bounded admission, publication and recovery."""
    if (
        any(
            type(value) is not int
            for value in (
                vertices,
                rate,
                seconds,
                query_rate,
                queue_capacity,
                ipc_bytes,
                ipc_batch,
            )
        )
        or not 8 <= vertices <= 1000000
        or vertices % 2
        or not 10 <= rate <= 100000
        or not 1 <= seconds <= 1800
        or not 10 <= query_rate <= 10000
        or not 2 <= queue_capacity <= 4096
        or not 1024 <= ipc_bytes <= 65536
        or not 1 <= ipc_batch <= 64
    ):
        raise ValueError("invalid bounded independent-load envelope")
    if workload not in ("hot", "sweep"):
        raise ValueError("require hot or sweep workload")
    traffic = Hot(vertices) if workload == "hot" else Sweep(vertices)
    if path.exists():
        raise ValueError("benchmark requires a fresh database")
    context = multiprocessing.get_context("spawn")
    receive, send = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    receive.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, ipc_bytes)
    send.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, ipc_bytes)
    send_bytes = send.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
    receive.settimeout(0.01)
    report, writer = context.Pipe(duplex=True)
    service = None
    process = None
    pending = deque()
    ack, offered_ack, queries = Histogram(), Histogram(), Histogram()
    received = [0, 0]
    accepted = busy = query_busy = query_count = peak_pending = 0
    previous = 1
    try:
        service = Service(path, n=vertices, queue_capacity=queue_capacity)
        # Spawn/import startup is excluded but measured arrival timestamps are
        # never reset to reception. The producer may still miss late startup slots.
        started = time.perf_counter_ns() + 1_000_000_000
        process = context.Process(
            target=_produce,
            args=(send, writer, started, rate, query_rate, seconds, ipc_batch),
        )
        process.start()
        send.close()
        writer.close()
        deadline = started + (seconds + 30) * 1_000_000_000
        final = None

        def finish(item):
            sequence, receipt, due = item
            outcome = receipt.result(30)
            if (
                outcome.sequence != sequence
                or not outcome.changed
                or outcome.version != sequence + 1
            ):
                raise RuntimeError("expected a real durable edge change")
            now = time.perf_counter_ns()
            timing = receipt.timing()
            if timing is None:
                raise RuntimeError("completed receipt lacks timing")
            ack.record(now - timing.admitted_ns)
            offered_ack.record(now - due)

        while True:
            while pending and pending[0][1].done():
                finish(pending.popleft())
            if final is None and report.poll():
                final = report.recv()
            if final is not None and sum(received) == sum(c[0] for c in final[0]):
                break
            if time.perf_counter_ns() > deadline:
                raise TimeoutError("independent producer/IPC drain exceeded deadline")
            if final is None and not process.is_alive() and not report.poll():
                raise RuntimeError("independent producer exited without counters")
            try:
                data = receive.recv(_PACKET.size * ipc_batch + 1)
            except TimeoutError:
                continue
            if not data or len(data) % _PACKET.size:
                raise RuntimeError("invalid independent offer packet")
            for kind, due in _PACKET.iter_unpack(data):
                if kind not in (0, 1) or not started <= due < started + seconds * 10**9:
                    raise RuntimeError("invalid independent offer timestamp/kind")
                received[kind] += 1
                if kind == 1:
                    try:
                        version, partner = service.partner(0).result(0)
                    except BusyError:
                        query_busy += 1
                        continue
                    if version < previous or partner != traffic.partner(version):
                        raise RuntimeError(
                            "query disagrees with exact committed prefix"
                        )
                    previous = version
                    query_count += 1
                    queries.record(time.perf_counter_ns() - due)
                else:
                    request = Request(
                        accepted + 1,
                        "delete" if accepted % 2 == 0 else "insert",
                        *traffic.edge(accepted + 1),
                    )
                    try:
                        receipt = service.submit(request)
                    except BusyError:
                        busy += 1
                    else:
                        accepted += 1
                        pending.append((accepted, receipt, due))
                        peak_pending = max(peak_pending, len(pending))
                        if len(pending) > queue_capacity + 256:
                            raise RuntimeError("client receipt envelope exceeded")
        counters, failures, producer_rss = final
        report.send("drained")
        if failures:
            raise RuntimeError(f"independent producer failed: {failures}")
        process.join(5)
        if process.is_alive() or process.exitcode != 0:
            raise RuntimeError("independent producer did not finish cleanly")
        before_drain = ack.count
        for item in pending:
            finish(item)
        elapsed = (time.perf_counter_ns() - started) / 10**9
        status, metrics = service.status().result(10), service.metrics()
        if (
            sum(counters[0]) != rate * seconds
            or sum(counters[1]) != query_rate * seconds
            or received != [c[0] for c in counters]
            or accepted + busy != received[0]
            or query_count + query_busy != received[1]
            or ack.count != accepted
            or status["sequence"] != accepted
            or metrics["outstanding"]
        ):
            raise RuntimeError("external offer/admission/completion counts disagree")
        expected = live_digest(service, vertices, status)
        buffers = {
            "requested_bytes": ipc_bytes,
            "receive_bytes": receive.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
            "send_bytes": send_bytes,
        }
    finally:
        receive.close()
        send.close()
        report.close()
        writer.close()
        if process is not None and process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
        if service is not None:
            service.close(30)
    with Durable(path) as recovered:
        removed = {traffic.edge(accepted)} if accepted % 2 else set()
        if certificate(recovered, set(), removed, vertices) != expected:
            raise RuntimeError("independent-load exact recovery failed")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "separate-process paced arrivals over bounded local datagrams; NOT production network/power-cut qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "workload": workload,
        "rate": rate,
        "query_rate": query_rate,
        "seconds": seconds,
        "ipc_buffers": buffers,
        "ipc_batch": ipc_batch,
        "planned_updates": rate * seconds,
        "producer_missed_updates": counters[0][2],
        "ipc_dropped_updates": counters[0][1],
        "busy_updates": busy,
        "real_acknowledged_updates": accepted,
        "acknowledged_before_drain": before_drain,
        "offering_and_drain_seconds": elapsed,
        "real_acknowledged_updates_per_second": accepted / elapsed,
        "planned_queries": query_rate * seconds,
        "producer_missed_queries": counters[1][2],
        "ipc_dropped_queries": counters[1][1],
        "busy_queries": query_busy,
        "partner_queries": query_count,
        "peak_client_receipts": peak_pending,
        "service_metrics": metrics,
        "final_status": status,
        "acknowledged_latency": ack.summary(),
        "offered_to_acknowledged_latency": offered_ack.summary(),
        "offered_query_latency": queries.summary(),
        "matching_digest": expected,
        "independent_exact_audit_and_recovery_passed": True,
        "owner_process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "producer_process_peak_rss_bytes": producer_rss,
    }


def main():
    """Run bounded independent arrivals and print all loss classes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--rate", type=int, default=10000)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--query-rate", type=int, default=1000)
    parser.add_argument("--queue-capacity", type=int, default=512)
    parser.add_argument("--ipc-bytes", type=int, default=16384)
    parser.add_argument("--ipc-batch", type=int, default=1)
    parser.add_argument("--workload", choices=("hot", "sweep"), default="hot")
    args = parser.parse_args()
    options = vars(args)
    options["path"] = options.pop("database")
    print(json.dumps(measure(**options), indent=2))


if __name__ == "__main__":
    main()
