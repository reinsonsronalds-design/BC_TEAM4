# TWO independent rolling ECS services; EC2 switches ALB rule after health check.
# This avoids needing an unverified ecs.amazonaws.com infrastructure role.
resource "aws_ecs_cluster" "main" {
  count = var.enable_application ? 1 : 0
  name  = "${var.project_name}-ecs"
}
resource "aws_ecs_task_definition" "app" {
  count                    = var.enable_application ? 1 : 0
  family                   = "${var.project_name}-app"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.existing_ecs_execution_role_arn
  lifecycle {
    precondition {
      condition     = trimspace(var.image_tag) != ""
      error_message = "Image tag required after successful Woodpecker Kaniko publishing."
    }
    precondition {
      condition     = !var.enable_discord_webhooks || alltrue([for c in local.discord_channels : try(trimspace(var.discord_webhook_secret_arns[c]) != "", false)])
      error_message = "All 3 Discord secret ARNs required when injection is enabled."
    }
  }
  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = "${data.aws_ecr_repository.backend.repository_url}:${var.image_tag}"
      essential = true
      command   = ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
      secrets = var.enable_discord_webhooks ? [
        for c in sort(tolist(local.discord_channels)) : {
          name      = "DISCORD_${upper(c)}_WEBHOOK_URL"
          valueFrom = var.discord_webhook_secret_arns[c]
        }
      ] : []
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = local.app_log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "backend"
        }
      }
    },
    {
      name         = "frontend"
      image        = "${data.aws_ecr_repository.frontend.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 80, protocol = "tcp" }]
      environment  = [{ name = "BACKEND_HOST", value = "127.0.0.1:8000" }]
      dependsOn    = [{ containerName = "backend", condition = "START" }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = local.app_log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])
}
resource "aws_ecs_service" "blue" {
  count                             = var.enable_application ? 1 : 0
  name                              = "${var.project_name}-blue"
  cluster                           = aws_ecs_cluster.main[0].id
  task_definition                   = aws_ecs_task_definition.app[0].arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 90
  network_configuration {
    subnets          = var.ecs_subnet_ids
    assign_public_ip = var.ecs_assign_public_ip
    security_groups  = [aws_security_group.app[0].id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.blue[0].arn
    container_name   = "frontend"
    container_port   = 80
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener_rule.production]
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
resource "aws_ecs_service" "green" {
  count                             = var.enable_application ? 1 : 0
  name                              = "${var.project_name}-green"
  cluster                           = aws_ecs_cluster.main[0].id
  task_definition                   = aws_ecs_task_definition.app[0].arn
  desired_count                     = 0
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 90
  network_configuration {
    subnets          = var.ecs_subnet_ids
    assign_public_ip = var.ecs_assign_public_ip
    security_groups  = [aws_security_group.app[0].id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.green[0].arn
    container_name   = "frontend"
    container_port   = 80
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener_rule.production]
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
