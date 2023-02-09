import logging
import shlex
from pathlib import Path

import pytest

log = logging.getLogger(__name__)


def remove_ext(path: Path) -> str:
    suffixes = "".join(path.suffixes)
    return path.name.replace(suffixes, "")


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, series: str, snap_channel: str):
    """Build and deploy Canal in bundle."""
    charm = next(Path.cwd().glob("canal*.charm"), None)
    if not charm:
        log.info("Build Charm...")
        charm = await ops_test.build_charm(".")

    resources = list(Path.cwd().glob("flannel*.tar.gz")) + list(
        Path.cwd().glob("calico*.tar.gz")
    )
    if not resources:
        log.info("Build Resources...")
        build_script = Path.cwd() / "build-canal-resources.sh"
        resources = await ops_test.build_resources(build_script, with_sudo=False)
    expected_resources = {
        "flannel-amd64",
        "flannel-arm64",
        "calico-amd64",
        "calico-arm64",
        "calico-node-image",
    }

    if resources and all(remove_ext(rsc) in expected_resources for rsc in resources):
        resources = {remove_ext(rsc).replace("-", "_"): rsc for rsc in resources}
    else:
        log.info("Failed to build resources, downloading from latest/edge")
        arch_resources = ops_test.arch_specific_resources(charm)
        resources = await ops_test.download_resources(charm, resources=arch_resources)
        resources = {name.replace("-", "_"): rsc for name, rsc in resources.items()}

    assert resources, "Failed to build or download charm resources."

    log.info("Build Bundle...")
    context = dict(charm=charm, series=series, snap_channel=snap_channel, **resources)
    overlays = [
        ops_test.Bundle("kubernetes-core", channel="edge"),
        Path("tests/data/charm.yaml"),
    ]
    bundle, *overlays = await ops_test.async_render_bundles(*overlays, **context)

    log.info("Deploy Bundle...")
    model = ops_test.model_full_name
    cmd = f"juju deploy -m {model} {bundle} " + " ".join(
        f"--overlay={f}" for f in overlays
    )
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))
    assert rc == 0, "Bundle deploy failed: {}".format((stderr or stdout).strip())

    await ops_test.model.wait_for_idle(status="active", timeout=60 * 60, idle_period=60)
