#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#

import logging

import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.service_mesh import generate_allow_all_authorization_policy
from charms.istio_beacon_k8s.v0.service_mesh import (
    MeshType,
    PolicyResourceManager,
    ServiceMeshConsumer,
)
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.resource_dispatcher.v0.kubernetes_manifests import KubernetesManifestsProvider
from lightkube import ApiError, Client
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops import UpgradeCharmEvent, main
from ops.charm import CharmBase
from ops.framework import EventBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import APIError, ChangeError, Layer

K8S_RESOURCE_FILES = ["src/templates/decorator-controller.yaml.j2"]
DISPATCHER_RESOURCES_PATH = "/var/lib/pebble/default/resources"  # NOTE: in Pebble user's home dir
PODDEFAULTS_RELATION_NAME = "pod-defaults"
SECRETS_RELATION_NAME = "secrets"
SERVICEACCOUNTS_RELATION_NAME = "service-accounts"
ROLES_RELATION_NAME = "roles"
ROLEBINDINGS_RELATION_NAME = "role-bindings"


class ResourceDispatcherOperator(CharmBase):
    """A Juju charm for ResourceDispatcher"""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)

        self._app_name = self.app.name
        self._service_mesh_relation_name = "service-mesh"
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
        self._service_port = 80
        self._webserver_port = 8080
        self._namespace_label = self.model.config["target_namespace_label"]
        self._container_name = "resource-dispatcher"
        self._container = self.unit.get_container(self._container_name)

        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "service_port": self._service_port,
            "label": self._namespace_label,
        }

        self._k8s_resource_handler = None

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.remove, self._on_remove)

        port = ServicePort(
            port=self._service_port, targetPort=self._webserver_port, name=f"{self.app.name}"
        )
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
        self._roles_manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=ROLES_RELATION_NAME
        )
        self._rolebindings_manifests_provider = KubernetesManifestsProvider(
            charm=self, relation_name=ROLEBINDINGS_RELATION_NAME
        )
        for provider in [
            self._poddefaults_manifests_provider,
            self._secrets_manifests_provider,
            self._serviceaccounts_manifests_provider,
            self._roles_manifests_provider,
            self._rolebindings_manifests_provider,
        ]:
            self.framework.observe(provider.on.updated, self._on_event)

        # for an ambient-mode service mesh:

        self._check_leader()

        self._mesh = ServiceMeshConsumer(
            self, policies=None  # custom AuthorizationPolicies managed below
        )

        self._authorization_policy_resource_manager = PolicyResourceManager(
            charm=self,
            lightkube_client=Client(field_manager=f"{self._app_name}-{self._namespace}"),
            labels={
                "app.kubernetes.io/instance": f"{self._app_name}-{self._namespace}",
                "kubernetes-resource-handler-scope": f"{self._app_name}-allow-all",
            },
            logger=self.logger,
        )

        # to update AuthorizationPolicies when the ambient-mode relation with the service mesh
        # provider is updated:
        for event in (
            self.on.service_mesh_relation_changed,
            self.on.service_mesh_relation_broken,
        ):
            self.framework.observe(event, self._on_service_mesh_relation_events)

        # NOTE: a custom AuthorizationPolicy that allows any incoming traffic to the workload is
        # defined here (and applied below) because it is required to receive API calls from
        # Metacontroller, whose webhook Resource Dispatcher implements, as Metacontroller does
        # not have Juju relations with Resource Dispatcher (yet, at the time of writing) and is
        # therefore not possible to allow traffic from one to the other via neither the
        # AppPolicy nor the UnitPolicy by istio_beacon_k8s.v0.service_mesh
        self._allow_all_to_workload_auth_policy = generate_allow_all_authorization_policy(
            app_name=self._app_name,
            namespace=self._namespace,
        )

    @property
    def container(self):
        """Return container."""
        return self._container

    @property
    def poddefaults_manifests_provider(self):
        """Returns the KubernetesManifestsProvider for Pod Defaults"""
        return self._poddefaults_manifests_provider

    @property
    def secrets_manifests_provider(self):
        """Returns the KubernetesManifestsProvider for Secrets"""
        return self._secrets_manifests_provider

    @property
    def service_accounts_manifests_provider(self):
        """Returns the KubernetesManifestsProvider for Service Accounts"""
        return self._service_accounts_manifests_provider

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
                        f"--port {self._webserver_port} "
                        f"--label {self._namespace_label} "
                        f"--folder {DISPATCHER_RESOURCES_PATH}"
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

    def _on_upgrade_charm(self, event: UpgradeCharmEvent):
        """Handle event when charm is upgraded"""
        # deploy K8S resources to speed up deployment
        self._deploy_k8s_resources()
        self._on_event(event=event)

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
        manifests = manifests_provider.get_manifests()
        self.logger.debug(f"manifests are {manifests}")
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
            self._update_manifests(
                self._roles_manifests_provider,
                f"{DISPATCHER_RESOURCES_PATH}/{ROLES_RELATION_NAME}",
            )
            self._update_manifests(
                self._rolebindings_manifests_provider,
                f"{DISPATCHER_RESOURCES_PATH}/{ROLEBINDINGS_RELATION_NAME}",
            )
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.info(f"Event {event} stopped early with message: {str(err)}")
            return
        self.model.unit.status = ActiveStatus()

    @property
    def ambient_mesh_enabled(self) -> bool:
        """Whether the relation with the ambient-mode service-mesh provider is setup."""
        if self.model.get_relation(self._service_mesh_relation_name):
            return True
        return False

    def _on_service_mesh_relation_events(self, event: EventBase) -> None:
        """Update AuthorizationPolicies according to service-mesh relation changes."""
        self._check_leader()

        # verifying that the defined AuthorizationPolicy is valid (i.e. supported):
        try:
            self._authorization_policy_resource_manager._validate_raw_policies(
                [self._allow_all_to_workload_auth_policy]
            )
        except (RuntimeError, TypeError) as e:
            raise GenericCharmRuntimeError(f"Error validating raw policies: {e}")

        # ensuring the allow-all AuthorizationPolicies is in place (only) when in ambient mode:
        policies = []
        if self.ambient_mesh_enabled:
            self.logger.info("Ambient mode enabled, creating the allow-all policy...")
            policies.append(self._allow_all_to_workload_auth_policy)
        else:
            self.logger.info("Ambient mode disabled, removing the allow-all policy...")
        self._authorization_policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=policies
        )

        self.model.unit.status = ActiveStatus()

    def _on_remove(self, _):
        """Remove all resources."""
        self._check_leader()

        self.unit.status = MaintenanceStatus("Removing K8S resources")

        # remove all AuthorizationPolicies that target the workload:
        self._authorization_policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=[]
        )

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
