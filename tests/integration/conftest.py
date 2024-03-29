import logging
import pytest

log = logging.getLogger(__name__)


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
        default="latest/stable",
        help="Set snap channel for the control-plane & worker units",
    )


@pytest.fixture()
def series(request):
    return request.config.getoption("--series")


@pytest.fixture()
def snap_channel(request):
    return request.config.getoption("--snap-channel")
