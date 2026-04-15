"""
Brainmaze Inventory Ledger – Streamlit Application
===================================================
A full-featured, event-sourced inventory management system designed for
research laboratories.

Pages
-----
📦 Current Stock   – live inventory table with PDF export
➕ Add Item        – register a new inventory item
🔄 Record Change   – add / remove stock for an existing item
📜 Event History   – immutable audit trail with per-event slip printing
🖨️ Print Reports   – generate stock sheets and item-history PDFs
🔄 Git Sync        – commit, push, and pull inventory data
⚙️  Settings       – project name, categories, and schema management

Run with:
    streamlit run src/app.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
import streamlit as st
import yaml

# Make sure sibling modules are importable when launched from any directory
sys.path.insert(0, str(Path(__file__).parent))

from git_manager import GitManager  # noqa: E402
from inventory import InventoryLedger  # noqa: E402
from reports import ReportGenerator  # noqa: E402

# ---------------------------------------------------------------------------
# Paths (override via environment variables for Docker / cloud deployments)
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports"))
SCHEMA_FILE = DATA_DIR / "schema.yaml"

# ---------------------------------------------------------------------------
# Default schema used when schema.yaml is absent
# ---------------------------------------------------------------------------
_DEFAULT_SCHEMA: Dict = {
    "project_name": "Brainmaze Laboratory Inventory",
    "schema_version": "1.0",
    "category_options": [
        "Reagent",
        "Equipment",
        "Consumable",
        "Chemical",
        "Biological",
        "Safety",
        "Administrative",
        "Other",
    ],
}

# ---------------------------------------------------------------------------
# Page & layout configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Brainmaze Inventory Ledger",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/bnelair/brainmaze_inventory_ledger",
        "Report a bug": "https://github.com/bnelair/brainmaze_inventory_ledger/issues",
        "About": "Brainmaze Inventory Ledger – event-sourced lab inventory management.",
    },
)

st.markdown(
    """
    <style>
        .main-header  { font-size:2rem; font-weight:700; color:#1e4078; margin-bottom:0; }
        .sub-header   { font-size:1rem; color:#555; margin-top:0; margin-bottom:1rem; }
        .badge-ok     { background:#d4edda; color:#155724; padding:2px 8px; border-radius:12px; font-size:.8rem; }
        .badge-warn   { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:12px; font-size:.8rem; }
        .badge-error  { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:12px; font-size:.8rem; }
        div[data-testid="stMetricValue"] { font-size:1.6rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Cached singletons
# ---------------------------------------------------------------------------

@st.cache_resource
def _ledger() -> InventoryLedger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return InventoryLedger(data_dir=DATA_DIR)


@st.cache_resource
def _git() -> GitManager:
    return GitManager(data_dir=DATA_DIR)


def _reporter() -> ReportGenerator:
    return ReportGenerator(project_name=_project_name())


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _load_schema() -> Dict:
    if SCHEMA_FILE.exists():
        with SCHEMA_FILE.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or _DEFAULT_SCHEMA
    return dict(_DEFAULT_SCHEMA)


def _save_schema(schema: Dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SCHEMA_FILE.open("w", encoding="utf-8") as fh:
        yaml.dump(schema, fh, default_flow_style=False, allow_unicode=True)


def _project_name() -> str:
    return _load_schema().get("project_name", "Brainmaze Inventory")


def _category_options() -> list:
    return _load_schema().get("category_options", _DEFAULT_SCHEMA["category_options"])


# ---------------------------------------------------------------------------
# Shared formatting
# ---------------------------------------------------------------------------

def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def _page_header(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(f'<p class="main-header">{icon} {title}</p>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p class="sub-header">{subtitle}</p>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar & navigation
# ---------------------------------------------------------------------------

_NAV_PAGES = {
    "📦 Current Stock":  "stock",
    "➕ Add Item":       "add_item",
    "🔄 Record Change":  "record_change",
    "📜 Event History":  "history",
    "🖨️ Print Reports":  "reports",
    "☁️ Git Sync":       "git_sync",
    "⚙️ Settings":       "settings",
}


def _render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            f"### 🧪 {_project_name()}",
            help="Configure the project name in ⚙️ Settings.",
        )
        st.caption("Inventory Ledger · Event-Sourced")
        st.divider()

        selection = st.radio(
            "Navigation",
            list(_NAV_PAGES.keys()),
            label_visibility="collapsed",
        )

        st.divider()
        # Quick stats
        df = _ledger().get_current_stock()
        if not df.empty:
            col1, col2 = st.columns(2)
            col1.metric("Items", len(df))
            total = int(df["quantity"].sum()) if "quantity" in df.columns else 0
            col2.metric("Total Qty", total)

            if "min_stock_level" in df.columns and "quantity" in df.columns:
                low = df[(df["min_stock_level"] > 0) & (df["quantity"] <= df["min_stock_level"])]
                if not low.empty:
                    st.warning(f"⚠️ **{len(low)}** item(s) below minimum stock.")
        else:
            st.info("No inventory items yet.")

    return _NAV_PAGES[selection]


# ===========================================================================
# Pages
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. Current Stock
# ---------------------------------------------------------------------------

def page_stock() -> None:
    _page_header("📦", "Current Stock", "Real-time inventory levels computed from the event ledger.")

    ledger = _ledger()
    df = ledger.get_current_stock()

    col_refresh, *_ = st.columns([1, 4])
    if col_refresh.button("🔄 Refresh"):
        st.cache_resource.clear()
        st.rerun()

    if df.empty:
        st.info("No inventory items yet. Go to **➕ Add Item** to get started.")
        return

    # ---- KPI row --------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Items", len(df))
    col2.metric("Total Quantity", int(df["quantity"].sum()) if "quantity" in df.columns else 0)
    if "min_stock_level" in df.columns and "quantity" in df.columns:
        low_n = int(((df["min_stock_level"] > 0) & (df["quantity"] <= df["min_stock_level"])).sum())
        col3.metric("⚠️ Low Stock", low_n, delta=f"-{low_n}" if low_n else None, delta_color="inverse")
    if "category" in df.columns:
        col4.metric("Categories", int(df["category"].nunique()))

    st.divider()

    # ---- filters --------------------------------------------------------
    fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
    with fcol1:
        search = st.text_input("🔍 Search", placeholder="Filter by any field…")
    with fcol2:
        cat_opts = ["All"] + (sorted(df["category"].dropna().unique().tolist()) if "category" in df.columns else [])
        cat_filter = st.selectbox("Category", cat_opts)
    with fcol3:
        low_only = st.checkbox("Low Stock Only")

    filtered = df.copy()
    if search:
        mask = filtered.apply(lambda r: search.lower() in " ".join(str(v) for v in r).lower(), axis=1)
        filtered = filtered[mask]
    if cat_filter != "All" and "category" in filtered.columns:
        filtered = filtered[filtered["category"] == cat_filter]
    if low_only and "min_stock_level" in filtered.columns:
        filtered = filtered[(filtered["min_stock_level"] > 0) & (filtered["quantity"] <= filtered["min_stock_level"])]

    # ---- table ----------------------------------------------------------
    display_order = ["item_name", "quantity", "unit", "category", "location",
                     "min_stock_level", "supplier", "catalog_number", "last_updated"]
    display_cols = [c for c in display_order if c in filtered.columns]
    col_labels = {
        "item_name": "Item Name", "quantity": "Qty", "unit": "Unit",
        "category": "Category", "location": "Location",
        "min_stock_level": "Min Stock", "supplier": "Supplier",
        "catalog_number": "Catalog #", "last_updated": "Last Updated",
    }

    def _hl_low(row: pd.Series) -> list:
        if "min_stock_level" in row.index and "quantity" in row.index:
            if row["min_stock_level"] > 0 and row["quantity"] <= row["min_stock_level"]:
                return ["background-color: #ffe6e6"] * len(row)
        return [""] * len(row)

    show_df = filtered[display_cols].rename(columns=col_labels)
    st.dataframe(
        show_df.style.apply(_hl_low, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # ---- PDF download ---------------------------------------------------
    reporter = _reporter()
    pdf_bytes = reporter.generate_stock_pdf(filtered)
    st.download_button(
        label="🖨️ Download Stock Sheet (PDF)",
        data=pdf_bytes,
        file_name=f"stock_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mime="application/pdf",
        type="primary",
    )


# ---------------------------------------------------------------------------
# 2. Add Item
# ---------------------------------------------------------------------------

def page_add_item() -> None:
    _page_header("➕", "Add Item", "Register a new inventory item and record its initial stock.")

    with st.form("add_item_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            item_name = st.text_input("Item Name *", placeholder="e.g., Ethanol 96%")
            initial_qty = st.number_input("Initial Quantity *", min_value=0, value=0, step=1)
        with col2:
            unit = st.text_input("Unit", value="pcs", placeholder="pcs · mL · mg · boxes")
            category = st.selectbox("Category", _category_options())

        col3, col4 = st.columns(2)
        with col3:
            location = st.text_input("Storage Location", placeholder="e.g., Freezer-1, Shelf-A")
            supplier = st.text_input("Supplier", placeholder="e.g., Sigma-Aldrich")
        with col4:
            catalog_number = st.text_input("Catalog / CAS Number", placeholder="e.g., CAS-64-17-5")
            min_stock = st.number_input(
                "Minimum Stock Level",
                min_value=0, value=0, step=1,
                help="Warn when quantity drops to or below this threshold.",
            )

        notes = st.text_area("Notes", placeholder="Optional additional notes…")

        st.divider()
        st.subheader("📋 Audit Information")
        acol1, acol2 = st.columns(2)
        with acol1:
            researcher = st.text_input("Researcher Name *", placeholder="Your full name")
        with acol2:
            reason = st.text_input("Reason *", placeholder="e.g., Initial stock entry, Purchased from supplier")

        submitted = st.form_submit_button("✅ Add Item", type="primary", use_container_width=True)

    if submitted:
        errors = []
        if not item_name.strip():
            errors.append("Item name is required.")
        if not researcher.strip():
            errors.append("Researcher name is required.")
        if not reason.strip():
            errors.append("Reason is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            event = _ledger().add_item(
                item_name=item_name.strip(),
                initial_quantity=int(initial_qty),
                researcher=researcher.strip(),
                reason=reason.strip(),
                unit=unit.strip(),
                category=category,
                location=location.strip(),
                supplier=supplier.strip(),
                catalog_number=catalog_number.strip(),
                min_stock_level=int(min_stock),
                notes=notes.strip(),
            )
            st.success(f"✅ **{item_name}** added to the inventory.")
            st.code(f"Transaction ID : {event['id']}\nItem ID        : {event['item_id']}")

            pdf_bytes = _reporter().generate_change_slip(event, item_name.strip())
            st.download_button(
                "🖨️ Download Confirmation Slip (PDF)",
                data=pdf_bytes,
                file_name=f"slip_{event['id']}.pdf",
                mime="application/pdf",
            )


# ---------------------------------------------------------------------------
# 3. Record Change
# ---------------------------------------------------------------------------

def page_record_change() -> None:
    _page_header("🔄", "Record Change", "Record a quantity change for an existing inventory item.")

    ledger = _ledger()
    df = ledger.get_current_stock()

    if df.empty:
        st.info("No items in inventory. Add items first using **➕ Add Item**.")
        return

    item_names: Dict[str, str] = df.set_index("item_id")["item_name"].to_dict()
    options = {f"{name}  (ID: {id_})": id_ for id_, name in item_names.items()}

    with st.form("record_change_form", clear_on_submit=True):
        selected_label = st.selectbox("Select Item *", list(options.keys()))
        item_id = options[selected_label]

        # Show current state of selected item
        row_match = df[df["item_id"] == item_id]
        current = row_match.iloc[0] if not row_match.empty else None
        if current is not None:
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Current Stock", f"{current['quantity']} {current.get('unit', 'pcs')}")
            mc2.metric("Category", current.get("category", "—"))
            mc3.metric("Location", current.get("location", "—"))
            mc4.metric("Min Stock", current.get("min_stock_level", 0))

        st.divider()

        dcol1, dcol2 = st.columns(2)
        with dcol1:
            change_type = st.selectbox("Change Type", ["Add Stock", "Remove Stock", "Set to Exact Value"])
        with dcol2:
            qty_input = st.number_input("Quantity", min_value=0, value=1, step=1)

        # Preview the resulting delta
        if current is not None:
            cur_qty = int(current["quantity"])
            if change_type == "Add Stock":
                delta = int(qty_input)
                new_qty = cur_qty + delta
            elif change_type == "Remove Stock":
                delta = -int(qty_input)
                new_qty = cur_qty + delta
            else:
                delta = int(qty_input) - cur_qty
                new_qty = int(qty_input)

            sign = "+" if delta >= 0 else ""
            st.info(
                f"Quantity **{cur_qty}** → **{new_qty}**  "
                f"(change: **{sign}{delta}**)"
            )

        st.divider()
        rcol1, rcol2 = st.columns(2)
        with rcol1:
            researcher = st.text_input("Researcher Name *", placeholder="Your full name")
        with rcol2:
            reason = st.text_input(
                "Reason *",
                placeholder="e.g., Used in experiment #42, Restocked from supplier",
            )

        submitted = st.form_submit_button("✅ Record Change", type="primary", use_container_width=True)

    if submitted:
        errors = []
        if not researcher.strip():
            errors.append("Researcher name is required.")
        if not reason.strip():
            errors.append("Reason is required.")
        if delta == 0:
            errors.append("The calculated quantity delta is 0 — no change will be recorded.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            event = ledger.record_change(
                item_id=item_id,
                qty_delta=delta,
                researcher=researcher.strip(),
                reason=reason.strip(),
            )
            name = item_names.get(item_id, "item")
            st.success(f"✅ Change recorded for **{name}**.")
            st.code(f"Transaction ID : {event['id']}")

            pdf_bytes = _reporter().generate_change_slip(event, name)
            st.download_button(
                "🖨️ Download Change Slip (PDF)",
                data=pdf_bytes,
                file_name=f"change_slip_{event['id']}.pdf",
                mime="application/pdf",
            )


# ---------------------------------------------------------------------------
# 4. Event History
# ---------------------------------------------------------------------------

def page_history() -> None:
    _page_header("📜", "Event History", "Immutable audit trail of every inventory change.")

    ledger = _ledger()
    events = ledger.get_event_history()
    item_names = ledger.get_item_names()

    if not events:
        st.info("No events recorded yet.")
        return

    # Build display DataFrame (newest first)
    records = []
    for ev in sorted(events, key=lambda e: e.get("timestamp", ""), reverse=True):
        payload = ev.get("payload", {})
        iid = ev.get("item_id", "")
        name = payload.get("item_name", item_names.get(iid, "—"))
        etype = ev.get("type", "")
        if etype == "ITEM_CREATED":
            qty_str = f"+{payload.get('quantity', 0)}"
        elif etype == "STOCK_CHANGED":
            d = int(payload.get("qty_delta", 0))
            qty_str = f"+{d}" if d >= 0 else str(d)
        else:
            qty_str = "—"
        records.append({
            "Transaction ID": ev.get("id", ""),
            "Timestamp":      _fmt_ts(ev.get("timestamp", "")),
            "Type":           etype.replace("_", " ").title(),
            "Item":           name,
            "Qty +/-":         qty_str,
            "Researcher":     payload.get("researcher", ""),
            "Reason":         payload.get("reason", ""),
        })

    df_hist = pd.DataFrame(records)

    st.metric("Total Events", len(df_hist))

    # Filters
    fc1, fc2 = st.columns([2, 1])
    with fc1:
        search = st.text_input("🔍 Search history", placeholder="Item, researcher, reason…")
    with fc2:
        type_filter = st.selectbox(
            "Event Type",
            ["All", "Item Created", "Stock Changed", "Item Updated"],
        )

    if search:
        mask = df_hist.apply(lambda r: search.lower() in " ".join(str(v) for v in r).lower(), axis=1)
        df_hist = df_hist[mask]
    if type_filter != "All":
        df_hist = df_hist[df_hist["Type"].str.lower() == type_filter.lower()]

    st.dataframe(df_hist, use_container_width=True, hide_index=True)

    # Print individual slip
    st.divider()
    st.subheader("🖨️ Print Confirmation Slip for a Specific Event")
    eid = st.text_input("Enter Transaction ID (ULID):")
    if eid.strip():
        event = ledger.get_event_by_id(eid.strip())
        if event:
            iid = event.get("item_id", "")
            name = event.get("payload", {}).get("item_name", item_names.get(iid, ""))
            pdf_bytes = _reporter().generate_change_slip(event, name)
            st.download_button(
                "📄 Download Slip",
                data=pdf_bytes,
                file_name=f"slip_{eid.strip()}.pdf",
                mime="application/pdf",
                type="primary",
            )
        else:
            st.error("Event not found. Please verify the Transaction ID.")


# ---------------------------------------------------------------------------
# 5. Print Reports
# ---------------------------------------------------------------------------

def page_reports() -> None:
    _page_header("🖨️", "Print Reports", "Generate printable PDF documents for physical filing.")

    ledger = _ledger()
    df = ledger.get_current_stock()
    reporter = _reporter()

    rcol1, rcol2 = st.columns(2)

    with rcol1:
        st.subheader("📋 Full Stock Sheet")
        st.write("Landscape A4 table of all current inventory. Print and tape to closet doors or bin labels.")
        if df.empty:
            st.warning("No inventory items to report.")
        else:
            pdf_bytes = reporter.generate_stock_pdf(df)
            st.download_button(
                "📥 Download Full Stock Sheet",
                data=pdf_bytes,
                file_name=f"stock_sheet_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

    with rcol2:
        st.subheader("📦 Item History Report")
        st.write("Chronological change log for a single inventory item.")
        if df.empty:
            st.warning("No inventory items yet.")
        else:
            names = df.set_index("item_id")["item_name"].to_dict()
            sel = st.selectbox("Select item", list(names.values()), key="hist_select")
            target_id = next((k for k, v in names.items() if v == sel), None)
            if target_id:
                ev_list = ledger.get_item_history(target_id)
                pdf_bytes = reporter.generate_item_history_pdf(ev_list, sel, df)
                st.download_button(
                    "📥 Download Item History",
                    data=pdf_bytes,
                    file_name=f"history_{sel.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )


# ---------------------------------------------------------------------------
# 6. Git Sync
# ---------------------------------------------------------------------------

def page_git_sync() -> None:
    _page_header("☁️", "Git Sync", "Commit, push, and pull inventory data with a remote Git repository.")

    git = _git()
    status = git.get_status()

    scol1, scol2 = st.columns(2)
    with scol1:
        if status["initialized"]:
            st.success("✅ Git repository initialised")
            st.markdown(f"**Branch:** `{status.get('branch', '—')}`")
            st.markdown(f"**Remote:** `{status.get('remote_url', 'Not configured')}`")
        else:
            st.warning("⚠️ Git repository not yet initialised.")
            st.caption(status.get("message", ""))
    with scol2:
        if status.get("has_changes"):
            st.warning(f"📝 **{len(status.get('changes', []))}** uncommitted change(s):")
            for ch in status.get("changes", [])[:8]:
                st.code(ch)
        elif status["initialized"]:
            st.success("✅ Working directory clean.")

    st.divider()

    # ---- Configuration --------------------------------------------------
    with st.expander("⚙️ Git Configuration", expanded=not status["initialized"]):
        cfg_repo = st.text_input(
            "Repository URL",
            value=os.environ.get("GIT_REPO_URL", git.repo_url or ""),
            placeholder="https://github.com/org/repo.git  or  git@github.com:org/repo.git",
        )
        ccol1, ccol2 = st.columns(2)
        with ccol1:
            cfg_auth = st.selectbox(
                "Authentication Method",
                ["PAT", "SSH", "APP"],
                index=["PAT", "SSH", "APP"].index(git.auth_method) if git.auth_method in ["PAT", "SSH", "APP"] else 0,
            )
            cfg_branch = st.text_input("Branch", value=git.branch)
        with ccol2:
            if cfg_auth in ("PAT", "APP"):
                cfg_token = st.text_input("Personal Access Token", type="password")
            else:
                st.info("SSH uses the mounted `~/.ssh` directory.  No token required.")
                cfg_token = ""

            cfg_name = st.text_input("Commit Author Name", value=git.git_user_name)
            cfg_email = st.text_input("Commit Author Email", value=git.git_user_email)

        if st.button("💾 Apply Configuration"):
            git.repo_url = cfg_repo
            git.auth_method = cfg_auth
            git.token = cfg_token or git.token
            git.branch = cfg_branch
            git.git_user_name = cfg_name
            git.git_user_email = cfg_email

            if not status["initialized"]:
                ok, msg = git.init_repo()
                (st.success if ok else st.error)(msg)

            if cfg_repo:
                ok, msg = git.setup_remote()
                (st.success if ok else st.error)(msg)

    st.divider()

    # ---- Actions --------------------------------------------------------
    acol1, acol2, acol3 = st.columns(3)
    with acol1:
        if st.button("📤 Commit", use_container_width=True):
            ok, msg = git.commit_all()
            (st.success if ok else st.error)(msg)
    with acol2:
        if st.button("⬇️ Pull", use_container_width=True):
            ok, msg = git.pull()
            (st.success if ok else st.error)(msg)
    with acol3:
        if st.button("⬆️ Push", use_container_width=True):
            ok, msg = git.push()
            (st.success if ok else st.error)(msg)

    if st.button("🔄 Full Sync  (Commit → Pull → Push)", type="primary", use_container_width=True):
        with st.spinner("Syncing…"):
            ok, msg = git.sync()
        (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")

    # ---- git-crypt ------------------------------------------------------
    st.divider()
    with st.expander("🔐 git-crypt – Unlock Encrypted Repository"):
        st.markdown(
            "Provide the symmetric key as a **Base64-encoded** string, "
            "or set the `GIT_CRYPT_KEY` environment variable before starting the container."
        )
        crypt_key = st.text_input("git-crypt Key (Base64)", type="password", key="crypt_key_input")
        if st.button("🔓 Unlock"):
            import os as _os
            if crypt_key:
                _os.environ["GIT_CRYPT_KEY"] = crypt_key
            ok, msg = git.unlock_git_crypt()
            (st.success if ok else st.error)(msg)

    # ---- Recent commits ------------------------------------------------
    if status.get("recent_commits"):
        st.divider()
        st.subheader("Recent Commits")
        for c in status["recent_commits"]:
            st.text(c)


# ---------------------------------------------------------------------------
# 7. Settings
# ---------------------------------------------------------------------------

def page_settings() -> None:
    _page_header("⚙️", "Settings", "Configure project name, categories, and schema.")

    schema = _load_schema()

    with st.form("settings_form"):
        new_name = st.text_input("Project Name", value=schema.get("project_name", ""))
        st.subheader("Category Options")
        cats_text = st.text_area(
            "Categories (one per line)",
            value="\n".join(schema.get("category_options", [])),
            height=200,
        )
        saved = st.form_submit_button("💾 Save Settings", type="primary")

    if saved:
        new_cats = [c.strip() for c in cats_text.splitlines() if c.strip()]
        schema["project_name"] = new_name.strip() or schema.get("project_name", "")
        schema["category_options"] = new_cats
        _save_schema(schema)
        st.success("✅ Settings saved.")
        st.cache_resource.clear()
        st.rerun()

    st.divider()
    st.subheader("📥 Data Export")
    export_col1, export_col2 = st.columns(2)

    ledger = _ledger()
    df = ledger.get_current_stock()

    with export_col1:
        if not df.empty:
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📄 Export Current Stock (CSV)",
                data=csv_bytes,
                file_name=f"stock_export_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with export_col2:
        events = ledger.get_event_history()
        if events:
            import json as _json
            json_bytes = _json.dumps(events, indent=2, ensure_ascii=False).encode("utf-8")
            st.download_button(
                "📄 Export Event Log (JSON)",
                data=json_bytes,
                file_name=f"events_export_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True,
            )

    st.divider()
    st.subheader("📂 Current Schema")
    st.json(schema)


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    page_key = _render_sidebar()

    pages = {
        "stock":         page_stock,
        "add_item":      page_add_item,
        "record_change": page_record_change,
        "history":       page_history,
        "reports":       page_reports,
        "git_sync":      page_git_sync,
        "settings":      page_settings,
    }
    pages.get(page_key, page_stock)()


if __name__ == "__main__":
    main()
