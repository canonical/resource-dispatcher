#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

"""Mock relation provider charms."""

import glob
import json
import logging
from pathlib import Path
from typing import List

import yaml
from charms.resource_dispatcher.v0.kubernetes_manifests import (
    KubernetesManifest,
    KubernetesManifestRequirerWrapper,
    KubernetesManifestsRequirer,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

logger = logging.getLogger(__name__)

PODDEFAULTS_RELATION_NAME = "pod-defaults"
SECRETS_RELATION_NAME = "secrets"
SERVICEACCOUNTS_RELATION_NAME = "service-accounts"

SERVICE_ACCOUNT_YAML = """
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {name}
secrets:
- name: s3creds

"""


class ManifestsTesterCharm(CharmBase):
    """Charm for sending manifests to ResourceDispatcher relations."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "manifests-tester"
        self._manifests_folder = self.model.config["manifests_folder"]

        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._update_service_accounts_relation_data)
        self.framework.observe(self.on.leader_elected, self._update_service_accounts_relation_data)
        self.framework.observe(
            self.on[SERVICEACCOUNTS_RELATION_NAME].relation_created,
            self._update_service_accounts_relation_data,
        )

        self._poddefaults_manifests_requirer = KubernetesManifestsRequirer(
            charm=self,
            relation_name=PODDEFAULTS_RELATION_NAME,
            manifests_items=self._poddefaults_manifests,
        )

        self._secrets_manifests_requirer = KubernetesManifestsRequirer(
            charm=self,
            relation_name=SECRETS_RELATION_NAME,
            manifests_items=self._secrets_manifests,
        )

        self.service_accounts_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=SERVICEACCOUNTS_RELATION_NAME
        )

    @property
    def _poddefaults_manifests(self):
        return self._get_manifests(PODDEFAULTS_RELATION_NAME, self._manifests_folder)

    @property
    def _secrets_manifests(self):
        return self._get_manifests(SECRETS_RELATION_NAME, self._manifests_folder)

    def _get_manifests(self, resource_type, folder) -> List[KubernetesManifest]:
        manifests = []
        manifest_files = glob.glob(f"{folder}/{resource_type}/*.yaml")
        for file in manifest_files:
            file_content = Path(file).read_text()
            manifests.append(KubernetesManifest(file_content))
        return manifests

    def _on_start(self, _):
        """Set active on start."""
        self._send_manifest_from_config()
        self.model.unit.status = ActiveStatus()

    def _update_service_accounts_relation_data(self, _):
        self._send_manifest_from_config()

    def _send_manifest_from_config(self):
        service_account_name = self.model.config["service_account_name"]
        config_manifest = SERVICE_ACCOUNT_YAML.format(name=service_account_name)
        config_manifest_items = [KubernetesManifest(config_manifest)]
        self.service_accounts_requirer_wrapper.send_data(config_manifest_items)


if __name__ == "__main__":  # pragma: nocover
    main(ManifestsTesterCharm)
