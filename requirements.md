# A) User Requirements (URD) - Final Revision
## 1. Core Objectives
Physical Visibility: Users must be able to print "Current Stock" sheets to tape onto inventory closets/bins for quick reference.

Paper Audit Trail: The system must generate "Inventory Change Documents" (Receipts) that include the item, quantity, researcher name (automatically determined from the logged-in account), and the explanation/reason for change for manual signing or physical filing.

Secure Enterprise Sync: Support for private research repositories on GitHub/GitLab using modern authentication (Personal Access Tokens or SSH Keys).

## 2. User Authentication & Access Control
Stateless User Store: The system shall authenticate users against a YAML file (`users.yaml`) that lives inside the git-tracked data directory, alongside inventory data. Passwords shall be stored as bcrypt hashes — never in plain text.

Three User Roles:
- **admin** — Full access: user management, project management, schema editing, Git sync, all CRUD operations.
- **readwrite** — Can add items, record stock changes, perform batch operations, view inventory, and download reports.
- **readonly** — Can only view current stock, event history, and download reports.

Self-Registration with Admin Approval: New users may self-register via the login page. Registered accounts are created in a **pending** (inactive) state. An admin must approve (activate) each account before it can be used to log in. Admins may also reject (delete) pending registrations.

Automatic Audit Attribution: The name of the user performing any add/remove/change operation is automatically determined from the logged-in account. There is no manual "Researcher Name" field in operation forms.

## 3. Multi-Project Inventory
Multiple Projects: The application shall support multiple independent inventory projects within a single deployment. Each project has its own item catalogue, event ledger, and schema.

Shared Users: All users (with their roles) apply across all projects.

Project Selection: Users select the active project from the sidebar. The current project context is shown at all times.

## 4. Per-Project Dynamic Schema
Admin-Defined Columns: Each project's schema (custom fields, categories, units, etc.) is defined by an admin through the UI. The schema is stored in a per-project `schema.yaml` file.

Custom Field Types: Supported field types are `text`, `number`, `select` (dropdown), and `checkbox`.

Required / Optional: Each custom field may be marked as required or optional with a configurable default value.

# B) Technical Requirements (SRS) - Final Revision
## 1. Output & Reporting
PDF Generation: The system shall use a library (e.g., ReportLab or FPDF2) to generate clean, printable PDF documents of the inventory tables and individual transaction records.

Audit Slips: Each "Change Event" shall have a "Print Confirmation" button that generates a standardized PDF slip including the ULID, Timestamp, and Reason. All generated PDFs shall be downloadable directly from the web interface via browser download (no separate server file-system access needed).

## 2. Batch Operations
Batch Add: The system shall allow adding multiple new items in a single operation. Users may fill in an interactive table (data editor) or upload a CSV file, preview the items, and submit all at once.

Batch Stock Change: The system shall allow selecting multiple existing items and applying the same stock operation (add, remove, or set exact quantity) with a shared reason to all selected items in one submission.

## 3. Git Authentication Layer
Credential Management: The system shall support three Git authentication methods:

HTTPS with Personal Access Token (PAT): Input via UI, stored in the local container environment.

SSH: The Docker container shall be able to mount a local .ssh directory to use private keys for passwordless pushing.

App Credentials: Environment variables for GitHub/GitLab Actions/Bot accounts.

## 4. Data Portability
Git-Crypt Integration: If using private repos, the git-crypt unlock key must be injectable via an environment variable or a secure vault during initialization.

# C) Implementation Details (SDD) - Final Revision
## 1. Authentication Module (`auth.py`)
```Python
class AuthManager:
    # Users stored in data/users.yaml (committed to git, bcrypt-hashed passwords)
    # User record: {username, display_name, role, password_hash, active, created_at}
    def authenticate(self, username, password) -> dict | None: ...
    def register(self, username, password, display_name) -> (bool, str): ...
    def approve_user(self, username) -> (bool, str): ...
    def list_pending(self) -> list[dict]: ...
    def list_users(self) -> list[dict]: ...
    def create_user(self, username, password, role, display_name) -> (bool, str): ...
    def update_role(self, username, role) -> (bool, str): ...
    def update_password(self, username, new_password) -> (bool, str): ...
    def delete_user(self, username) -> (bool, str): ...
```

## 2. Project Manager (`projects.py`)
```Python
class ProjectManager:
    # Projects registry: data/projects.yaml
    # Per-project directory: data/projects/<slug>/
    # Per-project files: events.jsonl, schema.yaml
    def list_projects(self) -> list[dict]: ...
    def create_project(self, name, description, created_by) -> dict: ...
    def get_project_dir(self, project_id) -> Path: ...
    def get_schema(self, project_id) -> dict: ...
    def save_schema(self, project_id, schema) -> None: ...
    def delete_project(self, project_id) -> (bool, str): ...
```

## 3. The Printing Module (`reports.py`)
```Python
class ReportGenerator:
    def generate_stock_pdf(self, df, custom_fields=None): ...
    def generate_change_slip(self, event_data, item_name=""): ...
    def generate_item_history_pdf(self, events, item_name, df_stock=None): ...
    def generate_batch_slip(self, events, batch_reason, researcher): ...
```

## 4. Git Remote Configuration
To support private repos, the GitManager will be updated to handle authenticated URLs:

HTTPS Path: https://{token}@github.com/user/repo.git

