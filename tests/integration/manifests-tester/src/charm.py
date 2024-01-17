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
from charms.resource_dispatcher.v0.resource_dispatcher import (
    KubernetesManifest,
    KubernetesManifestsRequirer,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

logger = logging.getLogger(__name__)

PODDEFAULTS_RELATION_NAME = "pod-defaults"
SECRETS_RELATION_NAME = "secrets"
SERVICEACCOUNTS_RELATION_NAME = "service-accounts"


class ManifestsTesterCharm(CharmBase):
    """Charm for sending manifests to ResourceDispatcher relations."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "manifests-tester"
        self._manifests_folder = self.model.config["manifests_folder"]

        self.framework.observe(self.on.start, self._on_start)

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
        self._service_accounts_manifests_requirer = KubernetesManifestsRequirer(
            charm=self,
            relation_name=SERVICEACCOUNTS_RELATION_NAME,
            manifests_items=self._serviceaccounts_manifests,
        )

    @property
    def _poddefaults_manifests(self):
        return self._get_manifests(PODDEFAULTS_RELATION_NAME, self._manifests_folder)

    @property
    def _secrets_manifests(self):
        return self._get_manifests(SECRETS_RELATION_NAME, self._manifests_folder)

    @property
    def _serviceaccounts_manifests(self):
        return self._get_manifests(SERVICEACCOUNTS_RELATION_NAME, self._manifests_folder)

    def _get_manifests(self, resource_type, folder) -> List[KubernetesManifest]:
        manifests = []
        manifest_files = glob.glob(f"{folder}/{resource_type}/*.yaml")
        for file in manifest_files:
            file_content = Path(file).read_text()
            manifests.append(KubernetesManifest(file_content))
        return manifests

    def _on_start(self, _):
        """Set active on start."""
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(ManifestsTesterCharm)
