# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
import subprocess
import time
from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.resources.core_v1 import Secret
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

CHARM_NAME = "resource-dispatcher"
MANIFEST_CHARM_NAME1 = "manifests-tester1"
MANIFEST_CHARM_NAME2 = "manifests-tester2"
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


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=CHARM_NAME)
    return client


@pytest.fixture(scope="function")
def namespace(lightkube_client: lightkube.Client):
    yaml_text = _safe_load_file_to_text(NAMESPACE_FILE)
    yaml_rendered = yaml.safe_load(yaml_text)
    for label in TESTING_LABELS:
        yaml_rendered["metadata"]["labels"][label] = "true"
    obj = codecs.from_dict(yaml_rendered)
    lightkube_client.apply(obj)

    yield obj.metadata.name

    delete_all_from_yaml(yaml_text, lightkube_client)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_dispatcher_charm(ops_test: OpsTest):
    await ops_test.model.deploy(
        entity_url=METACONTROLLER_CHARM_NAME,
        channel="latest/edge",
        trust=True,
    )

    built_charm_path = await ops_test.build_charm("./")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=CHARM_NAME,
        resources=resources,
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME, METACONTROLLER_CHARM_NAME],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
    )

    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_build_and_deploy_helper_charms(ops_test: OpsTest):
    build_manifests_charm_path = await ops_test.build_charm("./tests/integration/manifests-tester")
    await ops_test.model.deploy(
        entity_url=build_manifests_charm_path,
        application_name=MANIFEST_CHARM_NAME1,
        trust=True,
    )
    await ops_test.model.deploy(
        entity_url=build_manifests_charm_path,
        application_name=MANIFEST_CHARM_NAME2,
        trust=True,
        config={"test_data": "src/secrets2"},
    )

    await ops_test.model.relate(CHARM_NAME, MANIFEST_CHARM_NAME1)
    await ops_test.model.relate(CHARM_NAME, MANIFEST_CHARM_NAME2)

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME, METACONTROLLER_CHARM_NAME, MANIFEST_CHARM_NAME1, MANIFEST_CHARM_NAME2],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
    )
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_secrets_created_from_both_helpers(
    lightkube_client: lightkube.Client, namespace: str
) -> None:
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    secret = lightkube_client.get(Secret, SECRET_NAME, namespace=namespace)
    assert secret.data == {
        "AWS_ACCESS_KEY_ID": base64.b64encode("access_key".encode("utf-8")).decode("utf-8"),
        "AWS_SECRET_ACCESS_KEY": base64.b64encode("secret_access_key".encode("utf-8")).decode(
            "utf-8"
        ),
    }
    secrets = lightkube_client.list(Secret, namespace=namespace)
    assert len(list(secrets)) == 4


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    subprocess.Popen(["juju", "remove-relation", CHARM_NAME, MANIFEST_CHARM_NAME1])
    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME, METACONTROLLER_CHARM_NAME, MANIFEST_CHARM_NAME1, MANIFEST_CHARM_NAME2],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=300,
        idle_period=30
    )


@pytest.mark.abort_on_fail
async def test_remove_one_helper_relation(
    ops_test: OpsTest, lightkube_client: lightkube.Client, namespace: str
):
    time.sleep(
        30
    )  # sync can take up to 10 seconds for reconciliation loop to trigger (+ time to create namespace)
    secrets = lightkube_client.list(Secret, namespace=namespace)
    assert len(list(secrets)) == 2
