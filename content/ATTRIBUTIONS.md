# Attributions for adapted documentation examples

Some code blocks in the lessons (shown as examples, with a caption naming their source) are adapted from, or follow,
other projects' documentation. This file gives the credit, licence and change notice for each of them; the caption
names the source, the lesson's references link to it, and `content/LICENSE.md` points here. Everything not listed
below is the project's own work under CC BY-SA 4.0.

The licences were read from each source's legal notice or footer in October 2026.

## Sources and their terms

| Source | Rights holder | Licence | Evidence |
|---|---|---|---|
| OpenShift Container Platform 4.21 documentation (docs.redhat.com), including the cert-manager Operator for Red Hat OpenShift, OADP and MetalLB chapters | Red Hat | Apache License 2.0, https://www.apache.org/licenses/LICENSE-2.0 ("Modified versions must remove all Red Hat trademarks") | https://docs.redhat.com/en/legal-notice/red-hat-openshift-container-platform and each book's Legal Notice |
| Monitoring stack for Red Hat OpenShift 4.21, Red Hat OpenShift Logging 6.6, Red Hat OpenShift Pipelines 1.21, Red Hat Advanced Cluster Management for Kubernetes 2.16 documentation | Red Hat | Creative Commons Attribution-ShareAlike 3.0 Unported, https://creativecommons.org/licenses/by-sa/3.0/ | each book's Legal Notice, for example https://docs.redhat.com/en/documentation/red_hat_openshift_logging/6.6/html/configure/legal-notice |
| Kubernetes documentation (kubernetes.io) | The Kubernetes Authors | Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/ | page footer; https://git.k8s.io/website/LICENSE |
| Tekton documentation (tekton.dev) | The Tekton Authors | text CC BY 4.0, code samples Apache License 2.0 | page footer of https://tekton.dev/docs/pipelines/tasks/ |
| Velero documentation (velero.io) | Velero Authors (Velero a Series of LF Projects, LLC) | Apache License 2.0 (the documentation lives in the vmware-tanzu/velero repository) | https://github.com/vmware-tanzu/velero/blob/main/LICENSE |
| CNCF TAG App Delivery Platforms white paper | The CNCF Authors | CC BY 4.0 | page footer of https://tag-app-delivery.cncf.io/whitepapers/platforms/ |

How the terms are met:

- **Credit and link**: the table below names the source page, its rights holder and its address (Red Hat's CC BY-SA
  notice asks for the URL of the original version).
- **Licence**: Apache License 2.0: full text in the repository (`LICENSE`) and in the built site (`licenses.txt`).
  Creative Commons: linked above.
- **Changes**: each example was rewritten for the course: names, namespaces and values replaced, fields left out, and
  comments added. The table says what was taken. Examples are not the complete source passages.
- **ShareAlike**: CC BY-SA 3.0 permits adaptations under a later version with the same licence elements (section
  4(b)); the course's adaptations of the Red Hat CC BY-SA 3.0 material are licensed under CC BY-SA 4.0, the licence of
  the course content. CC BY 4.0 and Apache-2.0 material is included with the attribution above.
- **Trademarks**: the adapted examples contain no Red Hat logos or branding; they keep only the technical identifiers
  the software requires (API groups, resource and namespace names, registry host names). Naming the source documentation
  is attribution, not a claim of endorsement.

## Examples adapted from documentation

File: lesson id / block id. "Adapted" means the example follows the structure of a documented example with the course's
own names and values; "commands" means documented command lines (short, functional) with the course's placeholders.

### OpenShift Container Platform 4.21 documentation (© Red Hat, Apache-2.0)

