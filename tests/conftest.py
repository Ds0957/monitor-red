import stat
import sys
import textwrap

import pytest

from monired.db import Inventory

# A stand-in for the system `ping`: IPs whose last octet is odd always answer, even ones
# never do. It honours -i so tests run fast.
FAKE_PING = textwrap.dedent(
    """\
    import sys, time
    args = sys.argv[1:]
    ip = args[-1]
    interval = float(args[args.index("-i") + 1])
    seq = 0
    while True:
        seq += 1
        if int(ip.rsplit(".", 1)[1]) % 2:
            print(f"64 bytes from {ip}: icmp_seq={seq} ttl=64 time=1.5 ms", flush=True)
        else:
            print(f"no answer yet for icmp_seq={seq}", flush=True)
        time.sleep(interval)
    """
)


@pytest.fixture
def inv():
    inventory = Inventory(":memory:")
    yield inventory
    inventory.close()


@pytest.fixture
def fake_ping(tmp_path):
    script = tmp_path / "fake_ping.py"
    script.write_text(FAKE_PING)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return (sys.executable, str(script))
