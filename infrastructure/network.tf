# Reuse the existing instructor VPC and approved subnets. No shared resource managed.
data "aws_vpc" "bootcamp" {
  id = var.existing_vpc_id
}

resource "aws_security_group" "alb" {
  count       = var.enable_application ? 1 : 0
  name_prefix = "${var.project_name}-alb-"
  description = "Slice and Sip public demo ALB"
  vpc_id      = data.aws_vpc.bootcamp.id
}
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  count             = var.enable_application ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}
resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count             = var.enable_application && local.enable_https ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "alb_egress" {
  count                        = var.enable_application ? 1 : 0
  security_group_id            = aws_security_group.alb[0].id
  referenced_security_group_id = aws_security_group.app[0].id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_security_group" "app" {
  count       = var.enable_application ? 1 : 0
  name_prefix = "${var.project_name}-app-"
  description = "Slice and Sip Fargate tasks: ALB only"
  vpc_id      = data.aws_vpc.bootcamp.id
}
resource "aws_vpc_security_group_ingress_rule" "alb_to_app" {
  count                        = var.enable_application ? 1 : 0
  security_group_id            = aws_security_group.app[0].id
  referenced_security_group_id = aws_security_group.alb[0].id
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "app_egress" {
  count             = var.enable_application ? 1 : 0
  security_group_id = aws_security_group.app[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
