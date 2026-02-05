"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="latest/edge", trust=True
)
RESOURCE_DISPATCHER_NO_SECRET = CharmSpec(
    charm="resource-dispatcher", channel="2.0/stable", trust=True
)

# for Istio in ambient mode:
ISTIO_BEACON_K8S = CharmSpec(charm="istio-beacon-k8s", channel="2/edge", trust=True)
ISTIO_K8S = CharmSpec(charm="istio-k8s", channel="2/edge", trust=True, config={"platform": ""})
