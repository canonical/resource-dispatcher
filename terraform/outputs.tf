output "app_name" {
  value = juju_application.resource_dispatcher.name
}

output "provides" {
  value = {
    secrets          = "secrets",
    service_accounts = "service-accounts",
    pod_defaults     = "pod-defaults",
  }
}

output "requires" {
  value = {}
}
