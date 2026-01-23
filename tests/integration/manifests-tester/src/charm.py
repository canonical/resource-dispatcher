#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

"""Mock relation provider charms."""

import glob
import logging
from pathlib import Path
from typing import List

from charms.resource_dispatcher.v0.kubernetes_manifests import (
    KubernetesManifest,
    KubernetesManifestRequirerWrapper,
)
from ops import main
from ops.charm import CharmBase
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)

PODDEFAULTS_RELATION_NAME = "pod-defaults"
SECRETS_RELATION_NAME = "secrets"
SERVICEACCOUNTS_RELATION_NAME = "service-accounts"
ROLES_RELATION_NAME = "roles"
ROLEBINDINGS_RELATION_NAME = "role-bindings"

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
        self.framework.observe(self.on.upgrade_charm, self._update_manifests_in_relation)
        self.framework.observe(self.on.config_changed, self._update_manifests_in_relation)
        self.framework.observe(self.on.leader_elected, self._update_manifests_in_relation)
        self.framework.observe(
            self.on[SERVICEACCOUNTS_RELATION_NAME].relation_created,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[SERVICEACCOUNTS_RELATION_NAME].relation_changed,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[SECRETS_RELATION_NAME].relation_created,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[SECRETS_RELATION_NAME].relation_changed,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[PODDEFAULTS_RELATION_NAME].relation_created,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[PODDEFAULTS_RELATION_NAME].relation_changed,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[ROLES_RELATION_NAME].relation_created,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[ROLES_RELATION_NAME].relation_changed,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[ROLEBINDINGS_RELATION_NAME].relation_created,
            self._update_manifests_in_relation,
        )
        self.framework.observe(
            self.on[ROLEBINDINGS_RELATION_NAME].relation_changed,
            self._update_manifests_in_relation,
        )

        self.service_accounts_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=SERVICEACCOUNTS_RELATION_NAME
        )
        self.secrets_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=SECRETS_RELATION_NAME
        )
        self.poddefaults_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=PODDEFAULTS_RELATION_NAME
        )
        self.roles_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=ROLES_RELATION_NAME
        )
        self.rolebindings_requirer_wrapper = KubernetesManifestRequirerWrapper(
            charm=self, relation_name=ROLEBINDINGS_RELATION_NAME
        )

    @property
    def _poddefaults_manifests(self):
        return self._get_manifests(PODDEFAULTS_RELATION_NAME, self._manifests_folder)

    @property
    def _secrets_manifests(self):
        return self._get_manifests(SECRETS_RELATION_NAME, self._manifests_folder)

    @property
    def _roles_manifests(self):
        return self._get_manifests(ROLES_RELATION_NAME, self._manifests_folder)

    @property
    def _rolebindings_manifests(self):
        return self._get_manifests(ROLEBINDINGS_RELATION_NAME, self._manifests_folder)

    def _get_manifests(self, resource_type, folder) -> List[KubernetesManifest]:
        manifests = []
        manifest_files = glob.glob(f"{folder}/{resource_type}/*.yaml")
        for file in manifest_files:
            file_content = Path(file).read_text()
            manifests.append(KubernetesManifest(file_content))
        return manifests

    def _on_start(self, event):
        """Set active on start."""
        self._update_manifests_in_relation(event=event)
        self.model.unit.status = ActiveStatus()

    def _update_manifests_in_relation(self, event):
        service_account_name = self.model.config["service_account_name"]
        serviceaccount_manifest = [
            KubernetesManifest(SERVICE_ACCOUNT_YAML.format(name=service_account_name))
        ]

        self.service_accounts_requirer_wrapper.send_data(serviceaccount_manifest)
        self.secrets_requirer_wrapper.send_data(self._secrets_manifests)
        self.poddefaults_requirer_wrapper.send_data(self._poddefaults_manifests)
        self.roles_requirer_wrapper.send_data(self._roles_manifests)
        self.rolebindings_requirer_wrapper.send_data(self._rolebindings_manifests)


if __name__ == "__main__":  # pragma: nocover
    main(ManifestsTesterCharm)
