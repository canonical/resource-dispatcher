# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charms.resource_dispatcher.v0.kubernetes_manifests import (
    KUBERNETES_MANIFESTS_FIELD,
    KubernetesManifest,
)
from lightkube import ApiError
from ops.model import BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Service
from ops.testing import Harness

from charm import ResourceDispatcherOperator

EXPECTED_SERVICE = {
    "resource-dispatcher": Service(
        "resource-dispatcher",
        raw={
            "summary": "Entrypoint of resource-dispatcher-operator image",
            "startup": "enabled",
            "override": "replace",
            "command": "python3 main.py --port 80 --label user.kubeflow.org/enabled --folder /app/resources",
        },
    )
}

SECRET1 = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {"name": "mlpipeline-minio-artifact"},
    "stringData": {
        "AWS_ACCESS_KEY_ID": "minio",
        "AWS_SECRET_ACCESS_KEY": "NGJURYFBOOIP19XHNFHOMD02K9NG03",
    },
}
SECRET2 = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {"name": "mlpipeline-minio-artifact2"},
    "stringData": {
        "AWS_ACCESS_KEY_ID": "minio",
        "AWS_SECRET_ACCESS_KEY": "NGJURYFBOOIP19XHNFHOMD02K9NG03",
    },
}

SERVICEACCOUNT = {
    "apiVersion": "v1",
    "kind": "ServiceAccount",
    "metadata": {"name": "sa"},
    "secrets": [{"name": "s3creds"}],
}

VALID_MANIFESTS = [{"metadata": {"name": "a"}}, {"metadata": {"name": "b"}}]
INVALID_MANIFESTS = VALID_MANIFESTS + [{"metadata": {"name": "a"}}]


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code
        self.name = ""

    def json(self):
        reason = ""
        if self.code == 409:
            reason = "AlreadyExists"
        return {
            "apiVersion": 1,
            "code": self.code,
            "message": "broken",
            "reason": reason,
        }


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code=400):
        super().__init__(response=_FakeResponse(code))


class _FakeChangeError(ChangeError):
    """Used to simulate a ChangeError during testing."""

    def __init__(self, err, change):
        super().__init__(err, change)


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""

    harness = Harness(ResourceDispatcherOperator)

    # setup container networking simulation
    harness.set_can_connect("resource-dispatcher", True)

    return harness


def add_secret_relation_to_harness(harness: Harness) -> Harness:
    """Helper function to handle secret relation"""
    secret_manifests = [
        KubernetesManifest(yaml.dump(SECRET1)),
        KubernetesManifest(yaml.dump(SECRET2)),
    ]
    databag = {
        KUBERNETES_MANIFESTS_FIELD: json.dumps([item.manifest for item in secret_manifests])
    }
    secret_relation_id = harness.add_relation("secrets", "mlflow-server")
    harness.add_relation_unit(secret_relation_id, "mlflow-server/0")
    harness.update_relation_data(secret_relation_id, "mlflow-server", databag)
    return harness


