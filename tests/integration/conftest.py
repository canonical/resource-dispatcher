#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.

# See LICENSE file for licensing details.

import logging
import shutil
import subprocess
from pathlib import Path

import jubilant
import lightkube
import pytest
import yaml
from lightkube import codecs

from .helpers import delete_all_from_yaml, get_or_build_charm, safe_load_file_to_text

logger = logging.getLogger(__name__)
logging.getLogger("jubilant.wait").setLevel(logging.WARNING)


RESOURCE_DISPATCHER_CHARM_NAME = "resource-dispatcher"
MANIFESTS_TESTER_CHARM_PATH = Path("tests/integration/manifests-tester").absolute()
MANIFESTS_TESTER_NO_SECRET_CHARM_PATH = Path(
    "tests/integration/manifests-tester-no-secret"
).absolute()

NAMESPACE_MANIFEST_FILE = "./tests/integration/resources/namespace.yaml"
TESTING_LABELS = ["user.kubeflow.org/enabled"]  # Might be more than one in the future


def pytest_addoption(parser):
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="keep temporarily-created models",
    )


@pytest.fixture(scope="module")
def resource_dispatcher_charm() -> Path:
    """Path to the packed resource-dispatcher charm."""
    return get_or_build_charm(
        Path.cwd(),
        name="resource-dispatcher",
    )


@pytest.fixture(scope="module")
def manifest_tester_charm() -> Path:
    """Path to the packed manifest-tester charm with new lib that supports secrets."""
    return get_or_build_charm(
        Path.cwd() / "tests/integration/manifests-tester",
        name="manifest-tester",
    )


@pytest.fixture(scope="module")
def manifest_tester_no_secret_charm() -> Path:
    """Path to the packed manifest-tester charm with old lib that does not support secrets."""
    return get_or_build_charm(
        Path.cwd() / "tests/integration/manifests-tester-no-secret",
        name="manifest-tester-no-secret",
    )


@pytest.fixture(scope="module", autouse=True)
def copy_libraries_into_tester_charm() -> None:
    """Ensure that the tester charms use the current libraries."""
    lib = Path("lib/charms/resource_dispatcher/v0/kubernetes_manifests.py")
    Path(MANIFESTS_TESTER_CHARM_PATH, lib.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(lib.as_posix(), (MANIFESTS_TESTER_CHARM_PATH / lib).as_posix())


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=RESOURCE_DISPATCHER_CHARM_NAME)
    return client


@pytest.fixture(scope="module")
def namespace(lightkube_client: lightkube.Client):
    yaml_text = safe_load_file_to_text(NAMESPACE_MANIFEST_FILE)
    yaml_rendered = yaml.safe_load(yaml_text)
    for label in TESTING_LABELS:
        yaml_rendered["metadata"]["labels"][label] = "true"
    obj = codecs.from_dict(yaml_rendered)
    lightkube_client.apply(obj)

    yield obj.metadata.name

    delete_all_from_yaml(yaml_text, lightkube_client)


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    keep_models = bool(request.config.getoption("--keep-models"))

    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60

        yield juju  # run the test

        if request.session.testsfailed:
            log = juju.debug_log(limit=30)
            print(log, end="")

        status = juju.cli("status")
        debug_log = juju.debug_log(limit=1000)
        logger.info(debug_log)
        logger.info(status)
