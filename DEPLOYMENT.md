# Deployment Guide – Brainmaze Inventory Ledger

This guide covers every supported deployment target from a single laptop to
production cloud environments.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local – Docker Compose](#1-local--docker-compose)
3. [Local – Without Docker](#2-local--without-docker)
4. [AWS – EC2 (CloudFormation)](#3-aws--ec2-cloudformation)
5. [AWS – ECS Fargate](#4-aws--ecs-fargate)
6. [GCP – Compute Engine](#5-gcp--compute-engine)
7. [GCP – Cloud Run](#6-gcp--cloud-run)
8. [Environment Variables Reference](#environment-variables-reference)
9. [Updating the Application](#updating-the-application)
10. [Security Hardening Checklist](#security-hardening-checklist)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Minimum version | Install guide |
|---|---|---|
| Docker | 24.x | https://docs.docker.com/get-docker |
| Docker Compose | 2.x (plugin) | bundled with Docker Desktop |
| Python *(no-Docker only)* | 3.11+ | https://www.python.org |
| AWS CLI *(AWS only)* | 2.x | https://aws.amazon.com/cli |
| gcloud CLI *(GCP only)* | latest | https://cloud.google.com/sdk |

---

## 1. Local – Docker Compose

The recommended way to run the application on any laptop or on-prem server.

```bash
# Clone
git clone https://github.com/bnelair/brainmaze_inventory_ledger.git
cd brainmaze_inventory_ledger

# Configure (optional – defaults work for offline use)
cp .env.example .env
$EDITOR .env   # Set GIT_TOKEN, GIT_REPO_URL etc. if using Git sync

# Start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

**Data persistence:** All inventory data is stored in `./inventory_data/`.
This directory is a volume mount and survives container restarts and image
rebuilds.

**Custom port:** Set `APP_PORT=8080` in `.env` to expose on port 8080.

---

## 2. Local – Without Docker

```bash
# Python 3.11+ required
git clone https://github.com/bnelair/brainmaze_inventory_ledger.git
cd brainmaze_inventory_ledger

pip install -r requirements.txt

# Run
DATA_DIR=./inventory_data \
REPORTS_DIR=./reports \
streamlit run src/app.py --server.port 8501
```

---

## 3. AWS – EC2 (CloudFormation)

One-command deployment to a new EC2 instance inside a dedicated VPC.

### What gets created

- VPC with a public subnet and internet gateway
- Security group (ports 8501 and 22)
- EC2 instance (Amazon Linux 2023) with Docker pre-installed
- Separate EBS data volume (10 GB, gp3)
- The application repository is cloned and started automatically

### Steps

```bash
# 1. Set required variables
export KEY_PAIR_NAME="my-key-pair"       # Existing EC2 key pair name
export AWS_REGION="us-east-1"

# 2. (Optional) configure Git sync
export GIT_REPO_URL="https://github.com/org/inventory-data.git"
export GIT_TOKEN="ghp_xxxxxxxxxxxx"

# 3. Deploy
chmod +x deploy/aws/deploy.sh
./deploy/aws/deploy.sh
```

The script outputs the public IP and URL when the stack is ready.

> **Note:** The EC2 user-data script runs on first boot.  The application will
> be available ~3 minutes after the stack shows `CREATE_COMPLETE`.

### Teardown

```bash
aws cloudformation delete-stack --stack-name brainmaze-inventory-ledger \
    --region us-east-1
```

---

## 4. AWS – ECS Fargate

For a fully managed, highly available deployment without managing EC2 instances.

### Steps (overview)

```bash
# 1. Push image to ECR
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"
ECR_REPO="${AWS_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/brainmaze-ledger"

aws ecr create-repository --repository-name brainmaze-ledger --region ${REGION}
aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin ${ECR_REPO}

docker build -t brainmaze-ledger .
docker tag brainmaze-ledger:latest ${ECR_REPO}:latest
docker push ${ECR_REPO}:latest

# 2. Create EFS filesystem for persistent data
# (See AWS documentation for EFS creation + mount target setup)

# 3. Deploy ECS task definition pointing to the ECR image
# Set environment variables as ECS Task Environment or AWS Secrets Manager refs
```

### Persistent storage on ECS

ECS Fargate does not support persistent local volumes natively.
Use **Amazon EFS** for persistent inventory data:

1. Create an EFS filesystem in the same VPC as your ECS cluster.
2. In the task definition, add an EFS volume mount:
   ```json
   "volumes": [{
     "name": "inventory-data",
     "efsVolumeConfiguration": {
       "fileSystemId": "fs-xxxxxxxxx",
       "rootDirectory": "/brainmaze"
     }
   }]
   ```
3. Mount it as `/app/data` in the container.

Alternatively, configure a remote Git repository and enable auto-sync so all
changes are committed and pushed immediately.

---

## 5. GCP – Compute Engine

Equivalent to the AWS EC2 approach: a persistent VM running Docker Compose.

```bash
# 1. Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Export config
export GCP_PROJECT_ID="your-project-id"
export GCP_ZONE="us-central1-a"
export GIT_REPO_URL="https://github.com/org/inventory-data.git"
export GIT_TOKEN="ghp_xxxxxxxxxxxx"

# 3. Deploy
chmod +x deploy/gcp/deploy.sh
./deploy/gcp/deploy.sh
```

The script:
- Provisions a Compute Engine VM (Ubuntu 22.04, e2-small)
- Installs Docker + Docker Compose via startup script
- Clones the application and starts it
- Opens a firewall rule on the specified port

### Teardown

```bash
gcloud compute instances delete brainmaze-inventory-ledger --zone=us-central1-a
gcloud compute firewall-rules delete allow-brainmaze-8501
```

---

## 6. GCP – Cloud Run

Serverless containers with no infrastructure to manage.

> ⚠️ Cloud Run containers have **ephemeral** local storage.  Configure a remote
> Git repository so that inventory data is committed and pushed after every
> change, otherwise data is lost on container restart.

```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="us-central1"
export DEPLOY_TARGET=cloudrun

chmod +x deploy/gcp/deploy.sh
./deploy/gcp/deploy.sh
```

The script:
- Enables the required GCP APIs
- Builds the Docker image using Cloud Build and pushes to GCR
- Deploys a Cloud Run service with `--allow-unauthenticated`

For production, remove `--allow-unauthenticated` and set up **Cloud IAP** or
**Identity-Aware Proxy** to restrict access to your organisation.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8501` | Host port the web UI is exposed on |
| `DATA_DIR` | `/app/data` | Container path for inventory data |
| `REPORTS_DIR` | `/app/reports` | Container path for temporary PDF cache |
| `GIT_AUTH_METHOD` | `PAT` | Authentication method: `PAT`, `SSH`, or `APP` |
| `GIT_TOKEN` | *(empty)* | Personal Access Token or App token |
| `GIT_REPO_URL` | *(empty)* | Remote repository URL |
| `GIT_BRANCH` | `main` | Branch to push / pull |
| `GIT_USER_NAME` | `Brainmaze Bot` | Git commit author name |
| `GIT_USER_EMAIL` | `brainmaze@lab.local` | Git commit author email |
| `GIT_CRYPT_KEY` | *(empty)* | Base64-encoded git-crypt symmetric key |
| `SSH_DIR` | `~/.ssh` | Host path to SSH keys (volume mount source) |

---

## Updating the Application

```bash
# With Docker Compose
git pull
docker compose build
docker compose up -d

# Without Docker
git pull
pip install -r requirements.txt   # pick up any new deps
# Restart the Streamlit process
```

No data migrations are needed: the event log is append-only and backwards
compatible.

---

## Security Hardening Checklist

- [ ] Restrict `AllowedCIDR` (AWS) / firewall source range (GCP) to your
      office / VPN IP, not `0.0.0.0/0`.
- [ ] Put the application behind a reverse proxy (nginx / Caddy) with HTTPS /
      TLS termination.
- [ ] Use **AWS Secrets Manager** or **GCP Secret Manager** to inject
      `GIT_TOKEN` and `GIT_CRYPT_KEY` instead of storing them in `.env`.
- [ ] Enable Streamlit's built-in XSRF protection (set by default in the
      `Dockerfile` `config.toml`).
- [ ] For multi-user environments, add authentication middleware (e.g.,
      Streamlit-Authenticator, or an OAuth2 proxy in front of the app).
- [ ] Regularly rotate the Git Personal Access Token.
- [ ] Back up `inventory_data/` / the remote Git repository regularly.

---

## Troubleshooting

### The app shows "No inventory items yet" after restart

Check that the `./inventory_data` directory is correctly mounted.  Run
`docker compose ps` and `docker compose exec app ls /app/data`.

### Git push fails with "Authentication failed"

1. Verify `GIT_TOKEN` is set in `.env`.
2. Confirm the token has `repo` (GitHub) or `write_repository` (GitLab) scope.
3. For SSH auth: verify `~/.ssh` is mounted and the public key is added to your
   account.

### PDF download does nothing

Ensure your browser allows pop-ups / downloads from `localhost:8501`.

### Container keeps restarting

```bash
docker compose logs app   # view error output
```

Common causes: port already in use (`APP_PORT`), or a Python import error.

### Low disk space

The `events.jsonl` file grows over time.  A lab with 10 changes/day will
accumulate ~10 MB/year — disk space is not a concern in practice.

### git-crypt: "Error: secret key not available"

Set `GIT_CRYPT_KEY` before starting the container, or use the git-crypt
panel in the **☁️ Git Sync** page to unlock interactively.
