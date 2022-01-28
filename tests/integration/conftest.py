import logging
from pathlib import Path
import pytest
import shlex

log = logging.getLogger(__name__)


def ensure_arch_names(current_resources):
    for resource in current_resources:
        if any(arch in resource.name for arch in ['s390x', 'arm64', 'amd64']):
            continue
        if resource.name == 'calico-node-image.tar.gz':
            # doesn't have an associated arch
            continue
        # without an arch, assume 'amd64'
        head, tail = resource.name.split('.', 1)
        arched_name = "{}-amd64.{}".format(head, tail)
        (resource.parent / arched_name).symlink_to(resource)


@pytest.fixture()
async def setup_resources(ops_test):
    """Provides the flannel resources needed to deploy the charm."""
    script_path = resource_path = Path.cwd()
    current_resources = list(resource_path.glob("*.tar.gz"))
    tmpdir = ops_test.tmp_path / "resources"
    tmpdir.mkdir(parents=True, exist_ok=True)
    if not current_resources:
        # If they are not locally available, try to build them
        log.info("Build Resources...")
        build_script = script_path / "build-canal-resources.sh"
        rc, stdout, stderr = await ops_test.run(
            *shlex.split("sudo {}".format(build_script)), cwd=tmpdir, check=False
        )
        if rc != 0:
            err = (stderr or stdout).strip()
            log.warning("build-flannel-resources failed: {}".format(err))
        current_resources = list(Path(tmpdir).glob("*.tar.gz"))
        resource_path = tmpdir
    if not current_resources:
        # if we couldn't build them, just download a fixed version
        log.info("Downloading Resources...")
        fetch_script = script_path / "fetch-charm-store-resources.sh"
        rc, stdout, stderr = await ops_test.run(
            *shlex.split(str(fetch_script)), cwd=tmpdir, check=False
        )
        if rc != 0:
            err = (stderr or stdout).strip()
            log.warning("fetch-charm-store-resources failed: {}".format(err))
        current_resources = list(Path(tmpdir).glob("*.tar.gz"))
        resource_path = tmpdir
    if not current_resources:
        pytest.fail("Could not prepare necessary resources for testing charm")
    ensure_arch_names(current_resources)
    yield resource_path
