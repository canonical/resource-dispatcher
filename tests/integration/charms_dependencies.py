"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="4.11/stable", trust=True
)
RESOURCE_DISPATCHER_NO_SECRET = CharmSpec(
    charm="resource-dispatcher", channel="2.0/stable", trust=True
)
