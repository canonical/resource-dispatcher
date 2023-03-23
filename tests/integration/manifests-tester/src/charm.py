
#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

import glob
import json
import logging
import yaml

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus

from serialized_data_interface import get_interfaces

logger = logging.getLogger(__name__)

SECRETS_FOLDER = "src/secrets"


class ManifestsTesterCharm(CharmBase):
    """Charm for sending manifests to ResourceDispatcher relations."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "manifests-tester"

        for rel in self.model.relations.keys():
            self.framework.observe(self.on[rel].relation_changed, self._on_event)

    def _send_manifests(self, interfaces, folder, relation):
        if interfaces[relation]:
            manifests = []
            manifest_files = glob.glob(f"{folder}/*.yaml")
            for file in manifest_files:
                manifest = yaml.safe_load(file)
            manifests.append(manifest)
            interfaces[relation].send_data({relation: json.dumps(manifests)})

    def _on_event(self, _) -> None:
        """Perform all required actions for the Charm."""
        interfaces = get_interfaces(self)
        self._send_manifests(interfaces, SECRETS_FOLDER, "secret")
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(ManifestsTesterCharm)
