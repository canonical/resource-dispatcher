import logging

from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.service_mesh import generate_allow_all_authorization_policy
from charms.istio_beacon_k8s.v0.service_mesh import (
    MeshType,
    PolicyResourceManager,
    ServiceMeshConsumer,
)
from lightkube import Client
from ops import ActiveStatus, StatusBase

logger = logging.getLogger(__name__)


class ServiceMeshComponent(Component):
    """Component to manage the integration with Istio in ambient mode."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._app_name = self._charm.app.name
        self._app_namespace = self._charm.model.name
        self._service_mesh_relation_name = "service-mesh"

        self._mesh = ServiceMeshConsumer(
            self._charm, policies=None  # custom AuthorizationPolicies managed below
        )

        # to update AuthorizationPolicies when the ambient-mode relation with the service mesh
        # provider is updated:
        self._events_to_observe = [
            self._charm.on[self._service_mesh_relation_name].relation_changed,
            self._charm.on[self._service_mesh_relation_name].relation_broken,
        ]

        self._authorization_policy_resource_manager = PolicyResourceManager(
            charm=self._charm,
            lightkube_client=Client(field_manager=f"{self._app_name}-{self._app_namespace}"),
            labels={
                "app.kubernetes.io/instance": f"{self._app_name}-{self._app_namespace}",
                "kubernetes-resource-handler-scope": f"{self._app_name}-allow-all",
            },
            logger=logger,
        )

        # NOTE: a custom AuthorizationPolicy that allows any incoming traffic to the workload is
        # defined here (and applied below) because it is required to receive API calls from
        # Metacontroller, whose webhook Resource Dispatcher implements, as Metacontroller does not
        # have Juju relations with Resource Dispatcher (yet, at the time of writing) and is
        # therefore not possible to allow traffic from one to the other via neither the AppPolicy
        # nor the UnitPolicy by istio_beacon_k8s.v0.service_mesh
        self._allow_all_to_workload_authorization_policy = generate_allow_all_authorization_policy(
            app_name=self._app_name,
            namespace=self._app_namespace,
        )

    def get_status(self) -> StatusBase:
        if self.ambient_mesh_enabled:
            try:
                # verifying that the defined AuthorizationPolicy is valid (i.e. supported):
                self._authorization_policy_resource_manager._validate_raw_policies(
                    [self._allow_all_to_workload_authorization_policy]
                )

            except (RuntimeError, TypeError) as e:
                raise GenericCharmRuntimeError(f"Error validating raw policies: {e}")

        return ActiveStatus()

    def _configure_app_leader(self, event):
        """Ensure the allow-all AuthorizationPolicies is in place (only) when in ambient mode."""
        policies = []

        if self.ambient_mesh_enabled:
            logger.info("Ambient mode enabled, creating the allow-all policy...")
            policies.append(self._allow_all_to_workload_authorization_policy)
        else:
            logger.info("Ambient mode disabled, removing the allow-all policy...")

        self._authorization_policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=policies
        )

    def remove(self, event):
        """Remove all AuthorizationPolicies that target the workload, on charm removal."""
        self._authorization_policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=[]
        )

    @property
    def ambient_mesh_enabled(self) -> bool:
        """Whether the charm is in ambient mode.

        It verifies if the relation with the ambient-mode service-mesh provider is setup.
        """
        if self._charm.model.get_relation(self._service_mesh_relation_name):
            return True

        return False
