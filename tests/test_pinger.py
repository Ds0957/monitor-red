import asyncio
from datetime import datetime

from monired.pinger import DOWN, PENDING, UP, Monitor, parse_line


def test_parse_line():
    assert parse_line("64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=2.85 ms") == (UP, 2.85)
    assert parse_line("no answer yet for icmp_seq=3") == (DOWN, None)
    assert parse_line("From 10.0.0.9 icmp_seq=1 Destination Host Unreachable") == (DOWN, None)
    assert parse_line("64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=2.9 ms (DUP!)") is None
    assert parse_line("PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.") is None


def test_state_transitions_and_callbacks():
    changes = []
    t = datetime(2026, 10, 30, 8, 0)
    mon = Monitor(down_after=2, on_change=lambda *a: changes.append(a), clock=lambda: t)

    assert mon.status(1).state == PENDING
    mon._apply(1, UP, 2.0)
    assert mon.status(1).state == UP and changes == []      # pending -> up is not an event

    mon._apply(1, DOWN, None)
    assert mon.status(1).state == UP                         # one miss is not "down" yet
    mon._apply(1, DOWN, None)
    st = mon.status(1)
    assert (st.state, st.down_since, st.last_down) == (DOWN, t, t)
    mon._apply(1, DOWN, None)                                # stays down, no repeat event
    mon._apply(1, UP, 4.0)

    st = mon.status(1)
    assert (st.state, st.down_since, st.last_down) == (UP, None, t)
    assert (st.sent, st.received, st.avg_rtt, st.loss) == (5, 2, 3.0, 60.0)
    assert changes == [(1, DOWN, t), (1, UP, t)]


async def test_probe_backend_used_on_windows():
    calls = []

    def probe(ip, timeout):
        calls.append((ip, timeout))
        if ip == "10.0.0.9":
            raise OSError("network down")
        return 3.0 if ip == "10.0.0.1" else None

    mon = Monitor(interval=0.02, down_after=2, probe=probe)
    try:
        await mon.sync({1: "10.0.0.1", 2: "10.0.0.2", 3: "10.0.0.9"})
        for _ in range(100):
            if all(mon.status(i).sent >= 3 for i in (1, 2, 3)):
                break
            await asyncio.sleep(0.02)
        assert (mon.status(1).state, mon.status(1).last_rtt) == (UP, 3.0)
        assert mon.status(2).state == DOWN
        assert mon.status(3).state == DOWN          # a probe error counts as no reply
        assert ("10.0.0.1", 1.0) in calls
    finally:
        await mon.stop_all()
    assert mon.targets() == {}


async def test_monitor_runs_real_processes_and_resyncs(fake_ping):
    changes = []
    mon = Monitor(interval=0.05, down_after=2, ping_cmd=fake_ping, on_change=lambda *a: changes.append(a))
    try:
        await mon.sync({1: "10.0.0.1", 2: "10.0.0.2"})
        for _ in range(100):
            if mon.status(1).received >= 2 and mon.status(2).state == DOWN:
                break
            await asyncio.sleep(0.05)
        assert mon.status(1).state == UP
        assert mon.status(2).state == DOWN
        assert (2, DOWN) in [(c[0], c[1]) for c in changes]

        # Changing an IP restarts that device's pinger from a clean status.
        await mon.sync({1: "10.0.0.1", 2: "10.0.0.11"})
        assert mon.status(2).sent == 0
        for _ in range(100):
            if mon.status(2).state == UP:
                break
            await asyncio.sleep(0.05)
        assert mon.status(2).state == UP

        await mon.sync({1: "10.0.0.1"})
        assert mon.targets() == {1: "10.0.0.1"}
    finally:
        await mon.stop_all()
    assert mon.targets() == {}
