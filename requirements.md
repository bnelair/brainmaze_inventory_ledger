# A) User Requirements (URD) - Final Revision
## 1. Core Objectives
Physical Visibility: Users must be able to print "Current Stock" sheets to tape onto inventory closets/bins for quick reference.

Paper Audit Trail: The system must generate "Inventory Change Documents" (Receipts) that include the item, quantity, researcher name, and the explanation/reason for change for manual signing or physical filing.

Secure Enterprise Sync: Support for private research repositories on GitHub/GitLab using modern authentication (Personal Access Tokens or SSH Keys).

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
Plaintext
/brainmaze-ledger/
├── .ssh/                    # [OPTIONAL] Mounted for private Git access
├── reports/                 # [TEMPORARY] PDF cache for printing
├── src/
│   ├── app.py              # UI with "Print to PDF" buttons
│   ├── reports.py          # PDF generation logic
│   └── git_manager.py      # SSH/PAT credential logic
└── ...

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
