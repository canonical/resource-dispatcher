# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests the charm behavior when manifests-tester charm is first upgraded,
and only then resource-dispatcher charm is upgraded. 

This is not the correct sequence of upgrade because the resource-dispatcher that uses kubernetes_manifests 0.1 
won't work with the manifests-tester that uses kubernetes_manifests 0.2.

However, the purpose of this test is that even if the sequence of upgrade of charms is accidentally altered,
the charms will eventually recover once both the charms are upgraded at the end.
"""

import base64
import logging
import time
from pathlib import Path

import jubilant
import lightkube
import pytest
import yaml
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Secret, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding

from .helpers import METACONTROLLER_OPERATOR, deploy_k8s_resources

logger = logging.getLogger(__name__)

CHARM_NAME = "resource-dispatcher"
MANIFESTS_TESTER_CONFIG = yaml.safe_load(
    Path("./tests/integration/manifests-tester/config.yaml").read_text()
)

MANIFEST_TESTER_CHARM = "manifests-tester"
MINIO_SECRET_NAME_OLD = "mlpipeline-minio-artifact3"
MINIO_SECRET_NAME_NEW = "mlpipeline-minio-artifact"
SERVICE_ACCOUNT_NAME = MANIFESTS_TESTER_CONFIG["options"]["service_account_name"]["default"]
SERVICE_ACCOUNT_NAME_2 = SERVICE_ACCOUNT_NAME + "-2"
SERVICE_ACCOUNT_NAME_3 = SERVICE_ACCOUNT_NAME + "-3"


TESTER_SECRET_NAMES_OLD = ["mlpipeline-minio-artifact3", "seldon-rclone-secret3"]
TESTER_SECRET_NAMES_NEW = ["mlpipeline-minio-artifact", "seldon-rclone-secret"]

TESTER_PODDEFAULTS_NAMES_OLD = ["access-minio-3", "mlflow-server-minio-3"]
TESTER_PODDEFAULTS_NAMES_NEW = ["access-minio", "mlflow-server-minio"]

TESTER_ROLE_NAMES = ["test1-role"]
TESTER_ROLEBINDING_NAMES = ["test1-rolebinding"]


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PODDEFAULTS_CRD_TEMPLATE = "./tests/integration/resources/crds/poddefaults.yaml"
TESTING_LABELS = ["user.kubeflow.org/enabled"]  # Might be more than one in the future


PodDefault = create_namespaced_resource("kubeflow.org", "v1alpha1", "PodDefault", "poddefaults")


def test_deploy_metacontroller_setup(juju: jubilant.Juju):
    """Deploy necessary setup for resource-dispatcher charm to work."""
    deploy_k8s_resources([PODDEFAULTS_CRD_TEMPLATE])

    juju.deploy(
        charm=METACONTROLLER_OPERATOR.charm,
        channel=METACONTROLLER_OPERATOR.channel,
        trust=METACONTROLLER_OPERATOR.trust,
    )
    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )


def test_deploy_resource_dispatcher_charm(juju: jubilant.Juju):
    """Deploy resource-dispatcher charm from 2.0/stable channel, which uses kubernetes_manifest lib 0.1."""
    juju.deploy(
        charm=CHARM_NAME,
        app=CHARM_NAME,
        channel="2.0/stable",
        trust=True,
    )
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


def test_build_and_deploy_tester_charm(juju: jubilant.Juju, manifest_tester_no_secret_charm: Path):
    """Deploy manifest-tester charm, that uses kubernetes_manifest lib 0.2."""
    juju.deploy(
        charm=manifest_tester_no_secret_charm,
        app=MANIFEST_TESTER_CHARM,
        trust=True,
    )
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


def test_integrate_tester_with_resource_dispatcher(juju: jubilant.Juju):
    """Integrate manifest-tester charm with resource-dispatcher."""
    juju.integrate(f"{CHARM_NAME}:secrets", f"{MANIFEST_TESTER_CHARM}:secrets")
    juju.integrate(f"{CHARM_NAME}:service-accounts", f"{MANIFEST_TESTER_CHARM}:service-accounts")
    juju.integrate(f"{CHARM_NAME}:pod-defaults", f"{MANIFEST_TESTER_CHARM}:pod-defaults")
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


def test_manifests_created_from_tester_charm_old(
    lightkube_client: lightkube.Client, namespace: str
) -> None:
    """Ensure that resources from the old manifest-tester charm are created in K8s cluster."""
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    secret = lightkube_client.get(Secret, MINIO_SECRET_NAME_OLD, namespace=namespace)
    service_account = lightkube_client.get(
        ServiceAccount, SERVICE_ACCOUNT_NAME, namespace=namespace
    )
    # Teting one secret for content
    assert secret.data == {
        "AWS_ACCESS_KEY_ID": base64.b64encode("access_key".encode("utf-8")).decode("utf-8"),
        "AWS_SECRET_ACCESS_KEY": base64.b64encode("secret_access_key".encode("utf-8")).decode(
            "utf-8"
        ),
    }
    assert service_account != None
    for name in TESTER_SECRET_NAMES_OLD:
        secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert secret != None
    for name in TESTER_PODDEFAULTS_NAMES_OLD:
        pod_default = lightkube_client.get(PodDefault, name, namespace=namespace)
        assert pod_default != None


def test_upgrade_tester_charm(juju: jubilant.Juju, manifest_tester_charm: Path):
    """Upgrade manifest-tester charm in-place to the implementation that uses kubernetes_manifest v0.2."""
    juju.refresh(
        app=MANIFEST_TESTER_CHARM,
        path=manifest_tester_charm,
    )

    # The resource-dispatcher charm will be in error, because it cannot decode secret sent by manifest-tester
    status = juju.wait(
        lambda status: jubilant.all_error(status, CHARM_NAME)
        and jubilant.all_active(status, MANIFEST_TESTER_CHARM)
        and jubilant.all_agents_idle(status),
        delay=5,
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "error"


def test_upgrade_resource_dispatcher(juju: jubilant.Juju, resource_dispatcher_charm: Path):
    """Upgrade resource-dispatcher charm in-place to the current implementation (that uses kubernetes_manifest v0.2)"""
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}
    juju.refresh(app=CHARM_NAME, path=resource_dispatcher_charm, resources=resources)

    # The charm should eventually settle to active idle state
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


def test_integrate_new_relations_with_resource_dispatcher(
    juju: jubilant.Juju, lightkube_client: lightkube.Client, namespace: str
):
    """Integrate manifest-tester charm with resource-dispatcher over newly added roles and role-bindings relation."""
    juju.integrate(f"{CHARM_NAME}:roles", f"{MANIFEST_TESTER_CHARM}:roles")
    juju.integrate(f"{CHARM_NAME}:role-bindings", f"{MANIFEST_TESTER_CHARM}:role-bindings")
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    for name in TESTER_ROLE_NAMES:
        role = lightkube_client.get(Role, name, namespace=namespace)
        assert role != None
    for name in TESTER_ROLEBINDING_NAMES:
        rb = lightkube_client.get(RoleBinding, name, namespace=namespace)
        assert rb != None


def test_change_in_manifest_reflected_again(
    juju: jubilant.Juju,
    lightkube_client: lightkube.Client,
    namespace: str,
):
    """Change the config in manifest-tester, such that the manifests are changed, and verify they are reflected in the K8s resources."""
    juju.config(MANIFEST_TESTER_CHARM, {"service_account_name": SERVICE_ACCOUNT_NAME_2})
    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=10
    )
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)

    with pytest.raises(ApiError) as e_info:
        lightkube_client.get(ServiceAccount, SERVICE_ACCOUNT_NAME, namespace=namespace)
    service_account = lightkube_client.get(
        ServiceAccount, SERVICE_ACCOUNT_NAME_2, namespace=namespace
    )
    assert service_account != None
