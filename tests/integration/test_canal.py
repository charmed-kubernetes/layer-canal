import logging
import pytest
from pathlib import Path
import shlex

log = logging.getLogger(__name__)

CHARM_DIR = Path(__file__).parent.parent.parent
RESOURCE_BUILD_SCRIPT = CHARM_DIR / "build-canal-resources.sh"
BUNDLE_PATH = Path(__file__).parent / "bundle.yaml"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    resource_path = ops_test.tmp_path / "charm-resources"
    resource_path.mkdir()
    log.info("Building charm resources")
    await ops_test.run(
        RESOURCE_BUILD_SCRIPT,
        cwd=resource_path,
        check=True,
        fail_msg="Failed to build charm resources",
    )
    bundle = ops_test.render_bundle(
        "tests/data/bundle.yaml",
        canal_charm=await ops_test.build_charm("."),
        resource_path=resource_path,
    )
    # deploy with Juju CLI because libjuju does not support local resource
    # files (see https://github.com/juju/python-libjuju/issues/223)
    log.info("Deploying bundle")
    await ops_test.run(
        "juju",
        "deploy",
        "-m",
        ops_test.model_full_name,
        bundle,
        check=True,
        fail_msg="Failed to deploy bundle",
    )
    try:
        await ops_test.model.wait_for_idle(wait_for_active=True, timeout=30 * 60)
    finally:
        model = ops_test.model_full_name
        cmd = f"juju-crashdump -s -a debug-layer -a config -m {model}"
        await ops_test.run(*shlex.split(cmd))
        k8s_cp = "kubernetes-control-plane"
        unit = ops_test.model.applications[k8s_cp].units[0]
        response = await unit.run(
            "kubectl --kubeconfig /root/.kube/config get all -A", timeout=30
        )
        log.info(response.results["Stdout"] or response.results["Stderr"])
