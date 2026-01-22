# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
import time
from pathlib import Path

import jubilant
import lightkube
import pytest
import yaml
from charms_dependencies import METACONTROLLER_OPERATOR
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Secret, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding

from .helpers import deploy_k8s_resources

logger = logging.getLogger(__name__)

CHARM_NAME = "resource-dispatcher"
MANIFEST_CHARM_NAME1 = "manifests-tester1"
MANIFEST_CHARM_NAME2 = "manifests-tester2"
MANIFESTS_REQUIRER_TESTER_CHARM = Path("tests/integration/manifests-tester").absolute()
MANIFESTS_TESTER_CONFIG = yaml.safe_load(
    Path("./tests/integration/manifests-tester/config.yaml").read_text()
)
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
NAMESPACE_FILE = "./tests/integration/namespace.yaml"
PODDEFAULTS_CRD_TEMPLATE = "./tests/integration/crds/poddefaults.yaml"
TESTING_LABELS = ["user.kubeflow.org/enabled"]  # Might be more than one in the future
SECRET_NAME = "mlpipeline-minio-artifact"
SERVICE_ACCOUNT_NAME = MANIFESTS_TESTER_CONFIG["options"]["service_account_name"]["default"]
TESTER1_SECRET_NAMES = ["mlpipeline-minio-artifact", "seldon-rclone-secret"]
TESTER2_SECRET_NAMES = ["mlpipeline-minio-artifact2", "seldon-rclone-secret2"]
PODDEFAULTS_NAMES = ["access-minio", "mlflow-server-minio"]
TESTER1_ROLE_NAMES = ["test1-role"]
TESTER2_ROLE_NAMES = ["test2-role"]
TESTER1_ROLEBINDING_NAMES = ["test1-rolebinding"]
TESTER2_ROLEBINDING_NAMES = ["test2-rolebinding"]

PodDefault = create_namespaced_resource("kubeflow.org", "v1alpha1", "PodDefault", "poddefaults")


@pytest.mark.abort_on_fail
def test_build_and_deploy_dispatcher_charm(juju: jubilant.Juju, resource_dispatcher_charm: Path):
    deploy_k8s_resources([PODDEFAULTS_CRD_TEMPLATE])

    juju.deploy(
        charm=METACONTROLLER_OPERATOR.charm,
        channel=METACONTROLLER_OPERATOR.channel,
        trust=METACONTROLLER_OPERATOR.trust,
    )

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    juju.deploy(
        charm=resource_dispatcher_charm,
        app=CHARM_NAME,
        resources=resources,
        trust=True,
    )
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
def test_build_and_deploy_helper_charms(juju: jubilant.Juju, manifest_tester_charm: Path):
    juju.deploy(
        charm=manifest_tester_charm,
        app=MANIFEST_CHARM_NAME1,
        trust=True,
    )
    juju.deploy(
        charm=manifest_tester_charm,
        app=MANIFEST_CHARM_NAME2,
        trust=True,
        config={"manifests_folder": "src/manifests2", "service_account_name": "config-secret-2"},
    )

    juju.integrate(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME1}:secrets")
    juju.integrate(f"{CHARM_NAME}:service-accounts", f"{MANIFEST_CHARM_NAME1}:service-accounts")
    juju.integrate(f"{CHARM_NAME}:pod-defaults", f"{MANIFEST_CHARM_NAME1}:pod-defaults")
    juju.integrate(f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME1}:roles")
    juju.integrate(f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME1}:role-bindings")

    juju.integrate(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME2}:secrets")
    juju.integrate(f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME2}:roles")
    juju.integrate(f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME2}:role-bindings")

    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
def test_manifests_created_from_both_helpers(
    lightkube_client: lightkube.Client, namespace: str
) -> None:
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    secret = lightkube_client.get(Secret, SECRET_NAME, namespace=namespace)
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
    for name in TESTER1_SECRET_NAMES + TESTER2_SECRET_NAMES:
        secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert secret != None
    for name in PODDEFAULTS_NAMES:
        pod_default = lightkube_client.get(PodDefault, name, namespace=namespace)
        assert pod_default != None
    for name in TESTER1_ROLE_NAMES + TESTER2_ROLE_NAMES:
        role = lightkube_client.get(Role, name, namespace=namespace)
        assert role != None
    for name in TESTER1_ROLEBINDING_NAMES + TESTER2_ROLEBINDING_NAMES:
        rb = lightkube_client.get(RoleBinding, name, namespace=namespace)
        assert rb != None


@pytest.mark.abort_on_fail
def test_remove_relation(juju: jubilant.Juju):
    """Make sure that charm goes to active state after relation is removed"""
    juju.remove_relation(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME1}:secrets")
    juju.remove_relation(f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME1}:roles")
    juju.remove_relation(f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME1}:role-bindings")
    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=10
    )


@pytest.mark.abort_on_fail
def test_remove_one_helper_relation(lightkube_client: lightkube.Client, namespace: str):
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    for name in TESTER2_SECRET_NAMES:
        secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert secret != None
    for name in TESTER2_ROLE_NAMES:
        role = lightkube_client.get(Role, name, namespace=namespace)
        assert role != None
    for name in TESTER2_ROLEBINDING_NAMES:
        rolebinding = lightkube_client.get(RoleBinding, name, namespace=namespace)
        assert rolebinding != None
    for name in TESTER1_SECRET_NAMES:
        with pytest.raises(ApiError) as e_info:
            secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert "not found" in str(e_info)
    for name in TESTER1_ROLE_NAMES:
        with pytest.raises(ApiError) as e_info:
            role = lightkube_client.get(Role, name, namespace=namespace)
        assert "not found" in str(e_info)
    for name in TESTER1_ROLEBINDING_NAMES:
        with pytest.raises(ApiError) as e_info:
            rolebinding = lightkube_client.get(RoleBinding, name, namespace=namespace)
        assert "not found" in str(e_info)