| Block | Source page | What was taken |
|---|---|---|
| `lessons/b1-network-releases.yaml`: o3.ingress-gateway / gateway-yaml | Ingress and load balancing: Configuring ingress cluster traffic, Gateway API, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/ingress_and_load_balancing/configuring-ingress-cluster-traffic | GatewayClass and Gateway manifests; Gateway name and host name changed |
| `lessons/b1-network-releases.yaml`: o3.support-data / must-gather-example, sos-yaml | Support: Gathering data about your cluster, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/support/gathering-cluster-data | commands; archive name simplified |
| `lessons/b2-images-storage.yaml`: ct.openshift-images / allowed-example, mirror-set-example | Images: Image configuration, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/images/image-configuration-classic | adapted Image and ImageDigestMirrorSet; registries, names and fields changed or left out |
| `lessons/b3-identity-access.yaml`: n.htpasswd-users / retire-example | Authentication and authorization: Understanding identity provider configuration (Removing the kubeadmin user), https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/understanding-identity-provider | the deletion command; the checks before it are the course's |
| `lessons/b3-identity-access.yaml`: o2.groups / sync-example; `lessons/b7b-enterprise.yaml`: p.ldap-oidc / preview-sync and the section ldap-sync-config-reference | Authentication and authorization: Syncing LDAP groups, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/ldap-syncing | commands; adapted LDAPSyncConfig with the course's directory names |
| `lessons/b7b-enterprise.yaml`: p.ldap-oidc / ldap-provider-example, oidc-provider-example | Authentication and authorization: Configuring identity providers, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/configuring-identity-providers | adapted provider entries; names, URLs and claims changed |
| `lessons/b4-ingress.yaml`: n.ingress-sharding / default-exclusion | Ingress and load balancing: Configuring ingress cluster traffic (route sharding), same address as gateway-yaml | adapted routeSelector excerpt |
| `lessons/b4-ingress.yaml`: n.loadbalancer-services / metallb-example | Ingress and load balancing: Load balancing with MetalLB, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/ingress_and_load_balancing/load-balancing-with-metallb | adapted IPAddressPool and L2Advertisement; names and addresses changed |
| `lessons/b5-operators-maintenance.yaml`: c.olm / own-scope; n.operators-lifecycle / global-dedicated | Operators: Understanding Operators (Operator groups), https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/operators/understanding-operators | adapted OperatorGroup manifests |
| `lessons/b5-operators-maintenance.yaml`: c.olm / manual-request; n.operators-lifecycle / subscription, read-and-approve, change-channel | Operators: Administrator tasks, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/operators/administrator-tasks | adapted Subscription; commands with the course's names |
| `lessons/b5-operators-maintenance.yaml`: c.olm / install-chain-example | Security and compliance: cert-manager Operator for Red Hat OpenShift (installing by using the CLI), https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/security_and_compliance/cert-manager-operator-for-red-hat-openshift | command sequence, shortened, with comments |
| `lessons/b6-platform-ops.yaml`: n.nodes-capacity / maintenance-example | Nodes: Working with nodes, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/nodes/working-with-nodes (and Kubernetes: Safely drain a node, below) | commands |
| `lessons/b6-platform-ops.yaml`: p.cluster-partitioning / durable-template, router-placement | Machine management: Creating infrastructure machine sets, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/machine_management/creating-infrastructure-machinesets | adapted excerpts; labels, taints and values changed |
| `lessons/b6-platform-ops.yaml`: p.cluster-partitioning / project-selector | Nodes: Controlling pod placement onto nodes, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/nodes/controlling-pod-placement-onto-nodes-scheduling | adapted Namespace annotations |
| `lessons/b6-platform-ops.yaml`: p.cluster-partitioning / pool-example | Machine configuration: Machine configuration overview, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/machine_configuration/machine-config-index | adapted custom MachineConfigPool |
| `lessons/b7a-delivery-governance.yaml`: g.iac / diff-example; n.cicd / logs-example (with Tekton, below) | CLI tools: OpenShift CLI, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/cli_tools/openshift-cli-oc | commands |
| `lessons/b7a-delivery-governance.yaml`: n.supply-chain / inspect-policy | Nodes: Manage secure signatures with sigstore, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/nodes/nodes-sigstore-using | commands |
| `lessons/b7a-delivery-governance.yaml`: f.secrets-supplychain / encryption-setting | etcd: Enabling etcd encryption, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/etcd/etcd-encrypt | configuration excerpt |
| `lessons/b7a-delivery-governance.yaml`: f.secrets-supplychain / access-examples | Authentication and authorization: Using RBAC, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/using-rbac | commands |
| `lessons/b7a-delivery-governance.yaml`: f.secrets-supplychain / projection-example | Authentication and authorization: Using bound service account tokens, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/bound-service-account-tokens (and Kubernetes, below) | adapted volume excerpt |
| `lessons/b7a-delivery-governance.yaml`: f.secrets-supplychain / audit-config | Security and compliance: Configuring the audit log policy, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/security_and_compliance/audit-log-policy-config | configuration excerpt |
| `lessons/b7b-enterprise.yaml`: e.stateful-dr / backup-selection | Backup and restore: OADP application backup and restore, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/backup_and_restore/oadp-application-backup-and-restore (and Velero, below) | Backup written for the course from the documented fields |
| `lessons/b7b-enterprise.yaml`: i.day2-backup / documented-backup | Backup and restore: Control plane backup and restore, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/backup_and_restore/control-plane-backup-and-restore | commands |
| `lessons/b7b-enterprise.yaml`: i.day2-backup / inspect-version | Updating clusters, https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html-single/updating_clusters/index | command |
| `lessons/b7b-enterprise.yaml`: i.platform-team / onboarding-contract | Building applications: Projects (project creation), https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/building_applications/projects (and the CNCF white paper, below) | the course's own text; ideas only |

