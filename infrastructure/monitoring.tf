# CloudWatch alarms bonus; no retention API, SQS, EventBridge, RDS, or worker.
resource "aws_cloudwatch_metric_alarm" "ci_cpu" {
  count               = var.enable_application ? 1 : 0
  alarm_name          = "${var.project_name}-ci-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Bootcamp CI EC2 CPU above 80%"
  treat_missing_data  = "notBreaching"
  dimensions          = { InstanceId = data.aws_instance.ci.id }
}
resource "aws_cloudwatch_metric_alarm" "alb_unhealthy" {
  count               = var.enable_application ? 1 : 0
  alarm_name          = "${var.project_name}-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 2
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.app[0].arn_suffix
  }
}


# Application-generated HTTP 5xx responses.
resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  count               = var.enable_application ? 1 : 0
  alarm_name          = "${var.project_name}-app-5xx"
  alarm_description   = "Application returned more than 2 HTTP 5xx responses per minute"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 2
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.app[0].arn_suffix
  }
}

# Monitor both ECS blue/green services.
resource "aws_cloudwatch_metric_alarm" "ecs_memory" {
  for_each            = var.enable_application ? toset(["blue", "green"]) : toset([])
  alarm_name          = "${var.project_name}-ecs-${each.key}-high-memory"
  alarm_description   = "ECS ${each.key} service memory above 80%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"
  dimensions = {
    ClusterName = aws_ecs_cluster.main[0].name
    ServiceName = each.key == "blue" ? aws_ecs_service.blue[0].name : aws_ecs_service.green[0].name
  }
}
