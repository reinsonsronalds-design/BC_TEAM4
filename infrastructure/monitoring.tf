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
  statistic           = "Maximum"
  threshold           = 2
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.app[0].arn_suffix
  }
}
