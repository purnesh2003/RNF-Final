variable "region" {
  description = "AWS region. ap-south-1 = Mumbai."
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Short name used to label everything."
  type        = string
  default     = "community"
}

variable "domain_name" {
  description = "Your site address, e.g. community.yourdomain.com (no https://)."
  type        = string
}

variable "certificate_arn" {
  description = "ARN of an ISSUED ACM certificate for the ALB origin hostname, created in the SAME region as above."
  type        = string
}

variable "admin_email" {
  description = "Email of the first admin account."
  type        = string
}

variable "admin_password" {
  description = "Optional bootstrap password. Leave empty to let Terraform generate a random password; retrieve it from the sensitive output and change it after first login."
  type        = string
  sensitive   = true
}

variable "whatsapp_link" {
  description = "Your WhatsApp community invite link."
  type        = string
  default     = "https://chat.whatsapp.com/your-community-invite-code"
}

variable "image_tag" {
  description = "Tag of the Docker image you pushed to ECR."
  type        = string
  default     = "latest"
}

variable "min_tasks" {
  description = "Fewest app servers ever running (2 keeps the site up if one fails)."
  type        = number
  default     = 2
}

variable "max_tasks" {
  description = "Most app servers auto scaling may add. 20 servers x ~1500 connections = ~30,000 live chatters."
  type        = number
  default     = 20
}

variable "task_cpu" {
  description = "CPU units per server (1024 = 1 vCPU)."
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory per server in MB."
  type        = number
  default     = 2048
}

variable "target_connections_per_task" {
  description = "Add a server when the average live chat connections per server goes above this."
  type        = number
  default     = 1500
}

variable "db_min_acu" {
  description = "Smallest database size (Aurora capacity units). 0.5 is the minimum."
  type        = number
  default     = 0.5
}

variable "db_max_acu" {
  description = "Largest size the database may scale to."
  type        = number
  default     = 8
}

variable "redis_node_type" {
  description = "Size of the Redis node that relays chat between servers."
  type        = string
  default     = "cache.t4g.small"
}

variable "protect_data" {
  description = "true = database cannot be deleted by accident and a final backup is kept. Set false only to tear down a test setup."
  type        = bool
  default     = true
}


variable "db_instance_count" {
  description = "Aurora instances. Use 2 for production failover; 1 for lower-cost staging."
  type        = number
  default     = 2
}

variable "redis_nodes" {
  description = "Redis nodes. Use 2 for production automatic failover; 1 for lower-cost staging."
  type        = number
  default     = 2
}

variable "ecr_force_delete" {
  description = "Allow Terraform to delete an ECR repository containing images. Keep false for production."
  type        = bool
  default     = false
}

variable "enable_cloudfront" {
  description = "Put CloudFront in front of the ALB. Recommended for production."
  type        = bool
  default     = false
}

variable "cloudfront_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 for CloudFront. Must cover domain_name."
  type        = string
  default     = ""
}


variable "cloudfront_origin_domain" {
  description = "DNS name that resolves to the ALB and is covered by the ALB ACM certificate, e.g. origin.community.example.com."
  type        = string
  default     = ""
}


variable "alert_email" {
  description = "Optional email address for CloudWatch alarm notifications. SNS requires confirmation from the recipient."
  type        = string
  default     = ""
}