### Other Red Hat documentation (© Red Hat, CC BY-SA 3.0; adaptations here under CC BY-SA 4.0)

| Block | Source page | What was taken |
|---|---|---|
| `lessons/b6-platform-ops.yaml`: n.monitoring / enable-user-monitoring | Monitoring stack for Red Hat OpenShift 4.21: Preparing to configure the monitoring stack (user workload monitoring), https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.21/html/configuring_user_workload_monitoring/preparing-to-configure-the-monitoring-stack-uwm | the enabling ConfigMap (the only form the setting takes) |
| `lessons/b6-platform-ops.yaml`: n.monitoring / monitor-pair | Monitoring stack for Red Hat OpenShift 4.21: Configuring metrics for user workload monitoring, https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.21/html/configuring_user_workload_monitoring/configuring-metrics-uwm | adapted Service and ServiceMonitor; names, ports and fields changed |
| `lessons/b6-platform-ops.yaml`: n.monitoring / inspect-monitor | Monitoring stack for Red Hat OpenShift 4.21: Troubleshooting monitoring issues, https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.21/html/troubleshooting_monitoring_issues/index | commands |
| `lessons/b6-platform-ops.yaml`: n.logging / forwarder-shape | Red Hat OpenShift Logging 6.6: Setting up log forwarding, https://docs.redhat.com/en/documentation/red_hat_openshift_logging/6.6/html/configure/set-up-log-forwarding | adapted ClusterLogForwarder excerpt; names changed, outputs left out |
| `lessons/b6-platform-ops.yaml`: n.logging / inspect-forwarder | Red Hat OpenShift Logging 6.6: Troubleshoot, https://docs.redhat.com/en/documentation/red_hat_openshift_logging/6.6/html/troubleshoot/index | command |
| `lessons/b7a-delivery-governance.yaml`: n.cicd / pipeline-example | Red Hat OpenShift Pipelines 1.21: Creating CI/CD solutions for applications, https://docs.redhat.com/en/documentation/red_hat_openshift_pipelines/1.21/html/creating_cicd_pipelines/creating-applications-with-cicd-pipelines | the task ordering idea (runAfter); a much shorter Pipeline written for the course |
| `lessons/b7a-delivery-governance.yaml`: n.policy-governance / inform-example; `lessons/b7b-enterprise.yaml`: i.multicluster / policy-read-example | Red Hat Advanced Cluster Management for Kubernetes 2.16: Governance, https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/2.16/html-single/governance/index | partial ConfigurationPolicy with the course's names; commands |

### Kubernetes documentation (© The Kubernetes Authors, CC BY 4.0)

