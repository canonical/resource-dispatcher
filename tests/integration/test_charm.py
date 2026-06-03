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
from charmed_kubeflow_chisme.testing import (
    assert_security_context,
    generate_container_securitycontext_map,
    get_pod_names,
)
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Secret, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding

from .charms_dependencies import METACONTROLLER_OPERATOR
from .helpers import RESOURCE_DISPATCHER_CHARM_NAME, deploy_k8s_resources

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

CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)

TESTER1_SECRET_NAMES = ["mlpipeline-minio-artifact", "seldon-rclone-secret"]
TESTER2_SECRET_NAMES = ["mlpipeline-minio-artifact2", "seldon-rclone-secret2"]
<<<<<<< HEAD
PODDEFAULTS_NAMES = ["access-minio", "mlflow-server-minio"]
=======
TESTER3_SECRET_NAMES = ["mlpipeline-minio-artifact3", "seldon-rclone-secret3"]
TESTER4_SECRET_NAMES = ["mlpipeline-minio-artifact4", "seldon-rclone-secret4"]

TESTER1_PODDEFAULTS_NAMES = ["access-minio", "mlflow-server-minio"]
TESTER3_PODDEFAULTS_NAMES = ["access-minio-3", "mlflow-server-minio-3"]

TESTER1_ROLE_NAMES = ["test1-role"]
TESTER2_ROLE_NAMES = ["test2-role"]
TESTER1_ROLEBINDING_NAMES = ["test1-rolebinding"]
TESTER2_ROLEBINDING_NAMES = ["test2-rolebinding"]

