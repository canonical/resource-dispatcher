#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

"""Mock relation provider charms."""

import glob
import json
import logging
from pathlib import Path

import yaml
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

logger = logging.getLogger(__name__)


class ManifestsTesterCharm(CharmBase):
    """Charm for sending manifests to ResourceDispatcher relations."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "manifests-tester"
        self._secrets_folder = self.model.config["test_data"]

        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_event)

        for rel in self.model.relations.keys():
            self.framework.observe(self.on[rel].relation_changed, self._on_event)

    def _on_start(self, _):
        """Set active on start."""
        self.model.unit.status = ActiveStatus()

    def _get_interfaces(self):
        """Retrieve interface object."""
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed:
            self.model.unit.status = WaitingStatus()
            return {"secrets": None}
        except NoCompatibleVersions:
            self.model.unit.status = BlockedStatus()
            return {"secrets": None}
        return interfaces

    def _send_manifests(self, interfaces, folder, relation):
        """Send manifests from folder to desired relation."""
        if relation in interfaces and interfaces[relation]:
            manifests = []
            logger.info(f"Scanning folder {folder}")
            manifest_files = glob.glob(f"{folder}/*.yaml")
            for file in manifest_files:
                manifest = yaml.safe_load(Path(file).read_text())
                manifests.append(manifest)
            data = {relation: json.dumps(manifests)}
            interfaces[relation].send_data(data)

    def _on_event(self, _) -> None:
        """Perform all required actions for the Charm."""
        interfaces = self._get_interfaces()
        self._send_manifests(interfaces, self._secrets_folder, "secrets")
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(ManifestsTesterCharm)
