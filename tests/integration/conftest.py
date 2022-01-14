import asyncio
from itertools import chain
import logging
from pathlib import Path
import pytest
import shlex
from urllib.request import urlretrieve

log = logging.getLogger(__name__)
CNI_ARCH_URL = "https://api.jujucharms.com/charmstore/v5/~containers/canal-{charm}/resource/{resource}"  # noqa


async def _retrieve_url(charm, resource, target_file):
    url = CNI_ARCH_URL.format(
        charm=charm,
        resource=resource
    )
    urlretrieve(url, target_file)


@pytest.fixture()
async def setup_resources(ops_test):
    """Provides the flannel resources needed to deploy the charm."""
    resource_path = Path.cwd()
    current_resources = list(resource_path.glob("*.tar.gz"))
    tmpdir = ops_test.tmp_path / "resources"
    tmpdir.mkdir(parents=True, exist_ok=True)
    if not current_resources:
        # If they are not locally available, try to build them
        log.info("Build Resources...")
        build_script = resource_path / "build-canal-resources.sh"
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
        resources = (
            resource+arch
            for resource in ("flannel", "calico", "calico-upgrade")
            for arch in ("", "-arm64")
        )
        await asyncio.gather(
            *(
                _retrieve_url(859, resource, tmpdir / "{}.tar.gz".format(resource))
                for resource in chain(resources, ("calico-node-image",))
            ),
        )
        current_resources = list(Path(tmpdir).glob("*.tar.gz"))
        resource_path = tmpdir
    if not current_resources:
        pytest.fail("Could not prepare necessary resources for testing charm")

    yield resource_path
