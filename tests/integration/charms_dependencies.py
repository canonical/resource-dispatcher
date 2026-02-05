"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="4.11/stable", trust=True
)
