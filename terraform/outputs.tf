output "app_name" {
  value = juju_application.resource_dispatcher.name
}

output "provides" {
  value = {
    pod_defaults     = "pod-defaults",
    provide_cmr_mesh = "provide-cmr-mesh",
    secrets          = "secrets",
    service_accounts = "service-accounts",
    roles            = "roles",
    role_bindings    = "role-bindings",
  }
}

output "requires" {
  value = {
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh",
  }
}
