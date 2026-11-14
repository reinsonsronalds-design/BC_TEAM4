output "ci_instance_id" {
  value = data.aws_instance.ci.id
}
output "frontend_ecr_url" {
  value = data.aws_ecr_repository.frontend.repository_url
}
output "backend_ecr_url" {
  value = data.aws_ecr_repository.backend.repository_url
}
output "ecs_cluster_name" {
  value = var.enable_application ? aws_ecs_cluster.main[0].name : "Not deployed"
}
output "app_url" {
  value = var.enable_application ? "http://${aws_lb.app[0].dns_name}" : "Not deployed"
}
output "blue_service_name" {
  value = var.enable_application ? aws_ecs_service.blue[0].name : "Not deployed"
}
output "green_service_name" {
  value = var.enable_application ? aws_ecs_service.green[0].name : "Not deployed"
}
output "production_listener_rule_arn" {
  value = var.enable_application ? aws_lb_listener_rule.production[0].arn : "Not deployed"
}
output "deployment_strategy" {
  value = "EC2-orchestrated dual-service blue/green"
}
