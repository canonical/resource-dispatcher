# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
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
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import ConfigMap, Secret, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding

from .charms_dependencies import METACONTROLLER_OPERATOR
from .helpers import RESOURCE_DISPATCHER_CHARM_NAME, assert_resource_status, deploy_k8s_resources

logger = logging.getLogger(__name__)

MANIFEST_CHARM_NAME1 = "manifests-tester1"
MANIFEST_CHARM_NAME2 = "manifests-tester2"
MANIFEST_CHARM_NO_SECRET_NAME1 = "manifests-tester-no-secret1"
MANIFEST_CHARM_NO_SECRET_NAME2 = "manifests-tester-no-secret2"

MANIFESTS_TESTER_CONFIG = yaml.safe_load(
    Path("./tests/integration/manifests-tester/config.yaml").read_text()
)
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
NAMESPACE_FILE = "./tests/integration/resources/namespace.yaml"
PODDEFAULTS_CRD_TEMPLATE = "./tests/integration/resources/crds/poddefaults.yaml"
TESTING_LABELS = ["user.kubeflow.org/enabled"]  # Might be more than one in the future

CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)

MINIO_SECRET_NAME1 = "mlpipeline-minio-artifact"
MINIO_SECRET_NAME3 = "mlpipeline-minio-artifact3"

SERVICE_ACCOUNT_NAME1 = MANIFESTS_TESTER_CONFIG["options"]["service_account_name"]["default"]
SERVICE_ACCOUNT_NAME3 = "config-secret-3"

SERVICE_ACCOUNT_NAME1_NEW = SERVICE_ACCOUNT_NAME1 + "-new"
SERVICE_ACCOUNT_NAME3_NEW = SERVICE_ACCOUNT_NAME3 + "-new"


TESTER1_SECRET_NAMES = ["mlpipeline-minio-artifact", "seldon-rclone-secret"]
TESTER2_SECRET_NAMES = ["mlpipeline-minio-artifact2", "seldon-rclone-secret2"]
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

TESTER1_CONFIGMAPS_NAMES = ["test1-configmap"]
TESTER2_CONFIGMAPS_NAMES = ["test2-configmap"]

CONFLICT_TEST_SECRET_NAME = "conflict-test-secret"
# These values match the stringData in the two conflict-secret fixture files.
CONFLICT_GLOBAL_ACCESS_KEY = base64.b64encode(b"global-key").decode("utf-8")
CONFLICT_PINNED_ACCESS_KEY = base64.b64encode(b"pinned-key").decode("utf-8")


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


def test_deploy_resource_dispatcher_charm(juju: jubilant.Juju, resource_dispatcher_charm: Path):
    """Deploy resource-dispatcher charm from 2.0/stable channel, which uses kubernetes_manifest lib 0.1."""
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}
    juju.deploy(
        charm=resource_dispatcher_charm,
        app=RESOURCE_DISPATCHER_CHARM_NAME,
        resources=resources,
        trust=True,
    )
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert (
        status.apps[RESOURCE_DISPATCHER_CHARM_NAME]
        .units[f"{RESOURCE_DISPATCHER_CHARM_NAME}/0"]
        .workload_status.current
        == "active"
    )


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
    juju.deploy(
        charm=tester_charm,
        app=tester_charm_name_1,
        trust=True,
        config={
            "manifests_folder": "src/manifests1",
            "service_account_name": service_account_name_1,
        },
    )
    juju.deploy(
        charm=tester_charm,
        app=tester_charm_name_2,
        trust=True,
        config={
            "manifests_folder": "src/manifests2",
            "service_account_name": service_account_name_2,
        },
    )
    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert (
        status.apps[RESOURCE_DISPATCHER_CHARM_NAME]
        .units[f"{RESOURCE_DISPATCHER_CHARM_NAME}/0"]
        .workload_status.current
        == "active"
    )


