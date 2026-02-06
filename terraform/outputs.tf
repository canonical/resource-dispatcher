output "app_name" {
  value = juju_application.resource_dispatcher.name
}

output "provides" {
  value = {
    secrets          = "secrets",
    service_accounts = "service-accounts",
    pod_defaults     = "pod-defaults",
    provide_cmr_mesh  = "provide-cmr-mesh",
    roles            = "roles",
    role_bindings    = "role-bindings",
  }
}

output "requires" {
  value = {
    service_mesh     = "service-mesh",
    require_cmr_mesh = "require-cmr-mesh",
  }
}
