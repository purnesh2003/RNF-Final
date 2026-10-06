# Deploy on ONE AWS server (Lightsail) — about 30 minutes

This is a **staging/small-community option**, not the preferred architecture for the 5,000–20,000 user target. For the client production environment use `deploy/aws`.

## 1. Create the server
1. AWS Console → **Lightsail** → Create instance → Linux → **Ubuntu 22.04** → plan with **2 GB RAM** (or larger).
2. Networking tab → **Create static IP** and attach it. Firewall: allow **HTTP 80** and **HTTPS 443** (SSH 22 is already there).

## 2. Point your domain at it
At your domain registrar (or Route 53) add an **A record**: `community.yourdomain.com` → the static IP.
Wait a few minutes. (HTTPS certificates need this to work first.)

## 3. Install Docker on the server (use Lightsail's browser SSH button)
```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

## 4. Upload the project
On your PC, zip the project folder (skip `.venv` and `.env`) and upload it via Lightsail's SSH window
(or `scp`). Then on the server:
```
unzip rakshith-community.zip && cd rakshith-community
cp .env.example .env
nano .env
```
Set in `.env` (no `#` at the start of the line):
```
SECRET_KEY=<new random value: python3 -c "import secrets;print(secrets.token_hex(32))">
DB_PASSWORD=<another long random value>
DOMAIN=community.yourdomain.com
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<strong password>
ADMIN_FORCE_CHANGE=1
WHATSAPP_COMMUNITY_LINK=<your real link>
```

## 5. Start it
```
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f web     # Ctrl+C to leave the logs
```
Open `https://community.yourdomain.com` and log in as admin. HTTPS is automatic. (`CORS_ORIGINS` is set for you from `DOMAIN` - it is what lets live chat connect through HTTPS.)
After first login: change the admin password, then remove `ADMIN_PASSWORD` from `.env`.

## 6. Backups (do not skip)
- Lightsail → instance → **Snapshots** → enable **automatic snapshots** (covers database + uploads).
- Optional dump: `docker compose -f docker-compose.prod.yml exec db pg_dump -U community community > backup.sql`

## Updating later
Upload the new files, then run the `up -d --build` command again.