@pytest.mark.parametrize(
    "tester1_charm_name,tester2_charm_name",
    [
        (MANIFEST_CHARM_NAME1, MANIFEST_CHARM_NAME2),
        (MANIFEST_CHARM_NO_SECRET_NAME1, MANIFEST_CHARM_NO_SECRET_NAME2),
    ],
)
def test_integrate_tester_with_resource_dispatcher(
    juju: jubilant.Juju, tester1_charm_name: str, tester2_charm_name: str
):
    """Integrate manifest-tester charm with resource-dispatcher."""
    juju.integrate(f"{RESOURCE_DISPATCHER_CHARM_NAME}:secrets", f"{tester1_charm_name}:secrets")
    juju.integrate(
        f"{RESOURCE_DISPATCHER_CHARM_NAME}:service-accounts",
        f"{tester1_charm_name}:service-accounts",
    )
    juju.integrate(f"{RESOURCE_DISPATCHER_CHARM_NAME}:secrets", f"{tester2_charm_name}:secrets")
    juju.integrate(
        f"{RESOURCE_DISPATCHER_CHARM_NAME}:pod-defaults", f"{tester1_charm_name}:pod-defaults"
    )

    # roles relation support is only added recently -- they don't exist on old charms
    if tester1_charm_name != MANIFEST_CHARM_NO_SECRET_NAME1:
        juju.integrate(f"{RESOURCE_DISPATCHER_CHARM_NAME}:roles", f"{tester1_charm_name}:roles")
        juju.integrate(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:role-bindings",
            f"{tester1_charm_name}:role-bindings",
        )
        juju.integrate(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:config-maps", f"{tester1_charm_name}:config-maps"
        )

    # role-bindings relation support is only added recently -- they don't exist on old charms
    if tester2_charm_name != MANIFEST_CHARM_NO_SECRET_NAME2:
        juju.integrate(f"{RESOURCE_DISPATCHER_CHARM_NAME}:roles", f"{tester2_charm_name}:roles")
        juju.integrate(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:role-bindings",
            f"{tester2_charm_name}:role-bindings",
        )
        juju.integrate(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:config-maps", f"{tester2_charm_name}:config-maps"
        )

    status = juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=5
    )
    assert (
        status.apps[RESOURCE_DISPATCHER_CHARM_NAME]
        .units[f"{RESOURCE_DISPATCHER_CHARM_NAME}/0"]
        .workload_status.current
        == "active"
    )


