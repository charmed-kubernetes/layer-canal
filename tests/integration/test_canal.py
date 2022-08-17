import logging
import pytest
from pathlib import Path
import shlex


log = logging.getLogger(__name__)
CHARM_DIR = Path(__file__).parent.parent.parent
RESOURCE_BUILD_SCRIPT = CHARM_DIR / "build-canal-resources.sh"
BUNDLE_PATH = Path(__file__).parent / "bundle.yaml"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, setup_resources):
    log.info("Build Charm...")
    charm = await ops_test.build_charm(".")

    log.info("Build Bundle...")
    bundle = ops_test.render_bundle(
        "tests/data/bundle.yaml",
        canal_charm=charm,
        resource_path=setup_resources,
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
        await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
    finally:
        model = ops_test.model_full_name
        cmd = f"juju-crashdump -s -a debug-layer -a config -m {model}"
        await ops_test.run(*shlex.split(cmd))
        k8s_cp = "kubernetes-control-plane"
        unit = ops_test.model.applications[k8s_cp].units[0]
        action = await unit.run(
            "kubectl --kubeconfig /root/.kube/config get all -A", timeout=30
        )
        response = await action.wait()
        log.info(response.results["stdout"] or response.results["stderr"])