| Block | Source page | What was taken |
|---|---|---|
| `lessons/b5-operators-maintenance.yaml`: c.machineconfig-upgrades / blocked-budget; `lessons/b7b-enterprise.yaml`: i.ha-architecture / budget-example | Disruptions, https://kubernetes.io/docs/concepts/workloads/pods/disruptions/ | adapted PodDisruptionBudget; names and values changed |
| `lessons/b5-operators-maintenance.yaml`: o2.kustomize-helm / generator | Declarative management of Kubernetes objects using Kustomize, https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/ | adapted configMapGenerator fragment |
| `lessons/b6-platform-ops.yaml`: b.scheduler / affinity-example | Assigning Pods to Nodes, https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/ | adapted Pod spec excerpt |
| `lessons/b6-platform-ops.yaml`: b.scheduler / spread-example; `lessons/b7b-enterprise.yaml`: i.ha-architecture / spread-example | Pod Topology Spread Constraints, https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/ | adapted constraint fragment |
| `lessons/b6-platform-ops.yaml`: n.nodes-capacity / maintenance-example | Safely Drain a Node, https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/ | commands |
| `lessons/b7a-delivery-governance.yaml`: n.policy-governance / owner-policy, owner-binding (files used in the lesson) | Validating Admission Policy, https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/ | adapted policy and binding; match rules, expression, message and actions changed |
| `lessons/b7a-delivery-governance.yaml`: n.policy-governance / webhook-failure-setting | Dynamic Admission Control, https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/ | adapted webhook rule excerpt |
| `lessons/b7a-delivery-governance.yaml`: f.secrets-supplychain / projection-example | Managing Service Accounts (bound tokens), https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/ | adapted projected volume excerpt |

### Other projects

| Block | Source page | Licence | What was taken |
|---|---|---|---|
| `lessons/b7a-delivery-governance.yaml`: n.cicd / task-example, logs-example | Tekton: Tasks, https://tekton.dev/docs/pipelines/tasks/ and TaskRuns, https://tekton.dev/docs/pipelines/taskruns/ (© The Tekton Authors) | CC BY 4.0 (text), Apache-2.0 (code samples) | Task written for the course from the documented fields; commands |
| `lessons/b7b-enterprise.yaml`: e.stateful-dr / backup-selection, mapped-restore | Velero 1.16: Backup API type, https://velero.io/docs/v1.16/api-types/backup/, Restore API type, https://velero.io/docs/v1.16/api-types/restore/ (© Velero Authors) | Apache-2.0 | Backup and Restore written for the course from the documented fields |
| `lessons/b7b-enterprise.yaml`: i.platform-team / onboarding-contract | CNCF TAG App Delivery: Platforms white paper, https://tag-app-delivery.cncf.io/whitepapers/platforms/ (© The CNCF Authors) | CC BY 4.0 | ideas only; the text is the course's |

## Cited, not adapted

These captions name a source for the facts they rely on; the blocks were written for the course and copy no text:
Terraform `plan` (`g.iac / plan-example`, a single command), the Ansible `creates` option (`g.iac / guard-example`),
Cosign verification (`n.supply-chain / verify-example`, a single command), the burn-rate arithmetic from the Google SRE
workbook's alerting example (`h.slo-incidents / burn-example`, numbers and a formula), and the ServiceMonitor in
`b.crds-operators / example`.

## Text printed by programs in the recordings

`content/recordings/` contains the output of the commands the lessons ran. Apart from data about the test cluster, some
of that output is text written into the programs themselves:

- `oc explain` and `kubectl explain` descriptions come from the API type definitions in kubernetes/api (© The
  Kubernetes Authors), openshift/api (© Red Hat), operator-framework/api and prometheus-operator, all Apache-2.0.
- `oc ... --help` excerpts come from openshift/oc (Apache-2.0).
- Operator catalog data (`oc get packagemanifest`, for example channel names, CRD names and the cert-manager Operator's
  uninstall message) comes from the operator bundles, for example openshift/cert-manager-operator (Apache-2.0).
- `cat --help` prints the help text of GNU coreutils (© Free Software Foundation, GPL-3.0-or-later), quoted in full as
  an example of a help page.

Those passages keep their owners' copyright and licences; see `content/LICENSE.md`.