@pytest.mark.parametrize(
    (
        "expected_minio_secret_name,"
        "expected_service_account_name,"
        "expected_tester_secrets_1,"
        "expected_tester_secrets_2,"
        "expected_pod_defaults,"
        "expected_tester_roles_1,"
        "expected_tester_roles_2,"
        "expected_tester_rolebindings_1,"
        "expected_tester_rolebindings_2,"
        "expected_tester_configmaps_1,"
        "expected_tester_configmaps_2"
    ),
    [
        (
            MINIO_SECRET_NAME1,
            SERVICE_ACCOUNT_NAME1,
            TESTER1_SECRET_NAMES,
            TESTER2_SECRET_NAMES,
            TESTER1_PODDEFAULTS_NAMES,
            TESTER1_ROLE_NAMES,
            TESTER2_ROLE_NAMES,
            TESTER1_ROLEBINDING_NAMES,
            TESTER2_ROLEBINDING_NAMES,
            TESTER1_CONFIGMAPS_NAMES,
            TESTER2_CONFIGMAPS_NAMES,
        ),
        (
            MINIO_SECRET_NAME3,
            SERVICE_ACCOUNT_NAME3,
            TESTER3_SECRET_NAMES,
            TESTER4_SECRET_NAMES,
            TESTER3_PODDEFAULTS_NAMES,
            [],
            [],
            [],
            [],
            [],
            [],
        ),
    ],
)
def test_manifests_created_from_both_tester_charms(
    lightkube_client: lightkube.Client,
    namespace: str,
    expected_minio_secret_name: str,
    expected_service_account_name: str,
    expected_tester_secrets_1,
    expected_tester_secrets_2,
    expected_pod_defaults,
    expected_tester_roles_1,
    expected_tester_roles_2,
    expected_tester_rolebindings_1,
    expected_tester_rolebindings_2,
    expected_tester_configmaps_1,
    expected_tester_configmaps_2,
):
    assert_resource_status(
        lightkube_client, ServiceAccount, expected_service_account_name, namespace
    )
    # Testing one secret for content
    secret = assert_resource_status(
        lightkube_client, Secret, expected_minio_secret_name, namespace
    )
    assert secret.data == {
        "AWS_ACCESS_KEY_ID": base64.b64encode("access_key".encode("utf-8")).decode("utf-8"),
        "AWS_SECRET_ACCESS_KEY": base64.b64encode("secret_access_key".encode("utf-8")).decode(
            "utf-8"
        ),
    }
    for name in expected_tester_secrets_1 + expected_tester_secrets_2:
        assert_resource_status(lightkube_client, Secret, name, namespace)
    for name in expected_pod_defaults:
        assert_resource_status(lightkube_client, PodDefault, name, namespace)
    for name in expected_tester_roles_1 + expected_tester_roles_2:
        assert_resource_status(lightkube_client, Role, name, namespace)
    for name in expected_tester_rolebindings_1 + expected_tester_rolebindings_2:
        assert_resource_status(lightkube_client, RoleBinding, name, namespace)
    for name in expected_tester_configmaps_1 + expected_tester_configmaps_2:
        assert_resource_status(lightkube_client, ConfigMap, name, namespace)


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

    # pinned manifests are applied only to the namespace explicitly set in metadata.namespace
    assert_resource_status(lightkube_client, Secret, profile_scoped_secret, primary_namespace)
    assert_resource_status(
        lightkube_client, Secret, profile_scoped_secret, secondary_namespace, exists=False
    )

    # manifests without metadata.namespace are applied to all profile namespaces
    assert_resource_status(lightkube_client, Secret, profile_agnostic_secret, primary_namespace)
    assert_resource_status(lightkube_client, Secret, profile_agnostic_secret, secondary_namespace)


def test_conflict_resolution_pinned_overrides_global(
    lightkube_client: lightkube.Client,
    profile_namespaces: tuple[str, str],
) -> None:
    """When a pinned and a global manifest share a name, the pinned version wins in its namespace.

    The manifests-tester1 charm sends both:
    * conflict-secret-global.yaml    – global (no namespace), AWS_ACCESS_KEY_ID: global-key
    * conflict-secret-pinned.yaml    – pinned to the primary namespace, AWS_ACCESS_KEY_ID: pinned-key

    The dispatcher image must resolve the conflict so that:
    * The primary namespace receives the pinned version.
    * All other labeled namespaces receive the global version.
    """
    primary_namespace, secondary_namespace = profile_namespaces

    primary_secret = assert_resource_status(
        lightkube_client, Secret, CONFLICT_TEST_SECRET_NAME, primary_namespace
    )
    assert primary_secret.data["AWS_ACCESS_KEY_ID"] == CONFLICT_PINNED_ACCESS_KEY, (
        f"Primary namespace '{primary_namespace}' should have the pinned version of "
        f"'{CONFLICT_TEST_SECRET_NAME}'"
    )

    secondary_secret = assert_resource_status(
        lightkube_client, Secret, CONFLICT_TEST_SECRET_NAME, secondary_namespace
    )
    assert secondary_secret.data["AWS_ACCESS_KEY_ID"] == CONFLICT_GLOBAL_ACCESS_KEY, (
        f"Secondary namespace '{secondary_namespace}' should have the global version of "
        f"'{CONFLICT_TEST_SECRET_NAME}'"
    )


