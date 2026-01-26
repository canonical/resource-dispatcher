# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.testing import CharmSpec
from lightkube import codecs
from lightkube.generic_resource import load_in_cluster_generic_resources

logger = logging.getLogger(__name__)

RESOURCE_DISPATCHER_CHARM_NAME = "resource-dispatcher"
METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="latest/edge", trust=True
)
RESOURCE_DISPATCHER_NO_SECRET = CharmSpec(
    charm="resource-dispatcher", channel="2.0/stable", revision=402, trust=True
)
RESOURCE_DISPATCHER_NO_SECRET_REVISION = (
    402  # Revision that still uses kubernetes_manifests lib 0.1
)


def safe_load_file_to_text(filename: str) -> str:
    """Returns the contents of filename if it is an existing file, else it returns filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


def delete_all_from_yaml(yaml_text: str, lightkube_client: lightkube.Client = None):
    """Deletes all k8s resources listed in a YAML file via lightkube.

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        lightkube_client: Instantiated lightkube client or None
    """

    if lightkube_client is None:
        lightkube_client = lightkube.Client()

    for obj in codecs.load_all_yaml(yaml_text):
        lightkube_client.delete(type(obj), obj.metadata.name)


def deploy_k8s_resources(template_files: str):
    lightkube_client = lightkube.Client(field_manager=RESOURCE_DISPATCHER_CHARM_NAME)
    k8s_resource_handler = KubernetesResourceHandler(
        field_manager=RESOURCE_DISPATCHER_CHARM_NAME, template_files=template_files, context={}
    )
    load_in_cluster_generic_resources(lightkube_client)
    k8s_resource_handler.apply()


def get_or_build_charm(charm_path: Path, name: str) -> Path:
    if not (path := next(charm_path.glob("*.charm"), None)):
        logger.warning("Could not find packed %s charm. Building one now...", name)
        subprocess.run(["charmcraft", "pack"], check=True, cwd=charm_path)

    if not (path := next(charm_path.glob("*.charm"), None)):
        raise FileNotFoundError(f"Could neither find, nor build the {name} charm.")

    return path
