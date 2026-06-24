# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from lightkube import codecs
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import GenericNamespacedResource, load_in_cluster_generic_resources
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

RESOURCE_DISPATCHER_CHARM_NAME = "resource-dispatcher"
RESOURCE_DISPATCHER_NO_SECRET_REVISION = (
    402  # Revision that still uses kubernetes_manifests lib 0.1
)
RESOURCE_DISPATCHER_NO_SECRET_OCI_IMAGE = "charmedkubeflow/resource-dispatcher:1.0-22.04"  # Image before feature for roles and rolebindings were added


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


@retry(
    wait=wait_exponential(max=10),
    stop=stop_after_delay(60),
    reraise=True,
)
def assert_resource_status(
    lightkube_client: lightkube.Client,
    resource_type: GenericNamespacedResource,
    name: str,
    namespace: str,
    exists: bool = True,
):
    """Assert whether a Kubernetes resource exists, raising a clear error otherwise.

    When ``exists`` is ``True`` (the default), assert the resource is present and
    return the fetched object for further assertions. When ``exists`` is ``False``,
    assert the resource is absent. lightkube's ``get`` raises an ``ApiError`` with a
    404 status when the resource is missing, which this helper translates into an
    explicit ``AssertionError`` with a useful message depending on the expectation.
    The check is retried with exponential backoff (capped at 10s per wait) for up to
    60s to allow for the reconciliation loop to converge.
    """
    try:
        obj = lightkube_client.get(resource_type, name, namespace=namespace)
    except ApiError as e:
        if e.status.code == 404:
            if exists:
                raise AssertionError(
                    f"Expected {resource_type.__name__} '{name}' to exist in namespace "
                    f"'{namespace}'"
                ) from e
            return
        raise
    if not exists:
        raise AssertionError(
            f"Expected {resource_type.__name__} '{name}' to be absent from namespace "
            f"'{namespace}'"
        )
    return obj