@pytest.mark.parametrize(
    (
        "tester_charm_name,"
        "expected_deleted_secrets,"
        "expected_deleted_roles,"
        "expected_deleted_rolebindings,"
        "expected_deleted_configmaps,"
        "expected_existing_secrets,"
        "expected_existing_roles,"
        "expected_existing_rolebindings,"
        "expected_existing_configmaps"
    ),
    [
        (
            MANIFEST_CHARM_NAME2,
            TESTER2_SECRET_NAMES,
            TESTER2_ROLE_NAMES,
            TESTER2_ROLEBINDING_NAMES,
            TESTER2_CONFIGMAPS_NAMES,
            TESTER1_SECRET_NAMES,
            TESTER1_ROLE_NAMES,
            TESTER1_ROLEBINDING_NAMES,
            TESTER1_CONFIGMAPS_NAMES,
        ),
        (
            MANIFEST_CHARM_NO_SECRET_NAME2,
            TESTER4_SECRET_NAMES,
            [],
            [],
            [],
            TESTER3_SECRET_NAMES,
            [],
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
    expected_deleted_configmaps,
    expected_existing_secrets,
    expected_existing_roles,
    expected_existing_rolebindings,
    expected_existing_configmaps,
):
    """Make sure that charm goes to active state after relation is removed"""
    juju.remove_relation(
        f"{RESOURCE_DISPATCHER_CHARM_NAME}:secrets", f"{tester_charm_name}:secrets"
    )
    if tester_charm_name != MANIFEST_CHARM_NO_SECRET_NAME2:
        juju.remove_relation(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:roles", f"{tester_charm_name}:roles"
        )
        juju.remove_relation(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:role-bindings", f"{tester_charm_name}:role-bindings"
        )
        juju.remove_relation(
            f"{RESOURCE_DISPATCHER_CHARM_NAME}:config-maps", f"{tester_charm_name}:config-maps"
        )

    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=10
    )
    for name in expected_deleted_secrets:
        assert_resource_status(lightkube_client, Secret, name, namespace, exists=False)
    for name in expected_deleted_roles:
        assert_resource_status(lightkube_client, Role, name, namespace, exists=False)
    for name in expected_deleted_rolebindings:
        assert_resource_status(lightkube_client, RoleBinding, name, namespace, exists=False)
    for name in expected_deleted_configmaps:
        assert_resource_status(lightkube_client, ConfigMap, name, namespace, exists=False)

    for name in expected_existing_secrets:
        assert_resource_status(lightkube_client, Secret, name, namespace)
    for name in expected_existing_roles:
        assert_resource_status(lightkube_client, Role, name, namespace)
    for name in expected_existing_rolebindings:
        assert_resource_status(lightkube_client, RoleBinding, name, namespace)
    for name in expected_existing_configmaps:
        assert_resource_status(lightkube_client, ConfigMap, name, namespace)


@pytest.mark.parametrize(
    "tester_charm_name,old_service_account,new_service_account",
    [
        (MANIFEST_CHARM_NAME1, SERVICE_ACCOUNT_NAME1, SERVICE_ACCOUNT_NAME1_NEW),
        (MANIFEST_CHARM_NO_SECRET_NAME1, SERVICE_ACCOUNT_NAME3, SERVICE_ACCOUNT_NAME3_NEW),
    ],
)
def test_change_in_manifest_reflected(
    juju: jubilant.Juju,
    lightkube_client: lightkube.Client,
    namespace: str,
    tester_charm_name,
    old_service_account,
    new_service_account,
):
    """Change the config in manifest-tester, such that the manifests are changed, and verify they are reflected in the K8s resources."""
    juju.config(tester_charm_name, {"service_account_name": new_service_account})
    juju.wait(
        lambda status: jubilant.all_active(status) and jubilant.all_agents_idle(status), delay=10
    )

    assert_resource_status(
        lightkube_client, ServiceAccount, old_service_account, namespace, exists=False
    )
    assert_resource_status(lightkube_client, ServiceAccount, new_service_account, namespace)