PROFILE_SCOPED_SECRET1 = MINIO_SECRET_NAME1
PROFILE_SCOPED_SECRET2 = MINIO_SECRET_NAME3
PROFILE_AGNOSTIC_SECRET1 = "mlpipeline-minio-artifact2"
PROFILE_AGNOSTIC_SECRET2 = "mlpipeline-minio-artifact4"
>>>>>>> 175a621 ([PRA-90] Add feature to filter out manifests that are scoped to a namespace (#159))

PodDefault = create_namespaced_resource("kubeflow.org", "v1alpha1", "PodDefault", "poddefaults")


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
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
def test_container_security_context(
    juju: jubilant.Juju,
    lightkube_client: lightkube.Client,
    container_name: str,
):
    """Test that the security context is correctly set for charms and their workloads.

    Verify that all pods' and containers' specs define the expected security contexts, with
    particular emphasis on user IDs and group IDs.
    """
    pod_name = get_pod_names(juju.model, RESOURCE_DISPATCHER_CHARM_NAME)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        juju.model,
    )


<<<<<<< HEAD
def test_build_and_deploy_helper_charms(juju: jubilant.Juju, manifest_tester_charm: Path):
=======
@pytest.mark.parametrize(
    "tester_charm_fixture,tester_charm_name_1,tester_charm_name_2,service_account_name_1,service_account_name_2",
    [
        (
            "manifest_tester_charm",
            MANIFEST_CHARM_NAME1,
            MANIFEST_CHARM_NAME2,
            "default-sa",
            "default-sa-2",
        ),
        (
            "manifest_tester_no_secret_charm",
            MANIFEST_CHARM_NO_SECRET_NAME1,
            MANIFEST_CHARM_NO_SECRET_NAME2,
            "config-secret-3",
            "config-secret-4",
        ),
    ],
)
def test_build_and_deploy_tester_charms(
    request,
    juju: jubilant.Juju,
    tester_charm_fixture: str,
    tester_charm_name_1: str,
    tester_charm_name_2: str,
    service_account_name_1: str,
    service_account_name_2: str,
):
    """Deploy tester charms.

    The parametrized test will first deploy the manifest-tester charm with the new library that supports secrets,
    and then deploy the manifest-tester-no-secret charm with the old library that does not support secrets.
    This allows us to test both types of charms in the subsequent tests.
    """
    tester_charm = request.getfixturevalue(tester_charm_fixture)
>>>>>>> 175a621 ([PRA-90] Add feature to filter out manifests that are scoped to a namespace (#159))
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

    juju.integrate(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME2}:secrets")

    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert status.apps[CHARM_NAME].units[f"{CHARM_NAME}/0"].workload_status.current == "active"


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


<<<<<<< HEAD
def test_remove_relation(juju: jubilant.Juju):
=======
@pytest.mark.parametrize(
    "profile_scoped_secret,profile_agnostic_secret",
    [
        (PROFILE_SCOPED_SECRET1, PROFILE_AGNOSTIC_SECRET1),
        (PROFILE_SCOPED_SECRET2, PROFILE_AGNOSTIC_SECRET2),
    ],
)
def test_manifest_namespace_scoping(
    lightkube_client: lightkube.Client,
    profile_namespaces: tuple[str, str],
    profile_scoped_secret: str,
    profile_agnostic_secret: str,
) -> None:
    """Validate pinned manifests apply to one namespace while unpinned manifests apply to all profiles."""
    primary_namespace, secondary_namespace = profile_namespaces

    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespaces)

    # pinned manifests are applied only to the namespace explicitly set in metadata.namespace
    pinned_secret = lightkube_client.get(
        Secret, profile_scoped_secret, namespace=primary_namespace
    )
    assert pinned_secret != None

    # logger.error("sleeping...")
    # time.sleep(10 * 60)

    with pytest.raises(ApiError) as e_info:
        lightkube_client.get(Secret, profile_scoped_secret, namespace=secondary_namespace)
    assert "not found" in str(e_info)

    # manifests without metadata.namespace are applied to all profile namespaces
    unpinned_secret_primary = lightkube_client.get(
        Secret, profile_agnostic_secret, namespace=primary_namespace
    )
    unpinned_secret_secondary = lightkube_client.get(
        Secret, profile_agnostic_secret, namespace=secondary_namespace
    )
    assert unpinned_secret_primary != None
    assert unpinned_secret_secondary != None


@pytest.mark.parametrize(
    (
        "tester_charm_name,"
        "expected_deleted_secrets,"
        "expected_deleted_roles,"
        "expected_deleted_rolebindings,"
        "expected_existing_secrets,"
        "expected_existing_roles,"
        "expected_existing_rolebindings,"
    ),
    [
        (
            MANIFEST_CHARM_NAME2,
            TESTER2_SECRET_NAMES,
            TESTER2_ROLE_NAMES,
            TESTER2_ROLEBINDING_NAMES,
            TESTER1_SECRET_NAMES,
            TESTER1_ROLE_NAMES,
            TESTER1_ROLEBINDING_NAMES,
        ),
        (
            MANIFEST_CHARM_NO_SECRET_NAME2,
            TESTER4_SECRET_NAMES,
            [],
            [],
            TESTER3_SECRET_NAMES,
            [],
            [],
        ),
    ],
)
def test_remove_one_tester_relation(
    juju: jubilant.Juju,
    lightkube_client: lightkube.Client,
    namespace: str,
    tester_charm_name,
    expected_deleted_secrets,
    expected_deleted_roles,
    expected_deleted_rolebindings,
    expected_existing_secrets,
    expected_existing_roles,
    expected_existing_rolebindings,
):
>>>>>>> 175a621 ([PRA-90] Add feature to filter out manifests that are scoped to a namespace (#159))
    """Make sure that charm goes to active state after relation is removed"""
    juju.remove_relation(f"{CHARM_NAME}:secrets", f"{MANIFEST_CHARM_NAME1}:secrets")
    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )


def test_remove_one_helper_relation(lightkube_client: lightkube.Client, namespace: str):
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    for name in TESTER2_SECRET_NAMES:
        secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert secret != None
    for name in TESTER1_SECRET_NAMES:
        with pytest.raises(ApiError) as e_info:
            secret = lightkube_client.get(Secret, name, namespace=namespace)
        assert "not found" in str(e_info)
