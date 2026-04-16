# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] – 2026-04-16

### Added
- **Partial Location Transfer** — move any quantity of an item to a different
  storage location.  If no record exists at the destination, one is created
  automatically inheriting all metadata (category, unit, supplier, etc.).
- **Batch Transfer** — submit multiple item transfers in a single operation.
  All rows share a common batch ID and a downloadable **Batch Transfer Slip
  PDF** (Category | Item Name | From | To | Qty) is generated on success.
- `inventory.py` — `transfer_quantity()` and `batch_transfer()` methods.
- `reports.py` — `generate_transfer_slip()` for the new PDF slip.
- `src/version.py` — single source of truth for `__version__`.
- Version displayed in the sidebar footer and the Streamlit About menu.
- Category column placed first in all stock tables and PDFs.
- Dependency upper-bounds added to `requirements.txt` for reproducible builds.
- Makefile `lint` target now covers all six source modules.

### Changed
- Transfer Location page upgraded from a single-item metadata-only form to a
  full batch table editor with per-row quantity and destination controls.
- `README.md` updated with version badges, Transfer Location page description,
  and complete `src/` module listing.
- `docker-compose.yml` image tag updated to `1.0.0`.

---

## [Unreleased]

_Future improvements go here before the next release._
