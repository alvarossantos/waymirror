"""Headless concurrency regression tests for the single-session state machine."""

from __future__ import annotations

import multiprocessing
import os
import time
from dataclasses import dataclass

from waymirror.mirror import MirrorManager
from waymirror.state import StateStore


@dataclass
class _FakeProc:
    pid: int


def _start_worker(state_path, calls_path, start_gate, results) -> None:
    """One process attempting `start` against the shared state file."""

    def runner(cmd):
        with open(calls_path, "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n")
        # Widen the window between observing empty state and recording the session.
        time.sleep(0.25)
        return _FakeProc(pid=os.getpid())

    manager = MirrorManager(
        StateStore(state_path),
        runner=runner,
        pid_alive=lambda pid: True,
        now=lambda: "2026-01-01T00:00:00Z",
        killer=lambda pid, sig: None,
        waiter=lambda pid: True,
    )
    start_gate.wait(10)
    try:
        result = manager.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
        results.put((os.getpid(), result.action))
    except Exception as exc:  # noqa: BLE001 - report worker failures to the parent
        results.put((os.getpid(), f"error: {exc}"))


def test_concurrent_start_spawns_only_one_session(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    calls_path = tmp_path / "spawns.log"
    ctx = multiprocessing.get_context("fork")
    gate = ctx.Event()
    results = ctx.Queue()
    workers = [
        ctx.Process(target=_start_worker, args=(state_path, calls_path, gate, results))
        for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    gate.set()
    try:
        actions = [results.get(timeout=15)[1] for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
        assert all(not worker.is_alive() for worker in workers)
        assert all(worker.exitcode == 0 for worker in workers)

        spawns = calls_path.read_text(encoding="utf-8").splitlines()
        assert len(spawns) == 1, f"expected one spawned mirror, got {spawns!r} (actions={actions!r})"
        assert sorted(actions) == ["already_running", "started"]
        session = StateStore(state_path).load()
        assert session is not None
        assert str(session.pid) == spawns[0]
    finally:
        gate.set()
        for worker in workers:
            worker.join(timeout=15)
