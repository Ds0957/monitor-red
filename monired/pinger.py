"""Continuous ping engine.

Two backends feed the same status tracking:
- process (Linux): one long-running system `ping -O` per device, read line by line;
- probe (Windows, or tests): one echo request per interval through a callable
  `probe(ip, timeout) -> rtt_ms | None`, run in a thread pool.
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

PENDING, UP, DOWN = "pending", "up", "down"

_REPLY = re.compile(r"bytes from .*time[=<]([0-9.]+)")
_MISS = re.compile(r"no answer yet|Unreachable|timed out|Time to live exceeded", re.IGNORECASE)


def parse_line(line: str) -> tuple[str, float | None] | None:
    """Classify one line of `ping -O` output as a reply, a miss, or noise."""
    if "DUP!" in line:
        return None
    if m := _REPLY.search(line):
        return UP, float(m.group(1))
    if _MISS.search(line):
        return DOWN, None
    return None


@dataclass
class Status:
    sent: int = 0
    received: int = 0
    last_rtt: float | None = None
    rtt_total: float = 0.0
    streak: int = 0            # consecutive missed replies
    state: str = PENDING
    down_since: datetime | None = None
    last_down: datetime | None = None

    @property
    def loss(self) -> float:
        return (self.sent - self.received) * 100 / self.sent if self.sent else 0.0

    @property
    def avg_rtt(self) -> float | None:
        return self.rtt_total / self.received if self.received else None


ChangeCallback = Callable[[int, str, datetime], None]
Probe = Callable[[str, float], "float | None"]


def default_probe() -> Probe | None:
    """The native probe for this platform, or None to use the `ping` process backend."""
    if sys.platform == "win32":
        from .winicmp import ping

        return ping
    return None


class Monitor:
    """Keeps one ping process per (device id, ip) and tracks each device's status.

    A device is DOWN after `down_after` consecutive missed replies and UP again on
    the first reply; `on_change` is called on every UP<->DOWN transition.
    """

    def __init__(
        self,
        interval: float = 1.0,
        timeout: int = 1,
        down_after: int = 2,
        on_change: ChangeCallback | None = None,
        ping_cmd: tuple[str, ...] = ("ping",),
        clock: Callable[[], datetime] = datetime.now,
        probe: Probe | None = None,
    ):
        self.interval = interval
        self.timeout = timeout
        self.down_after = down_after
        self.on_change = on_change
        self.ping_cmd = ping_cmd
        self.clock = clock
        self.probe = probe
        self._executor: ThreadPoolExecutor | None = None
        self._tasks: dict[int, tuple[str, asyncio.Task]] = {}
        self._status: dict[int, Status] = {}

    def status(self, device_id: int) -> Status:
        return self._status.get(device_id, Status())

    def targets(self) -> dict[int, str]:
        return {device_id: ip for device_id, (ip, _) in self._tasks.items()}

    async def sync(self, targets: dict[int, str]) -> None:
        """Start, keep or stop pingers so they match `targets` (device id -> ip)."""
        stale = [i for i, (ip, _) in self._tasks.items() if targets.get(i) != ip]
        for device_id in stale:
            await self._stop(device_id)
            self._status.pop(device_id, None)
        for device_id, ip in targets.items():
            if device_id not in self._tasks:
                self._status[device_id] = Status()
                run = self._run_probe if self.probe else self._run
                task = asyncio.create_task(run(device_id, ip))
                self._tasks[device_id] = (ip, task)

    async def stop_all(self) -> None:
        for device_id in list(self._tasks):
            await self._stop(device_id)
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    async def _stop(self, device_id: int) -> None:
        _, task = self._tasks.pop(device_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self, device_id: int, ip: str) -> None:
        args = (*self.ping_cmd, "-O", "-n", "-W", str(self.timeout), "-i", str(self.interval), ip)
        while True:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            try:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    result = parse_line(raw.decode(errors="replace"))
                    if result:
                        self._apply(device_id, *result)
                await proc.wait()
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            # ping exited on its own (bad address, network error): retry shortly.
            await asyncio.sleep(max(self.interval, 2))

    async def _run_probe(self, device_id: int, ip: str) -> None:
        loop = asyncio.get_running_loop()
        if self._executor is None:
            # One blocking echo per device can be in flight at once.
            self._executor = ThreadPoolExecutor(max_workers=256, thread_name_prefix="ping")
        while True:
            started = loop.time()
            try:
                rtt = await loop.run_in_executor(self._executor, self.probe, ip, float(self.timeout))
            except OSError:
                rtt = None
            self._apply(device_id, UP if rtt is not None else DOWN, rtt)
            await asyncio.sleep(max(0.0, self.interval - (loop.time() - started)))

    def _apply(self, device_id: int, kind: str, rtt: float | None) -> None:
        st = self._status.setdefault(device_id, Status())
        now = self.clock()
        st.sent += 1
        if kind == UP:
            st.received += 1
            st.last_rtt = rtt
            st.rtt_total += rtt or 0.0
            st.streak = 0
            if st.state != UP:
                was_down = st.state == DOWN
                st.state, st.down_since = UP, None
                if was_down:
                    self._notify(device_id, UP, now)
        else:
            st.last_rtt = None
            st.streak += 1
            if st.streak >= self.down_after and st.state != DOWN:
                st.state = DOWN
                st.down_since = st.last_down = now
                self._notify(device_id, DOWN, now)

    def _notify(self, device_id: int, state: str, ts: datetime) -> None:
        if self.on_change:
            self.on_change(device_id, state, ts)
