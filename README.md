# Resource Dispatcher Operator
## Description

The Resource Dispatcher Operator for Juju enable allows you to deploy default resources to specific kubernetes namespaces.

## Usage

The Resource Dispatcher Operator may be deployed using the Juju command line as
follows

```sh
$ juju deploy resource-dispatcher
```

## Manifest conflict resolution

Resource Dispatcher accepts manifests from multiple Juju relations. Each manifest is
identified by the tuple (`metadata.namespace`, `metadata.name`).

### Pinned vs. global manifests

A manifest that sets `metadata.namespace` is called a **namespace-pinned** manifest, and is
applied only to that namespace. A manifest without `metadata.namespace` is called a
**global** manifest, and is applied to every profile namespace.

When a pinned manifest and a global manifest share the same `metadata.name`, the pinned
manifest **takes precedence** for its namespace. This allows a global default to be
overridden for a specific namespace.

In the case of two manifests sharing the (`metadata.namespace`, `metadata.name`) key, a conflict occurs, resulting in a `BlockedStatus`. This includes two manifests with the same name and without a namespace.

### Manifest saving layout

Manifests are written into the pebble layer under the dispatch folder using a two-level
directory structure:

```
<dispatch_folder>/
  _global/           # unpinned manifests (no namespace)
    <name>.yaml
  <namespace>/       # namespace-pinned manifests
    <name>.yaml
```

## Looking for a fully supported platform for MLOps?

Canonical [Charmed Kubeflow](https://charmed-kubeflow.io) is a state of the art, fully supported MLOps platform that helps data scientists collaborate on AI innovation on any cloud from concept to production, offered by Canonical - the publishers of [Ubuntu](https://ubuntu.com).

[![Kubeflow diagram](https://res.cloudinary.com/canonical/image/fetch/f_auto,q_auto,fl_sanitize,w_350,h_304/https://assets.ubuntu.com/v1/10400c98-Charmed-kubeflow-Topology-header.svg)](https://charmed-kubeflow.io)


Charmed Kubeflow is free to use: the solution can be deployed in any environment without constraints, paywall or restricted features. Data labs and MLOps teams only need to train their data scientists and engineers once to work consistently and efficiently on any cloud – or on-premise.

Charmed Kubeflow offers a centralised, browser-based MLOps platform that runs on any conformant Kubernetes – offering enhanced productivity, improved governance and reducing the risks associated with shadow IT.

Learn more about deploying and using Charmed Kubeflow at [https://charmed-kubeflow.io](https://charmed-kubeflow.io).


### Key features
* Centralised, browser-based data science workspaces: **familiar experience**
* Multi user: **one environment for your whole data science team**
* NVIDIA GPU support: **accelerate deep learning model training**
* Apache Spark integration: **empower big data driven model training**
* Ideation to production: **automate model training & deployment**
* AutoML: **hyperparameter tuning, architecture search**
* Composable: **edge deployment configurations available**


### What’s included in Charmed Kubeflow 1.4
* LDAP Authentication
* Jupyter Notebooks
* Work with Python and R
* Support for TensorFlow, Pytorch, MXNet, XGBoost
* TFServing, Seldon-Core
* Katib (autoML)
* Apache Spark
* Argo Workflows
* Kubeflow Pipelines

### Why engineers and data scientists choose Charmed Kubeflow
* Maintenance: Charmed Kubeflow offers up to two years of maintenance on select releases
* Optional 24/7 support available, [contact us here](https://charmed-kubeflow.io/contact-us) for more information
* Optional dedicated fully managed service available, [contact us here](https://charmed-kubeflow.io/contact-us) for more information or [learn more about Canonical’s Managed Apps service](https://ubuntu.com/managed/apps).
* Portability: Charmed Kubeflow can be deployed on any conformant Kubernetes, on any cloud or on-premise

### Documentation
Please see the [official docs site](https://charmed-kubeflow.io/docs) for complete documentation of the Charmed Kubeflow distribution.

### Bugs and feature requests
If you find a bug in our operator or want to request a specific feature, please file a bug here: 
[https://github.com/canonical/seldon-core-operator/issues](https://github.com/canonical/seldon-core-operator/issues)


### License
Charmed Kubeflow is free software, distributed under the [Apache Software License, version 2.0](https://github.com/canonical/seldon-core-operator/blob/master/LICENSE).


### Contributing
Canonical welcomes contributions to Charmed Kubeflow. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the distribution.

### Security
Security issues in Charmed Kubeflow can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.
