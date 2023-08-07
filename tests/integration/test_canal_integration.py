import json
import logging
import re
import shlex
import shutil
from ipaddress import ip_address, ip_network
from pathlib import Path
from time import sleep

import pytest
from kubernetes import client
from kubernetes.config import load_kube_config_from_dict

log = logging.getLogger(__name__)

##
# Flannel related tests
#
# As canal uses the flannel networking model, the following tests borrow heavily
# from the charm-flannel integration tests.
##


def _get_flannel_subnet(unit):
    """Get the flannel subnet for a given canal unit."""
    subnet = re.findall(r"[0-9]+(?:\.[0-9]+){3}", unit.workload_status_message)[0]
    return ip_address(subnet)


async def _get_kubeconfig(model):
    """Get kubeconfig from kubernetes-control-plane."""
    unit = model.applications["kubernetes-control-plane"].units[0]
    action = await unit.run_action("get-kubeconfig")
    output = await action.wait()  # wait for result
    return json.loads(output.results.get("kubeconfig", "{}"))


async def _create_test_pod(model):
    """Create tests pod and return spec."""
    # load kubernetes config
    kubeconfig = await _get_kubeconfig(model)
    load_kube_config_from_dict(kubeconfig)

    api = client.CoreV1Api()
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "test"},
        "spec": {
            "containers": [
                {
                    "image": "rocks.canonical.com/cdk/busybox:1.32",
                    "name": "test",
                    "args": ["echo", '"test"'],
                }
            ]
        },
    }
    log.info("Creating Test Pod")
    resp = api.create_namespaced_pod(body=pod_manifest, namespace="default")
    # wait for pod not to be in pending
    i = 0
    while resp.status.phase == "Pending" and i < 30:
        i += 1
        log.info("pod pending {s} seconds...".format(s=(i - 1) * 10))
        sleep(10)
        resp = api.read_namespaced_pod("test", namespace="default")

    api.delete_namespaced_pod("test", namespace="default")
    return resp


def _remove_ext(path: Path) -> str:
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
    if resources:
        log.info("Using pre-built resources...")
        resource_dir = ops_test.tmp_path / "resources"
        resource_dir.mkdir(exist_ok=True)
        for resource in resources:
            shutil.copy(resource, resource_dir)
        resources = list(resource_dir.glob("*"))
    else:
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

    if resources and all(_remove_ext(rsc) in expected_resources for rsc in resources):
        resources = {_remove_ext(rsc).replace("-", "_"): rsc for rsc in resources}
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


async def test_canal_network(ops_test):
    """Verify network for canal units and pods."""
    canal = ops_test.model.applications["canal"]
    canal_config = await canal.get_config()
    cidr_network = ip_network(canal_config.get("cidr", {}).get("value"))

    # verify flannel subnet is in the cidr range
    for unit in canal.units:
        assert unit.workload_status == "active"
        subnet = _get_flannel_subnet(unit)
        log.info(f"{unit.name} reports subnet {subnet}")
        assert subnet in cidr_network

    # verify a pod IP is in the cidr range
    resp = await _create_test_pod(ops_test.model)
    assert (
        ip_address(resp.status.pod_ip) in cidr_network
    ), "test pod does not have an ip address in the cidr network"
