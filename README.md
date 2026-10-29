# Rakshith Community — Python + AWS

A full-stack community platform built with **Python/Flask**, PostgreSQL, Redis, WebSockets and private S3 storage. It includes member accounts, real-time chat, file/photo sharing, opinions, quizzes, polls and an admin dashboard.

## What is already implemented

- User registration (name, email, date of birth, occupation), login, logout and password change
- Sign-up needs a Gmail address and is activated only after the member clicks the confirmation link e-mailed to them (fake addresses never get an account)
- Password rule: at least 12 characters with a letter, a number and a special character
- Working "Forgot password" e-mail (Gmail SMTP App Password, any SMTP server, or Amazon SES)
- Community split into 4 rooms (NISM, Investors, Traders, General); MP4 videos play inline (max 50 MB), photos/PDFs/Office files max 15 MB
- 📁 Documents library: every photo, video, PDF and file uploaded by the admin or members in one filterable place
- Strong password hashing; plaintext passwords are never stored
- Session protection and CSRF protection
- Admin user management, moderation and CSV export
- Real-time community chat using Socket.IO/WebSockets
- Redis fan-out so multiple app containers share chat
- Chat history and reconnect catch-up
- Polls with one vote per user enforced by a database constraint
- Quizzes with one attempt per user enforced by a database constraint
- AI quiz generator (Google Gemini): admin enters topic, number of questions and difficulty, reviews/edits the draft, then publishes. Every question is validated server-side; a Gemini failure never creates a quiz and existing quizzes are unaffected. Members are e-mailed once when a quiz is published. Put `GEMINI_API_KEY=...` in `.env` (see `.env.example`), then `docker compose up -d --build`.
- Public SIP calculator at `/sip-calculator` (no login; floating button on every page except the chat). When the admin posts in the feed or writes/shares a file in the community, every other active member gets a personal e-mail (`ADMIN_POST_EMAILS=0` turns it off). All member e-mails go out one per person ("Hi <name>"), never as a BCC batch.
- Fully self-contained front end: fonts, Bootstrap and the chat library are bundled in app/static (nothing loads from Google or a CDN)
- Professional design system: serif headlines, SVG icons, consistent cards, responsive on phones; research-desk cards on the home page
- Instagram-style home-page feed: admin posts news, information and updates with a photo/video or document, pinning, and member likes
- Admin hamburger menu (side panel) with every admin control, and member list export to Excel (.xlsx) or CSV
- Private S3 uploads with presigned browser uploads
- Upload size, extension and content-signature validation
- WhatsApp community link
- Docker and Docker Compose
- Terraform for AWS ECS Fargate, Aurora PostgreSQL, ElastiCache Redis, S3, ECR, WAF, CloudFront and CloudWatch
- Flask-Migrate/Alembic database migrations
- CI tests and dependency vulnerability auditing
- GitHub Actions deployment workflow

## Email setup (password reset)

1. Use a Gmail account: turn on 2-Step Verification, then create an **App Password** at https://myaccount.google.com/apppasswords.
2. In `.env` set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD` (the 16-letter app password) and `MAIL_FROM`.
3. Leave `PUBLIC_BASE_URL` blank (links use the address people visit) or set it to your real domain.
4. `docker compose up -d --build`. Other e-mail domains: add them to `EMAIL_ALLOWED_DOMAINS` (comma separated, `*` = any).

## Architecture

```text
Users
  |
  v
CloudFront (HTTPS/CDN)
  |
  v
AWS WAF
  |
  v
Application Load Balancer (HTTPS)
  |
  +-----------------------------+
  |                             |
v v                             v
ECS Fargate task 1       ECS Fargate task N
Python Flask + Socket.IO + Gunicorn
  |          |                    |
  |          +--------------------+
  |                    |
  +----------+---------+
             |
       +-----+------+----------------+
       |            |                |
       v            v                v
Aurora PostgreSQL  Redis            S3
users/posts/etc.   chat/rate limit  private files
       |
       v
CloudWatch / alarms

Cognito is not required for this version: authentication is implemented by the Flask application and PostgreSQL.
```

### Why this architecture

The uploaded project is already a Python/Flask application. Keeping Flask + PostgreSQL + Redis avoids throwing away working features and lets the system scale horizontally by adding identical ECS tasks.

The number of registered users is not the main scaling number. **Concurrent users, WebSocket connections, requests, database workload, file traffic and bandwidth** determine capacity and cost. Load testing is required before promising a specific peak.

## Local development

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env
```

