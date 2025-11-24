# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
import shutil
import time
from pathlib import Path

import lightkube
import pytest
import yaml
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charms_dependencies import METACONTROLLER_OPERATOR
from lightkube import codecs
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import (
    create_namespaced_resource,
    load_in_cluster_generic_resources,
)
from lightkube.resources.core_v1 import Secret, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding
from pytest_operator.plugin import OpsTest

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


@pytest.fixture(scope="module")
def copy_libraries_into_tester_charm() -> None:
    """Ensure that the tester charms use the current libraries."""
    lib = Path("lib/charms/resource_dispatcher/v0/kubernetes_manifests.py")
    Path(MANIFESTS_REQUIRER_TESTER_CHARM, lib.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(lib.as_posix(), (MANIFESTS_REQUIRER_TESTER_CHARM / lib).as_posix())


def _safe_load_file_to_text(filename: str) -> str:
    """Returns the contents of filename if it is an existing file, else it returns filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


def delete_all_from_yaml(yaml_text: str, lightkube_client: lightkube.Client = None):
    """Deletes all k8s resources listed in a YAML file via lightkube.

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        lightkube_client: Instantiated lightkube client or None
    """

    if lightkube_client is None:
        lightkube_client = lightkube.Client()

    for obj in codecs.load_all_yaml(yaml_text):
        lightkube_client.delete(type(obj), obj.metadata.name)


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=CHARM_NAME)
    return client


def deploy_k8s_resources(template_files: str):
    lightkube_client = lightkube.Client(field_manager=CHARM_NAME)
    k8s_resource_handler = KubernetesResourceHandler(
        field_manager=CHARM_NAME, template_files=template_files, context={}
    )
    load_in_cluster_generic_resources(lightkube_client)
    k8s_resource_handler.apply()


@pytest.fixture(scope="function")
def namespace(lightkube_client: lightkube.Client):
    yaml_text = _safe_load_file_to_text(NAMESPACE_FILE)
    yaml_rendered = yaml.safe_load(yaml_text)
    for label in TESTING_LABELS:
        yaml_rendered["metadata"]["labels"][label] = "true"
    obj = codecs.from_dict(yaml_rendered)
    lightkube_client.apply(obj)

    yield obj.metadata.name

    delete_all_from_yaml(yaml_text, lightkube_client)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_dispatcher_charm(ops_test: OpsTest):
    deploy_k8s_resources([PODDEFAULTS_CRD_TEMPLATE])

    await ops_test.model.deploy(
        entity_url=METACONTROLLER_OPERATOR.charm,
        channel=METACONTROLLER_OPERATOR.channel,
        trust=METACONTROLLER_OPERATOR.trust,
    )

    built_charm_path = await ops_test.build_charm("./")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=CHARM_NAME,
        resources=resources,
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME, METACONTROLLER_OPERATOR.charm],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
    )

    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_build_and_deploy_helper_charms(ops_test: OpsTest, copy_libraries_into_tester_charm):
    build_manifests_charm_path = await ops_test.build_charm("./tests/integration/manifests-tester")
    await ops_test.model.deploy(
        entity_url=build_manifests_charm_path,
        application_name=MANIFEST_CHARM_NAME1,
        trust=True,
    )
    await ops_test.model.deploy(
        entity_url=build_manifests_charm_path,
        application_name=MANIFEST_CHARM_NAME2,
        trust=True,
        config={"manifests_folder": "src/manifests2", "service_account_name": "config-secret-2"},
    )

    await ops_test.model.relate(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME1}:secrets")
    await ops_test.model.relate(
        f"{CHARM_NAME}:service-accounts", f"{MANIFEST_CHARM_NAME1}:service-accounts"
    )
    await ops_test.model.relate(
        f"{CHARM_NAME}:pod-defaults", f"{MANIFEST_CHARM_NAME1}:pod-defaults"
    )
    await ops_test.model.relate(f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME1}:roles")
    await ops_test.model.relate(
        f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME1}:role-bindings"
    )

    await ops_test.model.relate(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME2}:secrets")
    await ops_test.model.relate(f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME2}:roles")
    await ops_test.model.relate(
        f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME2}:role-bindings"
    )

    await ops_test.model.wait_for_idle(
        apps=[
            CHARM_NAME,
            METACONTROLLER_OPERATOR.charm,
            MANIFEST_CHARM_NAME1,
            MANIFEST_CHARM_NAME2,
        ],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
    )
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_manifests_created_from_both_helpers(
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
async def test_remove_relation(ops_test: OpsTest):
    """Make sure that charm goes to active state after relation is removed"""
    await ops_test.juju(
        "remove-relation", f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME1}:secrets"
    )
    await ops_test.juju("remove-relation", f"{CHARM_NAME}:roles", f"{MANIFEST_CHARM_NAME1}:roles")
    await ops_test.juju(
        "remove-relation", f"{CHARM_NAME}:role-bindings", f"{MANIFEST_CHARM_NAME1}:role-bindings"
    )
    await ops_test.model.wait_for_idle(
        apps=[
            CHARM_NAME,
            METACONTROLLER_OPERATOR.charm,
            MANIFEST_CHARM_NAME1,
            MANIFEST_CHARM_NAME2,
        ],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
        idle_period=30,
    )


@pytest.mark.abort_on_fail
async def test_remove_one_helper_relation(
    ops_test: OpsTest, lightkube_client: lightkube.Client, namespace: str
):
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