SSH Path: Standard git@github.com:user/repo.git (requires mounting /root/.ssh in Docker).

## 5. Revised File Structure
```Plaintext
/brainmaze-ledger/
├── .ssh/                        # [OPTIONAL] Mounted for private Git access
├── reports/                     # [TEMPORARY] PDF cache for printing
├── src/
│   ├── app.py                  # UI: auth, multi-project, role-based nav
│   ├── auth.py                 # User auth & role management
│   ├── projects.py             # Multi-project registry & schema
│   ├── reports.py              # PDF generation logic
│   ├── inventory.py            # Event-sourcing engine (+ batch ops)
│   └── git_manager.py          # SSH/PAT credential logic
└── data/                        # Git-tracked data root
    ├── users.yaml              # Hashed user credentials (stateless)
    ├── projects.yaml           # Project registry
    └── projects/
        ├── <project-slug>/
        │   ├── events.jsonl    # Append-only event ledger
        │   └── schema.yaml     # Per-project columns & categories
        └── ...
```

## 6. Final Stack Overview (Docker Compose)
```YAML
services:
  app:
    build: .
    environment:
      - GIT_AUTH_METHOD=SSH # or PAT
      - GIT_TOKEN=${MY_GIT_TOKEN}
      - GIT_CRYPT_KEY=${MY_UNLOCK_KEY}
    volumes:
      - ./inventory_data:/app/data
      - ~/.ssh:/root/.ssh:ro
    ports:
      - "8501:8501"
```

## Implementation Roadmap Summary
Phase 1: Build the core Event-Sourcing engine (Python + JSON + Pandas) with batch operations.

Phase 2: Implement Authentication (bcrypt, users.yaml, roles, registration + admin approval).

Phase 3: Implement Multi-Project support (ProjectManager, per-project schema with custom fields).

Phase 4: Implement the Dynamic UI (Streamlit) with login/register, role-based navigation, project selector, dynamic forms, and batch operation pages.

Phase 5: Integrate Git-Crypt and the GitManager for secure private repo syncing.

Phase 6: Add/enhance the ReportGenerator for printable PDFs and ensure all reports are web-downloadable.

# B) Technical Requirements (SRS) - Final Revision
## 1. Output & Reporting
PDF Generation: The system shall use a library (e.g., ReportLab or FPDF2) to generate clean, printable PDF documents of the inventory tables and individual transaction records.

Audit Slips: Each "Change Event" shall have a "Print Confirmation" button that generates a standardized PDF slip including the ULID, Timestamp, and Reason.

## 2. Git Authentication Layer
Credential Management: The system shall support three Git authentication methods:

HTTPS with Personal Access Token (PAT): Input via UI, stored in the local container environment.

SSH: The Docker container shall be able to mount a local .ssh directory to use private keys for passwordless pushing.

App Credentials: Environment variables for GitHub/GitLab Actions/Bot accounts.

## 3. Data Portability
Git-Crypt Integration: If using private repos, the git-crypt unlock key must be injectable via an environment variable or a secure vault during initialization.

# C) Implementation Details (SDD) - Final Revision
## 1. The Printing Module (Python)
Instead of just showing the table in the browser, we add a "Report" engine.

```Python
import pandas as pd
from fpdf import FPDF

class ReportGenerator:
    def generate_stock_pdf(self, df):
        # Creates a formatted PDF of the current inventory table
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(40, 10, "Brainmaze Inventory: Current Stock")
        # Logic to iterate through DataFrame and build PDF table...
        return pdf.output(dest='S').encode('latin-1')

    def generate_change_slip(self, event_data):
        # Creates a single-page confirmation for a specific transaction
        # Includes fields for: ULID, Item, Qty, Reason, Signature Line
        pass
```

## 2. Git Remote Configuration
To support private repos, the GitManager will be updated to handle authenticated URLs:

HTTPS Path: https://{token}@github.com/user/repo.git

SSH Path: Standard git@github.com:user/repo.git (requires mounting /root/.ssh in Docker).

## 3. Revised File Structure
```Plaintext
/brainmaze-ledger/
├── .ssh/                    # [OPTIONAL] Mounted for private Git access
├── reports/                 # [TEMPORARY] PDF cache for printing
├── src/
│   ├── app.py              # UI with "Print to PDF" buttons
│   ├── reports.py          # PDF generation logic
│   └── git_manager.py      # SSH/PAT credential logic
└── ...
```

## 4. Final Stack Overview (Docker Compose)
The final setup uses a "Self-Contained Secret" approach for the Git connection.

```YAML
services:
  app:
    build: .
    environment:
      - GIT_AUTH_METHOD=SSH # or PAT
      - GIT_TOKEN=${MY_GIT_TOKEN}
      - GIT_CRYPT_KEY=${MY_UNLOCK_KEY}
    volumes:
      - ./inventory_data:/app/data
      - ~/.ssh:/root/.ssh:ro # Mounts your local SSH keys for Git access
    ports:
      - "8501:8501" # Streamlit
```

## Implementation Roadmap Summary
Phase 1: Build the core Event-Sourcing engine (Python + JSON + Pandas).

Phase 2: Implement the Dynamic UI (Streamlit) that reads the per-project schema.yaml.

Phase 3: Integrate Git-Crypt and the GitManager for secure private repo syncing.

Phase 4: Add the ReportGenerator for "Inventory Closet" PDFs and "Change Confirmation" slips.
