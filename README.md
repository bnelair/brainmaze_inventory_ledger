# 🧪 Brainmaze Inventory Ledger

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-brightgreen)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A **full-stack, event-sourced inventory management system** designed for
research laboratories.  Every quantity change is stored as an immutable
event — giving you a tamper-evident audit trail, printable stock sheets, and
PDF confirmation slips that can be manually signed and physically filed.

---

## ✨ Features

| Feature | Detail |
|---|---|
| **Event Sourcing** | Every change is an append-only JSONL event identified by a ULID |
| **Current Stock view** | Live inventory table with low-stock highlighting |
| **Printable Stock Sheets** | Landscape A4 PDF — print and tape to closet doors / bins |
| **Change Confirmation Slips** | Per-transaction PDF with dual signature lines |
| **Item History Reports** | Full chronological PDF log per item |
| **Partial Location Transfer** | Move any quantity to a new location; batch multiple items; auto-creates destination record |
| **Git Synchronisation** | Push / pull inventory data to GitHub or GitLab |
| **Three Auth Methods** | PAT (HTTPS), SSH key pair, App / Bot token |
| **git-crypt support** | Encrypt private data repos; unlock key injected via env var |
| **Docker-ready** | Single `docker compose up` to run locally |
| **Cloud-ready** | Scripts for AWS CloudFormation and GCP Compute Engine / Cloud Run |

---

## 🚀 Quick Start (local, Docker)

```bash
# 1. Clone the application
git clone https://github.com/bnelair/brainmaze_inventory_ledger.git
cd brainmaze_inventory_ledger

# 2. Copy the example environment file
cp .env.example .env
# (Edit .env if you want Git sync – otherwise defaults are fine)

# 3. Build and start
docker compose up -d

# 4. Open the app
open http://localhost:8501
```

The application stores all inventory data in `./inventory_data/` (a local
folder mounted as a Docker volume), so data persists across container restarts.

---

## 🛠️ Local Development (without Docker)

```bash
# Python 3.11+ required
pip install -r requirements.txt

# Run Streamlit directly
DATA_DIR=./inventory_data REPORTS_DIR=./reports streamlit run src/app.py
```

Or use `make`:

```bash
make install   # pip install -r requirements.txt
make run       # launch Streamlit on http://localhost:8501
```

---

## 📁 Project Structure

```
brainmaze_inventory_ledger/
├── src/
│   ├── app.py            # Streamlit UI  (8 pages)
│   ├── inventory.py      # Event-sourcing engine
│   ├── reports.py        # PDF generation (fpdf2)
│   ├── git_manager.py    # Git auth & sync (PAT / SSH / APP)
│   ├── auth.py           # User management & bcrypt authentication
│   ├── projects.py       # Multi-project management
│   └── version.py        # Single version constant (__version__)
│
├── data/
│   └── schema.yaml       # Default project schema & category list
│
├── deploy/
│   ├── aws/
│   │   ├── cloudformation.yml   # VPC + EC2 + EBS template
│   │   └── deploy.sh            # One-command AWS deploy
│   └── gcp/
│       └── deploy.sh            # Compute Engine or Cloud Run deploy
│
├── inventory_data/       # Runtime – mounted volume (git repo for data)
├── reports/              # Runtime – temporary PDF cache
│
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── Makefile
├── requirements.txt
└── DEPLOYMENT.md         # Detailed deployment guide
```

---

## 🖥️ Application Pages

### 📦 Current Stock
Live inventory table computed by replaying all events.  Rows with quantity ≤
minimum stock level are highlighted in red.  A **Download Stock Sheet (PDF)**
button generates a printable landscape A4 table.

### ➕ Add Item
Register a new item with initial quantity, unit, category, location, supplier,
catalog number, and minimum stock threshold.  A confirmation slip PDF is
immediately available for download and physical filing.

### 🔄 Record Change
Select an existing item and record a stock addition, removal, or exact-value
set.  The resulting delta is previewed before submission.  A signed PDF slip is
generated automatically.

### 📍 Transfer Location
Move any quantity of one or more items to a different storage location in a
single batch operation.  If no record exists at the destination, one is created
automatically (cloning all metadata).  A printable **Batch Transfer Slip PDF**
with from / to / qty columns is generated after each transfer.

### 📜 Event History
Immutable, sortable, searchable audit trail.  Any event can be reprinted as an
individual confirmation slip by entering its Transaction ID (ULID).

### 🖨️ Print Reports
Generate full stock sheets and per-item history PDFs on demand.

### ☁️ Git Sync
Configure a remote repository, choose an authentication method (PAT / SSH /
App token), and commit / pull / push with a single click.  git-crypt unlock is
also accessible here.

### ⚙️ Settings
Edit the project name and category options.  Export current stock as CSV or the
full event log as JSON.

---

## 🔐 Git Authentication

### Personal Access Token (PAT) — recommended for most users

1. Create a token at **GitHub → Settings → Developer Settings → Personal Access
   Tokens** with `repo` scope.
2. Set in `.env`:
   ```
   GIT_AUTH_METHOD=PAT
   GIT_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   GIT_REPO_URL=https://github.com/org/inventory-data.git
   ```

### SSH Key Pair

1. Generate a key:  `ssh-keygen -t ed25519 -f ~/.ssh/brainmaze`
2. Add the public key to your GitHub / GitLab account.
3. In `.env` or `docker-compose.yml` set `GIT_AUTH_METHOD=SSH`.
4. The `docker-compose.yml` mounts `~/.ssh` read-only by default.

### App / Bot Account

Same as PAT but using a machine account token.  Set `GIT_AUTH_METHOD=APP`.

### git-crypt

```bash
# Export your git-crypt key as Base64
git-crypt export-key /tmp/git-crypt.key && base64 /tmp/git-crypt.key
```

Paste the Base64 string as `GIT_CRYPT_KEY=…` in `.env`.

---

## 🏗️ Architecture

```
Browser ──HTTP──▶ Streamlit (port 8501)
                      │
              ┌───────┴──────────────┐
              │                      │
         inventory.py           git_manager.py
         (event store)          (git sync)
              │
         events.jsonl           reports.py
         schema.yaml            (fpdf2 PDF engine)
              │
         inventory_data/
         (Docker volume / Git repo)
```

All inventory state lives in `inventory_data/events.jsonl`.  The current stock
is derived at read time by replaying the event log — there is no separate
"current state" file to get out of sync.

---

## ☁️ Cloud Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for step-by-step instructions covering:

- Local Docker Compose
- AWS EC2 (CloudFormation one-command deploy)
- AWS ECS Fargate (containerised, managed)
- Google Cloud Compute Engine
- Google Cloud Run (serverless)

---

## 📦 Technology Stack

| Layer | Technology |
|---|---|
| Frontend / UI | [Streamlit](https://streamlit.io) |
| Event Store | Newline-delimited JSON (JSONL) |
| Data Processing | [pandas](https://pandas.pydata.org) |
| PDF Generation | [fpdf2](https://py-fpdf2.readthedocs.io) |
| Unique IDs | [ULID](https://github.com/mdomke/python-ulid) |
| Configuration | YAML |
| Git Operations | subprocess (git CLI) |
| Container | Docker + Docker Compose |
| Cloud (AWS) | EC2, EBS, CloudFormation |
| Cloud (GCP) | Compute Engine, Cloud Run |

---

## 📄 License

MIT © Brainmaze
