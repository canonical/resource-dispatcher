import json
from contextlib import nullcontext as does_not_raise
from dataclasses import asdict
from typing import List

import pytest
import yaml
from ops.charm import CharmBase
from ops.testing import Harness

from lib.charms.harness_extensions.v0.capture_events import capture
from lib.charms.resource_dispatcher.v0.resource_dispatcher import (
    KUBERNETES_MANIFESTS_FIELD,
    KubernetesManifest,
    KubernetesManifestsProvider,
    KubernetesManifestsRequirer,
    KubernetesManifestsUpdatedEvent,
)

RELATION_NAME = "service-accounts"

DUMMY_PROVIDER_METADATA = """
name: dummy-provider
provides:
  service-accounts:
    interface: service-accounts
"""
DUMMY_REQUIRER_METADATA = """
name: dummy-requirer
requires:
  service-accounts:
    interface: service-accounts
"""

MANIFEST_CONTENT1 = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dummy-sa-1
secrets:
- name: dummy
"""

MANIFEST_CONTENT2 = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: other-dummy-sa-1
secrets:
- name: other-dummy
"""

MANIFEST_CONTENT3 = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dummy-sa-2
secrets:
- name: dummy
"""

MANIFEST_CONTENT4 = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: other-dummy-sa-2
secrets:
- name: other-dummy
"""

RELATION1_MANIFESTS = [
    KubernetesManifest(MANIFEST_CONTENT1),
    KubernetesManifest(MANIFEST_CONTENT2),
]

RELATION2_MANIFESTS = [
    KubernetesManifest(MANIFEST_CONTENT3),
    KubernetesManifest(MANIFEST_CONTENT4),
]

INVALID_YAML = """
apiVersion: v1
kind: Secret
metadata:
  name: mlpipeline-minio-artifact
  labels:
    user.kubeflow.org/enabled: "true
stringData:
  AWS_ACCESS_KEY_ID: access_key
  AWS_SECRET_ACCESS_KEY: secret_access_key
"""


class DummyProviderCharm(CharmBase):
    """Mock charm that is a manifests Provider."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=RELATION_NAME
        )


class DummyRequirerCharm(CharmBase):
    """Mock charm that is a manifests Requirer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.manifests_requirer = KubernetesManifestsRequirer(
            charm=self,
            relation_name=RELATION_NAME,
            manifests_items=RELATION1_MANIFESTS,
        )


class TestKubernetesManifest:
    @pytest.mark.parametrize(
        "manifest, context_raised",
        [
            (yaml.dump(MANIFEST_CONTENT1), does_not_raise()),
            (yaml.dump(MANIFEST_CONTENT2), does_not_raise()),
            (INVALID_YAML, pytest.raises(yaml.YAMLError)),
        ],
    )
    def test_yaml_validation(self, manifest, context_raised):
        with context_raised:
            KubernetesManifest(manifest)


class TestManifestsProvder:
    def test_get_manifests(self):
        """Tests that get_manifests correctly returns information from the relation."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        databag = {
            KUBERNETES_MANIFESTS_FIELD: json.dumps(
                [manifest_item.get_manifest() for manifest_item in RELATION1_MANIFESTS]
            )
        }

        other_databag = {
            KUBERNETES_MANIFESTS_FIELD: json.dumps(
                [manifest_item.get_manifest() for manifest_item in RELATION2_MANIFESTS]
            )
        }

        # Add data to relation
        harness.add_relation(RELATION_NAME, other_app, app_data=databag)

        # Add to a second relation so we simulate having two relations of data
        harness.add_relation(RELATION_NAME, other_app, app_data=other_databag)

        expected_manifests = [
            yaml.safe_load(content)
            for content in [
                MANIFEST_CONTENT1,
                MANIFEST_CONTENT2,
                MANIFEST_CONTENT3,
                MANIFEST_CONTENT4,
            ]
        ]

        harness.begin()

        # Act
        # Get manifests from relation data
        actual_manifests = harness.charm.manifests_provider.get_manifests()

        # Assert
        assert actual_manifests == expected_manifests

    def test_get_manifests_empty_relation(self):
        """Tests that get_manifests correctly handles empty relations."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Add empty relation
        harness.add_relation(RELATION_NAME, other_app)

        expected_manifests = []

        harness.begin()

        # Act
        # Get manifests from relation data
        actual_manifests = harness.charm.manifests_provider.get_manifests()

        # Assert
        assert actual_manifests == expected_manifests

    def test_emit_updated_event(self):
        """Tests that the Provider library emits KubernetesManifestsUpdatedEvent."""
        # Arrange
        # Set up charm
        other_app = "other"
        harness = Harness(DummyProviderCharm, meta=DUMMY_PROVIDER_METADATA)

        # Create data
        manifest = KubernetesManifest(MANIFEST_CONTENT1)
        databag = {KUBERNETES_MANIFESTS_FIELD: json.dumps([asdict(manifest)])}

        harness.begin()

        # Act/Assert
        relation_id = harness.add_relation(RELATION_NAME, other_app)

        # Add data to relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubernetesManifestsUpdatedEvent):
            harness.update_relation_data(
                relation_id=relation_id, app_or_unit=other_app, key_values=databag
            )

        # Remove relation
        # Assert that we emit a data_updated event
        with capture(harness.charm, KubernetesManifestsUpdatedEvent):
            harness.remove_relation(relation_id=relation_id)


class TestManifestsRequirer:
    def test_send_manifests_on_leader_elected(self):
        """Test that the Requirer correctly handles the leader elected event."""
        # Arrange
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        other_app = "provider"
        this_app = harness.model.app

        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        harness.begin()
        # Confirm that we have no data in the relation yet
        raw_relation_data = harness.get_relation_data(
            relation_id=relation_id, app_or_unit=this_app
        )
        assert raw_relation_data == {}

        # Act
        harness.set_leader(True)

        # Assert
        actual_manifests = get_manifests_from_relation(harness, relation_id, harness.model.app)

        assert actual_manifests == [item.get_manifest() for item in RELATION1_MANIFESTS]

    def test_send_manifests_on_relation_created(self):
        """Test that the Requirer correctly handles the relation created event."""
        # Arrange
        other_app = "provider"
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        harness.set_leader(True)
        harness.begin()

        # Act
        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        # Assert
        actual_manifests = get_manifests_from_relation(harness, relation_id, harness.model.app)

        assert actual_manifests == [item.get_manifest() for item in RELATION1_MANIFESTS]

    def test_send_manifests_without_leadership(self):
        """Tests whether library incorrectly sends manifests data when unit is not leader."""
        # Arrange
        other_app = "provider"
        harness = Harness(DummyRequirerCharm, meta=DUMMY_REQUIRER_METADATA)
        harness.set_leader(False)
        harness.begin()

        # Act
        # This should do nothing because we are not the leader
        relation_id = harness.add_relation(relation_name=RELATION_NAME, remote_app=other_app)

        # Assert
        # There should be no data in the relation, because we should skip writing data when not
        # leader
        raw_relation_data = harness.get_relation_data(
            relation_id=relation_id, app_or_unit=harness.model.app
        )
        assert raw_relation_data == {}


def get_manifests_from_relation(harness, relation_id, this_app) -> List[KubernetesManifest]:
    """Returns the list of KubernetesManifests from a service-account relation on a harness."""
    raw_relation_data = harness.get_relation_data(relation_id=relation_id, app_or_unit=this_app)
    actual_manifests = json.loads(raw_relation_data[KUBERNETES_MANIFESTS_FIELD])
    return actual_manifests