class TestCharm:
    """Test class for TrainingOperatorCharm."""

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    def test_check_leader_failure(self, _: MagicMock, harness: Harness):
        harness.begin()
        with pytest.raises(ErrorWithStatus) as e_info:
            harness.charm._check_leader()
        assert "Waiting for leadership" in str(e_info)
        assert e_info.value.status_type(WaitingStatus)

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    def test_check_leader_success(self, _: MagicMock, harness: Harness):
        harness.set_leader(True)
        harness.begin()
        try:
            harness.charm._check_leader()
        except ErrorWithStatus:
            pytest.fail("check_leader_success should not raise ErrorWithStatus")

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator._deploy_k8s_resources")
    def test_on_install_success(self, deploy_k8s_resources: MagicMock, harness: Harness):
        harness.begin()
        harness.charm._on_install(None)
        deploy_k8s_resources.assert_called()

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.container")
    def test_update_layer_failure_container_problem(
        self,
        container: MagicMock,
        harness: Harness,
    ):
        change = MagicMock()
        change.tasks = []
        container.replan.side_effect = _FakeChangeError("Fake problem during layer update", change)
        harness.begin()
        with pytest.raises(GenericCharmRuntimeError) as exc_info:
            harness.charm._update_layer()

        assert "Fake problem during layer update" in str(exc_info)

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    def test_update_layer_success(
        self,
        harness: Harness,
    ):
        harness.begin()
        harness.charm._update_layer()
        assert harness.charm.container.get_plan().services == EXPECTED_SERVICE

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    def test_deploy_k8s_resources_failure(self, k8s_handler: MagicMock, harness: Harness):
        k8s_handler.apply.side_effect = _FakeApiError()
        harness.begin()
        with pytest.raises(GenericCharmRuntimeError) as exc_info:
            harness.charm._deploy_k8s_resources()

        assert "K8S resources creation failed" in str(exc_info)

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    def test_deploy_k8s_resources_success(self, k8s_handler: MagicMock, harness: Harness):
        harness.begin()
        harness.charm._deploy_k8s_resources()
        k8s_handler.apply.assert_called()
        assert harness.charm.model.unit.status == WaitingStatus(
            "K8s resources created. Waiting for charm to be active"
        )

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    @patch("charm.delete_many")
    def test_on_remove_failure(self, delete_many: MagicMock, _: MagicMock, harness: Harness):
        delete_many.side_effect = _FakeApiError()
        harness.begin()
        with pytest.raises(ApiError):
            harness.charm._on_remove(None)

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.k8s_resource_handler")
    @patch("charm.delete_many")
    def test_on_remove_success(self, delete_many: MagicMock, _: MagicMock, harness: Harness):
        harness.begin()
        harness.charm._on_remove(None)
        assert harness.charm.model.unit.status == MaintenanceStatus("K8S resources removed")

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    def test_get_manifests_success(self, harness: Harness):
        harness = add_secret_relation_to_harness(harness)
        harness.set_leader(True)
        harness.begin()
        secrets = harness.charm._secrets_manifests_provider.get_manifests()
        assert secrets == [SECRET1, SECRET2]

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    def test_manifests_valid_true(self, harness: Harness):
        harness.begin()
        response = harness.charm._manifests_valid(VALID_MANIFESTS)
        assert response == True

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    def test_manifests_valid_false(self, harness: Harness):
        harness.begin()
        response = harness.charm._manifests_valid(INVALID_MANIFESTS)
        assert response == False

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.secrets_manifests_provider")
    @patch("charm.ResourceDispatcherOperator._sync_manifests")
    def test_update_manifests_success(
        self, sync_manifests: MagicMock, secrets_manifests_provider: MagicMock, harness: Harness
    ):
        harness.begin()
        secrets_manifests_provider.get_manifests.return_value = ""
        harness.charm._update_manifests(secrets_manifests_provider, "")
        sync_manifests.assert_called_with("", "")

    @patch(
        "charm.KubernetesServicePatch",
        lambda x, y, service_name, service_type, refresh_event: None,
    )
    @patch("charm.ResourceDispatcherOperator.secrets_manifests_provider")
    @patch("charm.ResourceDispatcherOperator._sync_manifests")
    @patch("charm.ResourceDispatcherOperator._manifests_valid")
    def test_update_manifests_invalid_manifests(
        self,
        manifests_valid: MagicMock,
        _: MagicMock,
        secrets_manifests_provider: MagicMock,
        harness: Harness,
    ):
        manifests_valid.return_value = False
        secrets_manifests_provider.get_manifests.return_value = ""
        harness.begin()
        with pytest.raises(ErrorWithStatus) as e_info:
            harness.charm._update_manifests(secrets_manifests_provider, "")
        assert "Failed to process invalid manifest. See debug logs" in str(e_info)
        assert e_info.value.status_type(BlockedStatus)
