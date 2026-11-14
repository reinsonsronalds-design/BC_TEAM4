# No IAM resources or IAM read data sources: reuses the known task execution
# role ARN and the approved EC2 instance profile, unchanged.
# Roleless blue/green is implemented by EC2 with its existing ecs:*
# and elasticloadbalancing:* permissions.
