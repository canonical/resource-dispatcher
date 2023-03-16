#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

import logging

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer

K8S_RESOURCE_FILES = ["src/templates/composite-controller.yaml.j2"]


class ResourceDispatcherOperator(CharmBase):
    """A Juju charm for ResourceDispatcher"""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
        self._port = self.model.config["resource_dispatcher_port"]
        self._namespace_label = self.model.config["target_namespace_label"]
        self._container_name = "resource-dispatcher"
        self._container = self.unit.get_container(self._container_name)

        self._context = {"app_name": self._name, "namespace": self._namespace}

        self._k8s_resource_handler = None

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.resource_dispatcher_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.remove, self._on_remove)

        # for rel in self.model.relations.keys():
        #     self.framework.observe(self.on[rel].relation_changed, self._on_event)

        port = ServicePort(int(self._port), name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(
            self,
            [port],
            service_type="ClusterIP",
            service_name=f"{self.model.app.name}",
            refresh_event=self.on.config_changed,
        )

    @property
    def container(self):
        """Return container."""
        return self._container

    @property
    def _resource_dispatcher_operator_layer(self) -> Layer:
        """Create and return Pebble framework layer."""
        layer_config = {
            "summary": "resource-dispatcher layer",
            "description": "Pebble config layer for resource-dispatcher-operator",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "Entrypoint of resource-dispatcher-operator image",
                    "command": (
                        "python3 "
                        "server.py "
                        f"--port {self._port} "
                        f"--label {self._namespace_label}"
                    ),
                    "startup": "enabled",
                }
            },
        }

        return Layer(layer_config)

    @property
    def k8s_resource_handler(self):
        """Update K8S with K8S resources."""
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        self._k8s_resource_handler = handler

    def _check_leader(self):
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            self.logger.info("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _on_pebble_ready(self, _):
        """Configure started container."""
        if not self.container.can_connect():
            # Pebble Ready event should indicate that container is available
            raise ErrorWithStatus("Pebble is ready and container is not ready", BlockedStatus)

        # proceed with other actions
        self._on_event(_)

    def _deploy_k8s_resources(self) -> None:
        """Deploys K8S resources."""
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()
        except ApiError:
            raise ErrorWithStatus("K8S resources creation failed", BlockedStatus)
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _on_install(self, _):
        """Installation only tasks."""
        # deploy K8S resources to speed up deployment
        self._deploy_k8s_resources()

    def _update_layer(self) -> None:
        """Update the Pebble configuration layer (if changed)."""
        current_layer = self.container.get_plan()
        new_layer = self._resource_dispatcher_operator_layer
        if current_layer.services != new_layer.services:
            self.unit.status = MaintenanceStatus("Applying new pebble layer")
            self.container.add_layer(self._container_name, new_layer, combine=True)
            try:
                self.logger.info("Pebble plan updated with new configuration, replaning")
                self.container.replan()
            except ChangeError as err:
                raise ErrorWithStatus(f"Failed to replan with error: {str(err)}", BlockedStatus)

    def _on_event(self, event) -> None:
        """Perform all required actions for the Charm."""
        try:
            self._check_leader()
            self._deploy_k8s_resources()
            # interfaces = self._get_interfaces()
            self._update_layer()
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.info(f"Event {event} stopped early with message: {str(err)}")
            return
        self.model.unit.status = ActiveStatus()

    def _on_remove(self, _):
        """Remove all resources."""
        self.unit.status = MaintenanceStatus("Removing K8S resources")
        k8s_resources_manifests = self.k8s_resource_handler.render_manifests()
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, k8s_resources_manifests)
        except ApiError as err:
            self.logger.error(f"Failed to delete K8S resources, with error: {err}")
            raise err
        self.unit.status = MaintenanceStatus("K8S resources removed")


if __name__ == "__main__":  # pragma: nocover
    main(ResourceDispatcherOperator)
