output "aws_region" {
  value = var.aws_region
}
output "ci_instance_id" {
  value = data.aws_instance.ci.id
}
output "ci_public_ip" {
  description = "Reported existing EC2 public IP (may be empty while stopped). Terraform does not allocate one."
  value       = data.aws_instance.ci.public_ip
}
output "ci_instance_profile" {
  description = "Existing instructor-managed instance profile."
  value       = data.aws_instance.ci.iam_instance_profile
}
output "frontend_ecr_url" {
  value = data.aws_ecr_repository.frontend.repository_url
}
output "backend_ecr_url" {
  value = data.aws_ecr_repository.backend.repository_url
}
output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}
output "discord_queue_url" {
  value = aws_sqs_queue.discord.id
}
output "discord_dlq_url" {
  value = aws_sqs_queue.discord_dlq.id
}
output "discord_secret_names" {
  value = { for channel, secret in aws_secretsmanager_secret.discord : channel => secret.name }
}
output "rds_endpoint" {
  value = var.enable_database ? aws_db_instance.postgres[0].endpoint : "Database not enabled"
}
output "app_url" {
  value = var.enable_application ? (local.enable_https ? "https://<your-app-domain>" : "http://${aws_lb.app[0].dns_name}") : "Application not enabled"
}
output "ecs_service_name" {
  value = var.enable_application ? aws_ecs_service.app[0].name : "Application not enabled"
}

output "blue_green_production_rule_arn" {
  description = "ALB production listener rule managed by ECS native blue/green."
  value       = var.enable_application ? aws_lb_listener_rule.production[0].arn : "Application not enabled"
}

output "deployment_strategy" {
  value = var.enable_application ? "ECS_BLUE_GREEN" : "Application not enabled"
}
