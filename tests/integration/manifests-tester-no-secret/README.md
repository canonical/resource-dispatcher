# Manifests Tester Charm

This charm is intended solely for testing purposes.

It uses the `charm-python` part in `charmcraft.yaml`, which requires that all Python dependencies (including transitive ones) be resolved in advance and explicitly listed in `requirements.txt`.

To update `requirements.txt`, use the following command with Python 3.12:

```bash
pip-compile --resolver=backtracking requirements.in
```
