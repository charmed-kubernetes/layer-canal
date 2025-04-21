import re
import subprocess
import logging
import packaging.version
import pytest

log = logging.getLogger(__name__)
STABLE_CHANNEL = re.compile(r"^\s+(\d+\.\d+)\/stable:\s+(\S+)")


def default_kubernetes_channel() -> str:
    """
    Get the default Kubernetes snap channel.
    """
    result = subprocess.run(
        ["snap", "info", "kubelet"],
        capture_output=True,
        text=True,
        check=True,
    )
    stables = [
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := STABLE_CHANNEL.match(line))  # numerical channel
        and match.group(2) != "--"  # not an empty channel
    ]
    if not stables:
        raise RuntimeError("No stable channel found for kubelet snap")
    most_stable = sorted(stables, key=packaging.version.parse, reverse=True)[0]
    log.debug(f"Most stable channel found: {most_stable}")
    return f"{most_stable}/stable"


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str,
        default="jammy",
        help="Set series for the machine units",
    )
    parser.addoption(
        "--snap-channel",
        type=str,
        default=default_kubernetes_channel(),
        help="Set snap channel for the control-plane & worker units",
    )


@pytest.fixture()
def series(request):
    return request.config.getoption("--series")


@pytest.fixture()
def snap_channel(request):
    return request.config.getoption("--snap-channel")
