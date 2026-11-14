variable "aws_region" {
  type    = string
  default = "eu-west-1"
}
variable "project_name" {
  type    = string
  default = "slice-sip"
}
variable "existing_ci_instance_id" {
  type = string
  validation {
    condition     = can(regex("^i-[0-9a-f]{8,17}$", var.existing_ci_instance_id))
    error_message = "Supply existing EC2 ID."
  }
}
variable "existing_vpc_id" {
  type = string
}
variable "alb_public_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.alb_public_subnet_ids) == 2 && length(distinct(var.alb_public_subnet_ids)) == 2
    error_message = "Two distinct ALB subnet IDs are required."
  }
}
variable "ecs_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.ecs_subnet_ids) >= 2 && length(distinct(var.ecs_subnet_ids)) == length(var.ecs_subnet_ids)
    error_message = "Supply at least two distinct ECS subnet IDs."
  }
}
variable "ecs_assign_public_ip" {
  type        = bool
  default     = false
  description = "False for private NAT-enabled subnets; true ONLY for approved public subnets."
}
variable "enable_application" {
  type        = bool
  default     = false
  description = "False before first CI build. Host deployer overrides to true on initial build."
}
variable "image_tag" {
  type    = string
  default = ""
  validation {
    condition     = var.image_tag == "" || can(regex("^[0-9a-f]{40}-[1-9][0-9]*$", var.image_tag))
    error_message = "Tag must be full commit SHA plus -pipelineNumber."
  }
}
variable "existing_ecs_execution_role_arn" {
  type        = string
  default     = "arn:aws:iam::597765856364:role/ecsTaskExecutionRole"
  description = "Verified existing ECS task EXECUTION role. No iam:GetRole lookup."
}
variable "app_certificate_arn" {
  type    = string
  default = ""
}
variable "enable_discord_webhooks" {
  type        = bool
  default     = false
  description = "Only enable when execution role can read all configured Secrets Manager values."
}
variable "discord_webhook_secret_arns" {
  type      = map(string)
  default   = {}
  sensitive = true
  validation {
    condition     = alltrue([for a in values(var.discord_webhook_secret_arns) : can(regex("^arn:aws:secretsmanager:eu-west-1:[0-9]{12}:secret:", a))])
    error_message = "Secret ARNs must be existing eu-west-1 Secrets Manager ARNs."
  }
}
