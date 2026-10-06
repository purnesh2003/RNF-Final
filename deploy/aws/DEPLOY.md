# Production AWS deployment

This deployment runs the existing Flask application on ECS Fargate and keeps the database, Redis and uploads managed by AWS.

## 0. Ownership and safety

Create the production environment in the **client's AWS account**. The client should own:

- AWS root account
- production domain
- Route 53/DNS account
- GitHub repository
- production secrets
- billing

Use a developer IAM role for implementation. Do not build the client's production system under a personal AWS account.

For staging, use a separate AWS account when possible. If the client cannot provide a second account, use a separate Terraform state and resource name such as `community-staging`, with smaller capacity values.

## 1. Tools

Install locally or use AWS CloudShell:

- AWS CLI
- Terraform >= 1.5
- Docker
- Git

Authenticate with an IAM role/user that is authorized to provision the required resources. Do not put root access keys in your project.

## 2. Certificates

When CloudFront is enabled, request **two ACM public certificates**:

### ALB origin certificate

Region: `ap-south-1`.

Cover both the public and origin hostnames, for example:

```text
community.example.com
origin.community.example.com
```

After DNS validation, copy its issued certificate ARN into `certificate_arn`.

### CloudFront certificate

Region: **us-east-1**.

Cover the public hostname:

```text
community.example.com
```

After DNS validation, copy its ARN into `cloudfront_certificate_arn`.

## 3. DNS and the two-stage CloudFront deployment

CloudFront needs the origin hostname to resolve when its distribution is created. The ALB does not exist yet, so bootstrap in two stages:

1. Set `enable_cloudfront = false`.
2. Apply the ALB/ECS/database/Redis infrastructure.
3. Get `load_balancer_dns_name`.
4. Create `origin.community.example.com` as a CNAME to that ALB hostname.
5. Temporarily point the public hostname to the ALB if you want to test the application before CloudFront.
6. Confirm the origin DNS name resolves and the ALB certificate covers both hostnames.
7. Set `enable_cloudfront = true` and apply again.
8. Get `cloudfront_domain_name` and point the public hostname to CloudFront.

If your registrar supports Route 53 aliases, you can use Route 53 for the final public alias. Otherwise use the registrar's CNAME/ALIAS/ANAME feature as supported by that provider.

## 4. Configure Terraform

```bash
cd deploy/aws
cp terraform.tfvars.example terraform.tfvars
```

Fill in:

```hcl
region                   = "ap-south-1"
domain_name              = "community.example.com"
certificate_arn          = "ALB_ORIGIN_CERTIFICATE_ARN"
cloudfront_certificate_arn = "CLOUDFRONT_US_EAST_1_CERTIFICATE_ARN"
cloudfront_origin_domain = "origin.community.example.com"
admin_email              = "admin@example.com"
admin_password           = ""
whatsapp_link             = "https://chat.whatsapp.com/..."
```

Leaving `admin_password` empty makes Terraform generate a random bootstrap password. Retrieve it after apply:

```bash
terraform output -raw bootstrap_admin_password
```

Change that password immediately after the first login.

## 5. Validate before spending money

```bash
terraform fmt -recursive
terraform init
terraform validate
terraform plan
```

Review every resource in the plan. Do not run `apply` if the plan contains resources you do not recognize.

## 6. Build and push the first image

Create the ECR repository first:

```bash
terraform apply -target=aws_ecr_repository.app
```

Then:

```bash
cd ../..
REPO=$(terraform -chdir=deploy/aws output -raw ecr_repository_url)
REGISTRY=${REPO%%/*}
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin "$REGISTRY"
docker build -t "$REPO:latest" .
docker push "$REPO:latest"
```

## 7. Create the infrastructure

```bash
cd deploy/aws
terraform apply
```

The first creation can take several minutes because Aurora, ECS, Redis, WAF and CloudFront are managed resources.

The application startup command now runs:

```text
flask db upgrade
flask ensure-admin
gunicorn ...
```

This means schema changes use migrations instead of `db.create_all()` in production.

## 8. Finish DNS

After Terraform completes, get the CloudFront hostname:

```bash
terraform output cloudfront_domain_name
```

Set the public DNS record for `community.example.com` to that CloudFront hostname.

Get the ALB hostname:

```bash
terraform output load_balancer_dns_name
```

Set the origin hostname (`origin.community.example.com`) to the ALB hostname.

Allow DNS and certificate validation to settle, then test:

```text
https://community.example.com
```

## 9. First login

Get the bootstrap password if Terraform generated it:

```bash
terraform output -raw bootstrap_admin_password
```

Log in with the configured admin email. The bootstrap admin is marked to require a password change. Change it immediately.

Do not send the bootstrap password through WhatsApp/email group chats.

## 10. Staging first

Before changing production, create a staging environment with a different `name`, for example:

```hcl
name            = "community-staging"
min_tasks       = 1
max_tasks       = 2
db_instance_count = 1
redis_nodes     = 1
protect_data    = false
```

Run migrations, functional tests, chat tests, upload tests and a basic load test in staging first.

## 11. CI/CD

GitHub Actions are supplied in `.github/workflows`.

Configure a GitHub **production environment** with:

Secret:

```text
AWS_ROLE_ARN
```

Variables:

```text
AWS_REGION
ECR_REPOSITORY
ECS_CLUSTER
ECS_SERVICE
```

Use AWS IAM OIDC trust for GitHub instead of long-lived AWS access keys.

The deployment workflow:

1. installs dependencies
2. runs compile checks
3. runs pytest
4. builds Docker
5. pushes the commit image and `latest`
6. triggers ECS deployment
7. waits for the ECS service to become stable

## 12. Terraform state

For a real client project, do not keep the only Terraform state file on a laptop.

Use an encrypted, access-controlled remote S3 backend with state locking. Keep the backend bucket separate from the application bucket and restrict access to the infrastructure team.

The current repository intentionally does not contain a backend bucket because that bucket must be bootstrapped once in the client's AWS account.

## 13. Backups and recovery

### Aurora

- Automated backups are enabled.
- Default retention is 7 days.
- Production uses two Aurora instances by default.
- Test an actual restore before launch.

### S3

- Public access is blocked.
- Server-side encryption is enabled.
- Versioning is enabled.
- Incomplete multipart uploads are automatically cleaned up.
- Old non-current versions expire after 90 days.

### Redis

Redis is used as a shared cache/fan-out layer, not as the source of truth. If Redis is lost, persistent application data remains in PostgreSQL.

## 14. Monitoring

CloudWatch receives ECS application logs and the application publishes the live chat connection metric used for autoscaling.

Terraform also creates alarms for:

- ALB target 5xx errors
- unhealthy ECS targets
- sustained ECS CPU utilization

Connect these alarms to an SNS/on-call notification path before the client launch.

## 15. Security review before launch

- [ ] Root MFA enabled
- [ ] No root access keys
- [ ] IAM least privilege
- [ ] Secrets Manager used for runtime secrets
- [ ] Terraform state protected
- [ ] HTTPS only
- [ ] WAF enabled
- [ ] S3 public access blocked
- [ ] Database private
- [ ] Redis private
- [ ] Admin password changed
- [ ] CI green
- [ ] Dependency audit green
- [ ] Staging tested
- [ ] Backup restore tested
- [ ] Load test completed
- [ ] Monitoring notifications tested

## 16. Updating the application

Normal updates should go through GitHub Actions. Do not SSH into ECS containers and edit application files.

For an emergency manual deployment, push a new image and force a new ECS deployment. Keep the source code in Git as the authoritative version.