Set a strong local `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` and WhatsApp link. Then:

```bash
export FLASK_APP=wsgi.py
flask db upgrade
flask ensure-admin
python wsgi.py
```

Windows PowerShell:

```powershell
$env:FLASK_APP="wsgi.py"
flask db upgrade
flask ensure-admin
python wsgi.py
```

Open `http://localhost:8000`.

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

This starts PostgreSQL, Redis, two Flask containers and nginx so cross-container WebSocket behaviour can be tested locally.

## Database changes

**Do not use `db.create_all()` as a production migration mechanism.**

Use:

```bash
flask db upgrade
```

When the schema changes:

```bash
flask db migrate -m "describe the schema change"
flask db upgrade
```

Review generated migrations before committing them. The baseline migration creates the current schema on a fresh database and safely does nothing when an existing baseline schema is already present.

## AWS production

Terraform is under `deploy/aws`.

The production design uses:

- VPC across two Availability Zones
- Public ALB and private database/Redis subnets
- ECS Fargate with 2–20 tasks and CPU/chat-connection autoscaling
- Aurora PostgreSQL Serverless v2 with two instances by default
- ElastiCache Redis replication group with automatic failover by default
- Private, encrypted, versioned S3 bucket
- ECR for container images
- Secrets Manager for application secrets
- WAF managed rules + rate limiting
- CloudFront with dynamic-content caching disabled and WebSocket support
- CloudWatch logs and operational alarms
- IAM least-privilege task permissions

Follow `deploy/aws/DEPLOY.md` exactly. Do not deploy to production before running `terraform fmt`, `terraform validate`, `terraform plan`, CI tests and a staging deployment.

### Certificates and DNS

Two certificates are used when CloudFront is enabled:

1. **ALB origin certificate:** in `ap-south-1`, covering the origin hostname such as `origin.community.example.com`.
2. **CloudFront certificate:** in `us-east-1`, covering the public hostname such as `community.example.com`.

DNS should resolve the origin hostname to the ALB and the public hostname to CloudFront.

## CI/CD

GitHub Actions are provided:

- `.github/workflows/ci.yml` — compile, pytest and `pip-audit`
- `.github/workflows/deploy.yml` — build/push the Docker image and wait for ECS deployment stability

For deployment, use GitHub OIDC and an AWS IAM role rather than storing long-lived AWS access keys in GitHub.

Required GitHub environment values:

- `AWS_ROLE_ARN` secret
- `AWS_REGION` variable
- `ECR_REPOSITORY` variable
- `ECS_CLUSTER` variable
- `ECS_SERVICE` variable

## Security checklist before launch

- [ ] Client owns the AWS production account
- [ ] Root account has MFA and is not used for daily work
- [ ] Developer uses an IAM role with least privilege
- [ ] Terraform state is stored remotely in an encrypted, access-controlled backend
- [ ] Production secrets are in Secrets Manager, not Git
- [ ] Admin uses a unique strong password and changes the bootstrap password immediately
- [ ] HTTPS is enforced
- [ ] WAF is enabled
- [ ] S3 public access is blocked
- [ ] Database and Redis are in private subnets
- [ ] Database backups are enabled and a restore has been tested
- [ ] CI passes
- [ ] Dependency audit passes
- [ ] Staging has been tested before production
- [ ] Load test has been run at the expected peak
- [ ] CloudWatch alarms are connected to an operational notification path

## Scope

The current application includes the community platform features. Finance/news/market-data pages are not part of the core platform and should be added as separate modules if required.

## Invite friends, publish later
- **Invite friends** (user menu > Invite friends): each member gets a personal link; the page counts friends who signed up with it and confirmed their email.
- **Publish later**: the admin "Create a post" and "Create quiz" forms have an optional date/time (`SCHEDULE_TZ`, default Asia/Kolkata). The item is hidden from members until then; members are e-mailed at that time. Manage it under Admin menu > Scheduled posts & quizzes (publish now / cancel). A small background thread started in `wsgi.py` does the publishing (turn off with `SCHEDULER_ENABLED=0`).
- Needs `flask db upgrade` (migration 0010).

## Market updates (pre-market / post-market)
Two buttons above the community chat show the latest **Pre-market update** and **Post-market update**. The admin writes them by hand
(Admin menu > Market updates: pick the update and day, type the text, publish; Edit / Delete below). No AI or API key is involved.
Members only read the saved text. Uses the `market_updates` table (migration 0011).
