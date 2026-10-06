output "ecr_repository_url" {
  description = "Push your Docker image here."
  value       = aws_ecr_repository.app.repository_url
}

output "load_balancer_dns_name" {
  description = "Point your domain (CNAME, or an alias record in Route 53) at this address."
  value       = aws_lb.app.dns_name
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service" {
  value = aws_ecs_service.web.name
}


output "cloudfront_domain_name" {
  description = "CloudFront hostname to use as the DNS target when CloudFront is enabled."
  value       = try(aws_cloudfront_distribution.app[0].domain_name, null)
}

output "database_endpoint" {
  description = "Aurora writer endpoint."
  value       = aws_rds_cluster.db.endpoint
}

output "redis_endpoint" {
  description = "Redis primary endpoint."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}


output "bootstrap_admin_password" {
  description = "Generated first-admin password when admin_password was left empty. Change it after first login."
  sensitive   = true
  value       = var.admin_password != "" ? var.admin_password : random_password.admin.result
}


output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
