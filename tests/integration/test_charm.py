# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from base64 import b64decode
from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import Namespace, Pod, Secret, ServiceAccount
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

CHARM_NAME = "resource-dispatcher"
METACONTROLLER_CHARM_NAME = "metacontroller-operator"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
NAMESPACE_FILE = "./tests/integration/namespace.yaml"
TESTING_LABELS = ["user.kubeflow.org/enabled"]  # Might be more than one in the future
SECRET_NAME = "mlpipeline-minio-artifact"


def _safe_load_file_to_text(filename: str) -> str:
    """Returns the contents of filename if it is an existing file, else it returns filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=CHARM_NAME)
    return client


@pytest.fixture(scope="session")
def namespace(lightkube_client: lightkube.Client):
    yaml_text = _safe_load_file_to_text(NAMESPACE_FILE)
    yaml_rendered = yaml.safe_load(yaml_text)
    for label in TESTING_LABELS:
        yaml_rendered["metadata"]["labels"][label] = "true"
    obj = codecs.from_dict(yaml_rendered)
    try:
        lightkube_client.apply(obj)
    except lightkube.core.exceptions.ApiError as e:
        raise e

    yield obj.metadata.name


@pytest.mark.abort_on_fail
async def test_build_and_deploy_charms(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm("./")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=METACONTROLLER_CHARM_NAME,
        channel="latest/edge",
        trust=True,
    )

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=CHARM_NAME,
        resources=resources,
        trust=True,
    )

    await ops_test.model.wait_for_idle(status="active", raise_on_blocked=True, timeout=300)
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"

    await ops_test.model.wait_for_idle(
        apps=[METACONTROLLER_CHARM_NAME],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=600,
        idle_period=600
    )


@pytest.mark.abort_on_fail
async def test_minio_secret_added(lightkube_client: lightkube.Client, namespace: str) -> None:
    secret = lightkube_client.get(Secret, SECRET_NAME, namespace=namespace)
    assert secret != None
