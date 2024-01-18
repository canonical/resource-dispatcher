#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

import logging

import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.kubernetes_manifests.v0.kubernetes_manifests import KubernetesManifestsProvider
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import APIError, ChangeError, Layer

K8S_RESOURCE_FILES = ["src/templates/decorator-controller.yaml.j2"]
DISPATCHER_RESOURCES_PATH = "/app/resources"
PODDEFAULTS_RELATION_NAME = "pod-defaults"
SECRETS_RELATION_NAME = "secrets"
SERVICEACCOUNTS_RELATION_NAME = "service-accounts"


class ResourceDispatcherOperator(CharmBase):
    """A Juju charm for ResourceDispatcher"""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
        self._port = 80
        self._namespace_label = self.model.config["target_namespace_label"]
        self._container_name = "resource-dispatcher"
        self._container = self.unit.get_container(self._container_name)

        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "port": self._port,
            "label": self._namespace_label,
        }

        self._k8s_resource_handler = None

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.remove, self._on_remove)

        port = ServicePort(int(self._port), name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(
            self,
            [port],
            service_type="ClusterIP",
            service_name=f"{self.model.app.name}",
            refresh_event=self.on.config_changed,
        )

        self._poddefaults_manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=PODDEFAULTS_RELATION_NAME
        )
        self._secrets_manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=SECRETS_RELATION_NAME
        )
        self._serviceaccounts_manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=SERVICEACCOUNTS_RELATION_NAME
        )

        for provider in [
            self._poddefaults_manifests_provider,
            self._secrets_manifests_provider,
            self._serviceaccounts_manifests_provider,
        ]:
            self.framework.observe(provider.on.updated, self._on_event)

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
                        "main.py "
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

    def _check_container(self, event: EventBase):
        """Check if we can connect the container."""
        if not self.container.can_connect():
            event.defer()
            raise ErrorWithStatus("Container is not ready", WaitingStatus)

    def _deploy_k8s_resources(self) -> None:
        """Deploys K8S resources."""
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()
        except ApiError as err:
            raise GenericCharmRuntimeError("K8S resources creation failed") from err
        self.model.unit.status = WaitingStatus(
            "K8s resources created. Waiting for charm to be active"
        )

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
                raise GenericCharmRuntimeError(f"Failed to replan with error: {str(err)}") from err

    def _get_manifests(self, manifests_provider):
        """Unpacks and returns the manifests relation data."""

        manifests = []
        manifests = manifests_provider.get_manifests()
        self.logger.debug(f"manifests are {manifests}")
        return manifests

    def _manifests_valid(self, manifests):
        """Checks if manifests are unique."""
        if manifests:
            for manifest in manifests:
                if (
                    sum([m["metadata"]["name"] == manifest["metadata"]["name"] for m in manifests])
                    > 1
                ):
                    return False
        return True

    def _sync_manifests(self, manifests, push_location):
        """Push list of manifests into layer.

        Args:
            manifests: List of kubernetes manifests to be pushed to pebble layer.
            push_location: Container location where the manifests should be pushed to.
        """
        try:
            all_files = self.container.list_files(push_location)
        except APIError as e:
            if "no such file or directory" in e.message:
                self.logger.info(
                    f"Resource push location '{push_location}' does not exist - creating it"
                )
                all_files = []
            else:
                raise e
        if manifests:
            manifests_locations = [
                f"{push_location}/{m['metadata']['name']}.yaml" for m in manifests
            ]
        else:
            manifests_locations = []
        if all_files:
            for file in all_files:
                if file.path not in manifests_locations:
                    self.container.remove_path(file.path)
        if manifests:
            for manifest in manifests:
                filename = manifest["metadata"]["name"]
                self.container.push(
                    f"{push_location}/{filename}.yaml", yaml.dump(manifest), make_dirs=True
                )

    def _update_manifests(self, manifests_provider, dispatch_folder):
        """Get manifests from relation and update them in dispatcher folder."""
        manifests = self._get_manifests(manifests_provider)
        if not self._manifests_valid(manifests):
            self.logger.debug(
                f"Manifests names in all relations must be unique {','.join(str(m) for m in manifests)}"  # noqa E501
            )
            raise ErrorWithStatus(
                "Failed to process invalid manifest. See debug logs.",
                BlockedStatus,
            )
        self.logger.debug(f"received {manifests_provider._relation_name} are {manifests}")
        self._sync_manifests(manifests, dispatch_folder)

    def _on_event(self, event: EventBase) -> None:
        """Perform all required actions for the Charm."""
        try:
            self._check_leader()
            self._check_container(event)
            self._update_layer()
            self._update_manifests(
                self._secrets_manifests_provider,
                f"{DISPATCHER_RESOURCES_PATH}/{SECRETS_RELATION_NAME}",
            )
            self._update_manifests(
                self._serviceaccounts_manifests_provider,
                f"{DISPATCHER_RESOURCES_PATH}/{SERVICEACCOUNTS_RELATION_NAME}",
            )
            self._update_manifests(
                self._poddefaults_manifests_provider,
                f"{DISPATCHER_RESOURCES_PATH}/{PODDEFAULTS_RELATION_NAME}",
            )
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
            if err.status.code != 404:
                self.logger.error(f"Failed to delete K8S resources, with error: {err}")
                raise err
        self.unit.status = MaintenanceStatus("K8S resources removed")


if __name__ == "__main__":  # pragma: nocover
    main(ResourceDispatcherOperator)
