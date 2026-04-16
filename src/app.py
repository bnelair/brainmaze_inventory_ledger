"""
Brainmaze Inventory Ledger – Streamlit Application
===================================================
A full-featured, event-sourced inventory management system designed for
research laboratories.

Authentication
--------------
All users must log in before accessing any page.  New users may self-register
and will be placed in a *pending* state until an admin approves their account.
The researcher name on every operation is automatically taken from the
logged-in account — no manual entry required.

Pages (role-gated)
------------------
All roles
  📦 Current Stock   – live inventory with PDF export
  📜 Event History   – immutable audit trail
  🖨️ Print Reports   – download stock sheets and item histories

Read & Write + Admin
  ➕ Add Item        – register a single new item
  📦 Batch Add       – add many items at once (CSV or table editor)
  🔄 Record Change   – single-item quantity change
  📦 Batch Change    – apply one operation to many items at once

Admin only
  ☁️ Git Sync        – commit, push, pull inventory data
  ⚙️ Project Settings – rename project, categories & custom columns
  🗂️ Projects        – create / delete projects
  👥 Users           – approve pending registrations, manage roles

Run with:
    streamlit run src/app.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from auth import (  # noqa: E402
    AuthManager,
    ROLE_ADMIN,
    ROLE_READWRITE,  # noqa: F401
    ROLE_LABELS,
)
from git_manager import GitManager   # noqa: E402
from inventory import InventoryLedger  # noqa: E402
from projects import ProjectManager  # noqa: E402
from reports import ReportGenerator  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports"))

# ---------------------------------------------------------------------------
# Page config  – must be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Brainmaze Inventory Ledger",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help":     "https://github.com/bnelair/brainmaze_inventory_ledger",
        "Report a bug": "https://github.com/bnelair/brainmaze_inventory_ledger/issues",
        "About":        "Brainmaze Inventory Ledger – event-sourced lab inventory.",
    },
)

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
        .main-header  { font-size:2rem; font-weight:700; color:#1e4078; margin-bottom:0; }
        .sub-header   { font-size:1rem; color:#555; margin-top:0; margin-bottom:1rem; }
        .badge-ok     { background:#d4edda; color:#155724; padding:2px 8px;
                        border-radius:12px; font-size:.8rem; }
        .badge-warn   { background:#fff3cd; color:#856404; padding:2px 8px;
                        border-radius:12px; font-size:.8rem; }
        .badge-error  { background:#f8d7da; color:#721c24; padding:2px 8px;
                        border-radius:12px; font-size:.8rem; }
        div[data-testid="stMetricValue"] { font-size:1.6rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached singletons
# ---------------------------------------------------------------------------

@st.cache_resource
def _auth(data_dir: str) -> AuthManager:
    return AuthManager(data_dir=data_dir)


@st.cache_resource
def _projects(data_dir: str) -> ProjectManager:
    return ProjectManager(data_dir=data_dir)


@st.cache_resource
def _ledger(project_data_dir: str) -> InventoryLedger:
    return InventoryLedger(data_dir=project_data_dir)


@st.cache_resource
def _git(data_dir: str) -> GitManager:
    return GitManager(data_dir=data_dir)


def _auth_mgr() -> AuthManager:
    return _auth(str(DATA_DIR))


def _proj_mgr() -> ProjectManager:
    return _projects(str(DATA_DIR))


def _current_ledger() -> InventoryLedger:
    proj_dir = _proj_mgr().get_project_data_dir(st.session_state["project_id"])
    return _ledger(str(proj_dir))


def _reporter() -> ReportGenerator:
    schema = _proj_mgr().get_schema(st.session_state["project_id"])
    return ReportGenerator(project_name=schema.get("project_name", "Brainmaze Inventory"))


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def _user() -> Dict[str, Any]:
    return st.session_state.get("user", {})


def _role() -> str:
    return _user().get("role", "readonly")


def _display_name() -> str:
    return _user().get("display_name", _user().get("username", ""))


def _can_write() -> bool:
    return AuthManager.can_write(_role())


def _is_admin() -> bool:
    return AuthManager.is_admin(_role())


# ---------------------------------------------------------------------------
# Utility
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


def _schema() -> Dict[str, Any]:
    return _proj_mgr().get_schema(st.session_state["project_id"])


def _category_options() -> List[str]:
    return _schema().get("category_options", ["Other"])


def _location_options() -> List[str]:
    return _schema().get("location_options", ["Other"])


def _custom_fields() -> List[Dict[str, Any]]:
    return _schema().get("custom_fields", [])


def _rerun_clear() -> None:
    st.cache_resource.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Dynamic custom-field form helpers
# ---------------------------------------------------------------------------

def _render_custom_field_inputs(prefix: str = "") -> Dict[str, Any]:
    """Render widgets for each project custom field and return {name: value}."""
    values: Dict[str, Any] = {}
    for field in _custom_fields():
        fname = field.get("name", "")
        label = field.get("label", fname)
        ftype = field.get("type", "text")
        default = field.get("default", "")
        star = " *" if field.get("required") else ""
        key = f"{prefix}_{fname}"

        if ftype == "select":
            opts = field.get("options", [])
            idx = opts.index(default) if default in opts else 0
            values[fname] = st.selectbox(label + star, opts, index=idx, key=key)
        elif ftype == "number":
            values[fname] = st.number_input(
                label + star, value=float(default) if default != "" else 0.0, key=key
            )
        elif ftype == "checkbox":
            values[fname] = st.checkbox(label, value=bool(default), key=key)
        else:
            values[fname] = st.text_input(label + star, value=str(default), key=key)
    return values


def _validate_custom_fields(values: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for field in _custom_fields():
        if field.get("required"):
            v = values.get(field["name"], "")
            if v == "" or v is None:
                errors.append(f"'{field.get('label', field['name'])}' is required.")
    return errors


# ===========================================================================
# AUTH PAGES
# ===========================================================================

def page_setup_wizard() -> None:
    """First-run page shown when no users exist at all."""
    st.markdown("## 🔐 First-Run Setup")
    st.info(
        "No users exist yet. Create the **administrator** account to get started."
    )
    with st.form("setup_form"):
        username = st.text_input("Admin Username *")
        display  = st.text_input("Display Name", placeholder="e.g., Dr. Alice Smith")
        pw1 = st.text_input("Password *", type="password")
        pw2 = st.text_input("Confirm Password *", type="password")
        go  = st.form_submit_button("🚀 Create Admin Account", type="primary")

    if go:
        errors: List[str] = []
        if not username.strip():
            errors.append("Username is required.")
        if pw1 != pw2:
            errors.append("Passwords do not match.")
        for e in errors:
            st.error(e)
        if not errors:
            ok, msg = _auth_mgr().create_user(
                username=username.strip(),
                password=pw1,
                role=ROLE_ADMIN,
                display_name=display.strip() or username.strip(),
                active=True,
            )
            if ok:
                _proj_mgr().create_project(
                    name="Default Inventory",
                    description="Default project created during first-run setup.",
                    created_by=username.strip(),
                )
                st.success("✅ Admin account created. Please log in.")
                st.cache_resource.clear()
                st.rerun()
            else:
                st.error(msg)


def page_login() -> None:
    """Login / Register page shown to unauthenticated visitors."""
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown(
            "<h1 style='text-align:center;color:#1e4078;'>🧪 Brainmaze Inventory</h1>",
            unsafe_allow_html=True,
        )
        tab_login, tab_register = st.tabs(["🔑 Log In", "📝 Register"])

        # ---- Log In -------------------------------------------------------
        with tab_login:
            with st.form("login_form"):
                uname = st.text_input("Username")
                passw = st.text_input("Password", type="password")
                sub   = st.form_submit_button(
                    "Log In", type="primary", use_container_width=True
                )
            if sub:
                user = _auth_mgr().authenticate(uname.strip(), passw)
                if user:
                    st.session_state["user"] = user
                    projects = _proj_mgr().list_projects()
                    if projects:
                        st.session_state["project_id"] = projects[0]["id"]
                    st.rerun()
                else:
                    all_names = {u["username"] for u in _auth_mgr().list_users()}
                    if uname.strip() in all_names:
                        st.error(
                            "Your account is **pending administrator approval**. "
                            "Please contact your admin."
                        )
                    else:
                        st.error("Invalid username or password.")

        # ---- Register ----------------------------------------------------
        with tab_register:
            st.info(
                "After registering, your account must be **approved by an admin** "
                "before you can log in."
            )
            with st.form("register_form"):
                r_uname   = st.text_input("Username *", key="reg_uname")
                r_display = st.text_input("Display Name", placeholder="Your full name")
                r_pw1     = st.text_input("Password *", type="password", key="reg_pw1")
                r_pw2     = st.text_input(
                    "Confirm Password *", type="password", key="reg_pw2"
                )
                r_sub = st.form_submit_button(
                    "📝 Submit Registration", use_container_width=True
                )
            if r_sub:
                if r_pw1 != r_pw2:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = _auth_mgr().register(
                        username=r_uname.strip(),
                        password=r_pw1,
                        display_name=r_display.strip(),
                    )
                    (st.success if ok else st.error)(msg)


# ===========================================================================
# SIDEBAR & NAVIGATION
# ===========================================================================

def _project_selector() -> None:
    projects = _proj_mgr().list_projects()
    if not projects:
        return
    proj_names = {p["id"]: p["name"] for p in projects}
    current_id = st.session_state.get("project_id", projects[0]["id"])
    selected = st.selectbox(
        "📂 Project",
        options=list(proj_names.keys()),
        format_func=lambda pid: proj_names.get(pid, pid),
        index=next((i for i, p in enumerate(projects) if p["id"] == current_id), 0),
        key="project_selector",
    )
    if selected != st.session_state.get("project_id"):
        st.session_state["project_id"] = selected
        st.rerun()


_NAV_ALL = [
    ("📦 Current Stock",  "stock"),
    ("📜 Event History",  "history"),
    ("🖨️ Print Reports",  "reports"),
]
_NAV_RW = [
    ("➕ Add Item",       "add_item"),
    ("📦 Batch Add",      "batch_add"),
    ("🔄 Record Change",  "record_change"),
    ("📦 Batch Change",   "batch_change"),
]
_NAV_ADMIN = [
    ("☁️ Git Sync",        "git_sync"),
    ("⚙️ Project Settings","project_settings"),
    ("🗂️ Projects",        "projects"),
    ("👥 Users",           "users"),
]


def _render_sidebar() -> str:
    with st.sidebar:
        try:
            proj_name = _schema().get("project_name", "Brainmaze Inventory")
        except Exception:
            proj_name = "Brainmaze Inventory"
        st.markdown(f"### 🧪 {proj_name}")
        _project_selector()
        st.caption(
            f"👤 {_display_name()}  ·  {ROLE_LABELS.get(_role(), _role())}"
        )
        st.divider()

        nav_items = list(_NAV_ALL)
        if _can_write():
            nav_items += _NAV_RW
        if _is_admin():
            nav_items += _NAV_ADMIN

        nav_labels = [label for label, _ in nav_items]
        nav_keys   = {label: key for label, key in nav_items}

        selected = st.radio(
            "Navigation",
            nav_labels,
            label_visibility="collapsed",
        )

        st.divider()
        try:
            df_q = _current_ledger().get_current_stock()
            if not df_q.empty:
                c1, c2 = st.columns(2)
                c1.metric("Items", len(df_q))
                c2.metric(
                    "Qty",
                    int(df_q["quantity"].sum()) if "quantity" in df_q.columns else 0,
                )
                if "min_stock_level" in df_q.columns and "quantity" in df_q.columns:
                    low = df_q[
                        (df_q["min_stock_level"] > 0)
                        & (df_q["quantity"] <= df_q["min_stock_level"])
                    ]
                    if not low.empty:
                        st.warning(f"⚠️ **{len(low)}** item(s) below min stock.")
        except Exception:
            pass

        st.divider()
        if st.button("🚪 Log Out", use_container_width=True):
            for k in ["user", "project_id"]:
                st.session_state.pop(k, None)
            st.rerun()

    return nav_keys.get(selected, "stock")


# ===========================================================================
# PAGE: Current Stock
# ===========================================================================

def page_stock() -> None:
    _page_header(
        "📦", "Current Stock",
        "Real-time inventory levels computed from the event ledger.",
    )

    ledger = _current_ledger()
    df = ledger.get_current_stock()

    col_refresh, *_ = st.columns([1, 4])
    if col_refresh.button("🔄 Refresh"):
        _rerun_clear()

    if df.empty:
        st.info("No inventory items yet. Go to **➕ Add Item** to get started.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Items", len(df))
    c2.metric(
        "Total Quantity",
        int(df["quantity"].sum()) if "quantity" in df.columns else 0,
    )
    if "min_stock_level" in df.columns and "quantity" in df.columns:
        low_n = int(
            ((df["min_stock_level"] > 0) & (df["quantity"] <= df["min_stock_level"])).sum()
        )
        c3.metric(
            "⚠️ Low Stock",
            low_n,
            delta=f"-{low_n}" if low_n else None,
            delta_color="inverse",
        )
    if "category" in df.columns:
        c4.metric("Categories", int(df["category"].nunique()))

    st.divider()

    fc1, fc2, fc3 = st.columns([2, 1, 1])
    with fc1:
        search = st.text_input("🔍 Search", placeholder="Filter by any field…")
    with fc2:
        cat_opts = ["All"] + (
            sorted(df["category"].dropna().unique().tolist())
            if "category" in df.columns
            else []
        )
        cat_filter = st.selectbox("Category", cat_opts)
    with fc3:
        low_only = st.checkbox("Low Stock Only")

    filtered = df.copy()
    if search:
        mask = filtered.apply(
            lambda r: search.lower() in " ".join(str(v) for v in r).lower(), axis=1
        )
        filtered = filtered[mask]
    if cat_filter != "All" and "category" in filtered.columns:
        filtered = filtered[filtered["category"] == cat_filter]
    if low_only and "min_stock_level" in filtered.columns:
        filtered = filtered[
            (filtered["min_stock_level"] > 0)
            & (filtered["quantity"] <= filtered["min_stock_level"])
        ]

    core_order = [
        "item_name", "quantity", "unit", "category", "location",
        "min_stock_level", "supplier", "item_id_label", "last_updated",
    ]
    custom_names = [
        f["name"] for f in _custom_fields() if f["name"] in filtered.columns
    ]
    display_cols = [c for c in core_order if c in filtered.columns] + custom_names
    col_labels: Dict[str, str] = {
        "item_name": "Item Name", "quantity": "Qty", "unit": "Unit",
        "category": "Category", "location": "Location",
        "min_stock_level": "Min Stock", "supplier": "Supplier",
        "item_id_label": "ID", "last_updated": "Last Updated",
    }
    for f in _custom_fields():
        col_labels[f["name"]] = f.get("label", f["name"])

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
    pdf_bytes = _reporter().generate_stock_pdf(filtered, custom_fields=_custom_fields())
    st.download_button(
        "🖨️ Download Stock Sheet (PDF)",
        data=pdf_bytes,
        file_name=f"stock_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mime="application/pdf",
        type="primary",
    )


# ===========================================================================
# PAGE: Add Item
# ===========================================================================

def page_add_item() -> None:
    _page_header("➕", "Add Item",
                 "Register a new inventory item and record its initial stock.")

    researcher = _display_name()
    st.info(f"👤 Adding as: **{researcher}**")

    with st.form("add_item_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            item_name   = st.text_input("Item Name *", placeholder="e.g., Ethanol 96%")
            initial_qty = st.number_input("Initial Quantity *", min_value=0, value=0, step=1)
        with col2:
            unit     = st.text_input("Unit", value="pcs", placeholder="pcs · mL · mg · boxes")
            category = st.selectbox("Category", _category_options())

        col3, col4 = st.columns(2)
        with col3:
            location = st.selectbox("Storage Location", _location_options())
            supplier = st.text_input("Supplier", placeholder="e.g., Sigma-Aldrich")
        with col4:
            item_id_label = st.text_input("ID",
                                           placeholder="e.g., SKU-001, CAS-64-17-5")

        notes = st.text_area("Notes", placeholder="Optional additional notes…")

        custom_values: Dict[str, Any] = {}
        if _custom_fields():
            st.divider()
            st.subheader("📋 Additional Fields")
            custom_values = _render_custom_field_inputs(prefix="add")

        st.divider()
        reason = st.text_input(
            "Reason *",
            placeholder="e.g., Initial stock entry, Purchased from supplier",
        )
        submitted = st.form_submit_button(
            "✅ Add Item", type="primary", use_container_width=True
        )

    if submitted:
        errors: List[str] = []
        if not item_name.strip():
            errors.append("Item name is required.")
        if not reason.strip():
            errors.append("Reason is required.")
        errors.extend(_validate_custom_fields(custom_values))
        for e in errors:
            st.error(e)
        if not errors:
            event = _current_ledger().add_item(
                item_name=item_name.strip(),
                initial_quantity=int(initial_qty),
                researcher=researcher,
                reason=reason.strip(),
                unit=unit.strip(),
                category=category,
                location=location.strip(),
                supplier=supplier.strip(),
                item_id_label=item_id_label.strip(),
                notes=notes.strip(),
                **custom_values,
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


# ===========================================================================
# PAGE: Batch Add
# ===========================================================================

def page_batch_add() -> None:
    _page_header("📦", "Batch Add Items",
                 "Register multiple new items in a single operation.")

    researcher = _display_name()
    st.info(f"👤 Adding as: **{researcher}**")

    tab_editor, tab_csv = st.tabs(["📝 Table Editor", "📂 CSV Upload"])

    core_col_config: Dict[str, Any] = {
        "item_name": st.column_config.TextColumn("Item Name *", required=True),
        "quantity":  st.column_config.NumberColumn("Qty *", min_value=0, default=0,
                                                    required=True),
        "unit":      st.column_config.TextColumn("Unit", default="pcs"),
        "category":  st.column_config.SelectboxColumn("Category",
                                                       options=_category_options()),
        "location":  st.column_config.SelectboxColumn("Location",
                                                        options=_location_options()),
        "supplier":  st.column_config.TextColumn("Supplier"),
        "item_id_label": st.column_config.TextColumn("ID"),
        "notes":     st.column_config.TextColumn("Notes"),
        "reason":    st.column_config.TextColumn("Reason (overrides batch reason)"),
    }
    for f in _custom_fields():
        core_col_config[f["name"]] = st.column_config.TextColumn(
            f.get("label", f["name"])
        )

    all_col_names = list(core_col_config.keys())

    with tab_editor:
        empty_df = pd.DataFrame(
            [{k: None for k in all_col_names}, {k: None for k in all_col_names}]
        )
        edited = st.data_editor(
            empty_df,
            column_config=core_col_config,
            num_rows="dynamic",
            use_container_width=True,
            key="batch_add_editor",
        )
        batch_reason_e = st.text_input(
            "Batch Reason *",
            placeholder="e.g., Initial stock from supplier order #1234",
            key="batch_reason_editor",
        )
        if st.button("✅ Submit Batch", type="primary", key="batch_submit_editor"):
            valid_items = [
                r for r in edited.dropna(subset=["item_name"]).to_dict("records")
                if str(r.get("item_name", "")).strip()
            ]
            if not valid_items:
                st.error("Enter at least one item with a name.")
            elif not batch_reason_e.strip():
                st.error("Batch reason is required.")
            else:
                events = _current_ledger().add_batch_items(
                    items=valid_items,
                    researcher=researcher,
                    batch_reason=batch_reason_e.strip(),
                )
                st.success(f"✅ **{len(events)}** item(s) added.")
                pdf_bytes = _reporter().generate_batch_slip(
                    events, batch_reason_e.strip(), researcher
                )
                st.download_button(
                    "📥 Download Batch Confirmation (PDF)",
                    data=pdf_bytes,
                    file_name=f"batch_add_{events[0]['payload']['batch_id']}.pdf",
                    mime="application/pdf",
                )

    with tab_csv:
        st.markdown("**1. Download the CSV template:**")
        tmpl_df = pd.DataFrame(columns=all_col_names)
        st.download_button(
            "📥 Download CSV Template",
            data=tmpl_df.to_csv(index=False).encode("utf-8"),
            file_name="batch_add_template.csv",
            mime="text/csv",
        )

        st.markdown("**2. Upload your filled CSV:**")
        uploaded = st.file_uploader("Choose CSV file", type=["csv"],
                                    key="batch_csv_upload")
        if uploaded:
            try:
                df_csv = pd.read_csv(uploaded)
                st.subheader("Preview")
                st.dataframe(df_csv, use_container_width=True, hide_index=True)

                batch_reason_c = st.text_input(
                    "Batch Reason *",
                    placeholder="e.g., Bulk import from supplier",
                    key="batch_reason_csv",
                )
                if st.button("✅ Import CSV", type="primary", key="batch_csv_import"):
                    if "item_name" not in df_csv.columns:
                        st.error("CSV must have an 'item_name' column.")
                    elif not batch_reason_c.strip():
                        st.error("Batch reason is required.")
                    else:
                        items = df_csv.dropna(subset=["item_name"]).to_dict("records")
                        events = _current_ledger().add_batch_items(
                            items=items,
                            researcher=researcher,
                            batch_reason=batch_reason_c.strip(),
                        )
                        st.success(f"✅ **{len(events)}** item(s) imported.")
                        pdf_bytes = _reporter().generate_batch_slip(
                            events, batch_reason_c.strip(), researcher
                        )
                        st.download_button(
                            "📥 Download Import Confirmation (PDF)",
                            data=pdf_bytes,
                            file_name=f"batch_import_{events[0]['payload']['batch_id']}.pdf",
                            mime="application/pdf",
                        )
            except Exception as exc:
                st.error(f"Failed to read CSV: {exc}")


# ===========================================================================
# PAGE: Record Change (single item)
# ===========================================================================

def page_record_change() -> None:
    _page_header("🔄", "Record Change",
                 "Record a quantity change for an existing inventory item.")

    researcher = _display_name()
    st.info(f"👤 Recording as: **{researcher}**")

    ledger = _current_ledger()
    df = ledger.get_current_stock()

    if df.empty:
        st.info("No items in inventory. Add items first using **➕ Add Item**.")
        return

    item_names: Dict[str, str] = df.set_index("item_id")["item_name"].to_dict()
    options = {f"{name}  (ID: {iid})": iid for iid, name in item_names.items()}

    with st.form("record_change_form", clear_on_submit=True):
        selected_label = st.selectbox("Select Item *", list(options.keys()))
        item_id = options[selected_label]

        row_match = df[df["item_id"] == item_id]
        current = row_match.iloc[0] if not row_match.empty else None
        if current is not None:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Current Stock",
                       f"{current['quantity']} {current.get('unit', 'pcs')}")
            mc2.metric("Category",  current.get("category", "—"))
            mc3.metric("Location",  current.get("location", "—"))

        st.divider()
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            change_type = st.selectbox(
                "Change Type",
                ["Add Stock", "Remove Stock", "Set to Exact Value"],
            )
        with dcol2:
            qty_input = st.number_input("Quantity", min_value=0, value=1, step=1)

        delta = 0
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
        reason = st.text_input(
            "Reason *",
            placeholder="e.g., Used in experiment #42, Restocked from supplier",
        )
        submitted = st.form_submit_button(
            "✅ Record Change", type="primary", use_container_width=True
        )

    if submitted:
        errors: List[str] = []
        if not reason.strip():
            errors.append("Reason is required.")
        if delta == 0:
            errors.append("The calculated quantity delta is 0 — no change will be recorded.")
        for e in errors:
            st.error(e)
        if not errors:
            event = ledger.record_change(
                item_id=item_id,
                qty_delta=delta,
                researcher=researcher,
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


# ===========================================================================
# PAGE: Batch Change
# ===========================================================================

def page_batch_change() -> None:
    _page_header("📦", "Batch Stock Change",
                 "Apply the same operation to multiple items in one go.")

    researcher = _display_name()
    st.info(f"👤 Recording as: **{researcher}**")

    ledger = _current_ledger()
    df = ledger.get_current_stock()

    if df.empty:
        st.info("No inventory items yet. Add items first.")
        return

    item_names: Dict[str, str] = df.set_index("item_id")["item_name"].to_dict()

    selected_labels = st.multiselect(
        "Select Items *",
        options=[f"{name}  (ID: {iid})" for iid, name in item_names.items()],
        help="Select one or more items to change.",
    )
    selected_ids: List[str] = []
    for lbl in selected_labels:
        for iid, name in item_names.items():
            if lbl == f"{name}  (ID: {iid})":
                selected_ids.append(iid)
                break

    if selected_ids:
        preview = df[df["item_id"].isin(selected_ids)][
            ["item_name", "quantity", "unit", "category"]
        ].copy()
        preview.columns = ["Item Name", "Current Qty", "Unit", "Category"]
        st.dataframe(preview, use_container_width=True, hide_index=True)

    with st.form("batch_change_form", clear_on_submit=True):
        bc1, bc2 = st.columns(2)
        with bc1:
            change_type = st.selectbox(
                "Operation",
                ["Add Stock", "Remove Stock", "Set to Exact Value"],
            )
        with bc2:
            qty_input = st.number_input("Quantity", min_value=0, value=1, step=1)

        batch_reason = st.text_input(
            "Batch Reason *",
            placeholder="e.g., Weekly usage, Restocked from PO-1234",
        )
        submitted = st.form_submit_button(
            f"✅ Apply to {len(selected_ids)} item(s)",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        errors: List[str] = []
        if not selected_ids:
            errors.append("Please select at least one item.")
        if not batch_reason.strip():
            errors.append("Batch reason is required.")
        for e in errors:
            st.error(e)
        if not errors:
            changes: List[Dict[str, Any]] = []
            for iid in selected_ids:
                cur_qty = int(df[df["item_id"] == iid]["quantity"].iloc[0])
                if change_type == "Add Stock":
                    delta = int(qty_input)
                elif change_type == "Remove Stock":
                    delta = -int(qty_input)
                else:
                    delta = int(qty_input) - cur_qty
                changes.append({"item_id": iid, "qty_delta": delta})

            events = ledger.record_batch_changes(
                changes=changes,
                researcher=researcher,
                batch_reason=batch_reason.strip(),
            )
            st.success(f"✅ **{len(events)}** stock change(s) recorded.")
            pdf_bytes = _reporter().generate_batch_slip(
                events,
                batch_reason.strip(),
                researcher,
                item_names=item_names,
            )
            st.download_button(
                "📥 Download Batch Slip (PDF)",
                data=pdf_bytes,
                file_name=f"batch_change_{events[0]['payload']['batch_id']}.pdf",
                mime="application/pdf",
            )


# ===========================================================================
# PAGE: Event History
# ===========================================================================

def page_history() -> None:
    _page_header("📜", "Event History",
                 "Immutable audit trail of every inventory change.")

    ledger = _current_ledger()
    events = ledger.get_event_history()
    item_names = ledger.get_item_names()

    if not events:
        st.info("No events recorded yet.")
        return

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
            "Qty +/-":        qty_str,
            "Researcher":     payload.get("researcher", ""),
            "Reason":         payload.get("reason", ""),
            "Batch ID":       payload.get("batch_id", ""),
        })

    df_hist = pd.DataFrame(records)
    st.metric("Total Events", len(df_hist))

    fc1, fc2 = st.columns([2, 1])
    with fc1:
        search = st.text_input("🔍 Search history",
                               placeholder="Item, researcher, reason…")
    with fc2:
        type_filter = st.selectbox(
            "Event Type",
            ["All", "Item Created", "Stock Changed", "Item Updated"],
        )

    if search:
        mask = df_hist.apply(
            lambda r: search.lower() in " ".join(str(v) for v in r).lower(), axis=1
        )
        df_hist = df_hist[mask]
    if type_filter != "All":
        df_hist = df_hist[df_hist["Type"].str.lower() == type_filter.lower()]

    st.dataframe(df_hist, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🖨️ Print Slip for a Specific Event")
    eid = st.text_input("Enter Transaction ID (ULID):")
    if eid.strip():
        event = ledger.get_event_by_id(eid.strip())
        if event:
            iid = event.get("item_id", "")
            name = event.get("payload", {}).get("item_name", item_names.get(iid, ""))
            pdf_bytes = _reporter().generate_change_slip(event, name)
            st.download_button(
                "📄 Download Slip (PDF)",
                data=pdf_bytes,
                file_name=f"slip_{eid.strip()}.pdf",
                mime="application/pdf",
                type="primary",
            )
        else:
            st.error("Event not found. Please verify the Transaction ID.")


# ===========================================================================
# PAGE: Print Reports
# ===========================================================================

def page_reports() -> None:
    _page_header("🖨️", "Print Reports",
                 "Generate and download printable PDF documents.")

    ledger = _current_ledger()
    df = ledger.get_current_stock()
    reporter = _reporter()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📋 Full Stock Sheet")
        st.write("Landscape A4 table of all current inventory.")
        if df.empty:
            st.warning("No inventory items to report.")
        else:
            pdf = reporter.generate_stock_pdf(df, custom_fields=_custom_fields())
            st.download_button(
                "📥 Download Full Stock Sheet",
                data=pdf,
                file_name=f"stock_sheet_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

    with col2:
        st.subheader("📦 Item History Report")
        st.write("Chronological change log for a single inventory item.")
        if df.empty:
            st.warning("No inventory items yet.")
        else:
            names = df.set_index("item_id")["item_name"].to_dict()
            sel_name = st.selectbox("Select item", list(names.values()),
                                    key="hist_select")
            target_id = next((k for k, v in names.items() if v == sel_name), None)
            if target_id:
                ev_list = ledger.get_item_history(target_id)
                pdf = reporter.generate_item_history_pdf(ev_list, sel_name, df)
                st.download_button(
                    "📥 Download Item History",
                    data=pdf,
                    file_name=f"history_{sel_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

    st.divider()
    st.subheader("📂 Data Exports")
    ex1, ex2 = st.columns(2)
    with ex1:
        if not df.empty:
            st.download_button(
                "📄 Export Stock (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"stock_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with ex2:
        events_all = ledger.get_event_history()
        if events_all:
            st.download_button(
                "📄 Export Event Log (JSON)",
                data=json.dumps(events_all, indent=2,
                                ensure_ascii=False).encode("utf-8"),
                file_name=f"events_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True,
            )


# ===========================================================================
# PAGE: Git Sync  (admin only)
# ===========================================================================

def page_git_sync() -> None:
    _page_header("☁️", "Git Sync",
                 "Commit, push, and pull inventory data with a remote Git repository.")

    git = _git(str(DATA_DIR))
    status = git.get_status()

    sc1, sc2 = st.columns(2)
    with sc1:
        if status["initialized"]:
            st.success("✅ Git repository initialised")
            st.markdown(f"**Branch:** `{status.get('branch', '—')}`")
            st.markdown(f"**Remote:** `{status.get('remote_url', 'Not configured')}`")
        else:
            st.warning("⚠️ Git repository not yet initialised.")
    with sc2:
        if status.get("has_changes"):
            st.warning(
                f"📝 **{len(status.get('changes', []))}** uncommitted change(s):"
            )
            for ch in status.get("changes", [])[:8]:
                st.code(ch)
        elif status["initialized"]:
            st.success("✅ Working directory clean.")

    st.divider()
    with st.expander("⚙️ Git Configuration",
                     expanded=not status["initialized"]):
        cfg_repo = st.text_input(
            "Repository URL",
            value=os.environ.get("GIT_REPO_URL", git.repo_url or ""),
        )
        c1, c2 = st.columns(2)
        with c1:
            _auth_methods = ["PAT", "SSH", "APP", "BASIC"]
            cfg_auth = st.selectbox(
                "Auth Method", _auth_methods,
                index=(
                    _auth_methods.index(git.auth_method)
                    if git.auth_method in _auth_methods else 0
                ),
            )
            cfg_branch = st.text_input("Branch", value=git.branch)
        with c2:
            if cfg_auth == "BASIC":
                cfg_username = st.text_input(
                    "Username",
                    value=git.username or os.environ.get("GIT_USERNAME", ""),
                )
                cfg_token = st.text_input("Password", type="password")
            elif cfg_auth in ("PAT", "APP"):
                cfg_username = ""
                cfg_token = st.text_input("Token", type="password")
            else:
                cfg_username = ""
                cfg_token = ""
            cfg_name  = st.text_input("Commit Author Name",  value=git.git_user_name)
            cfg_email = st.text_input("Commit Author Email", value=git.git_user_email)

        if st.button("💾 Apply Configuration"):
            git.repo_url    = cfg_repo
            git.auth_method = cfg_auth
            git.username    = cfg_username or git.username
            git.token       = cfg_token or git.token
            git.branch      = cfg_branch
            git.git_user_name  = cfg_name
            git.git_user_email = cfg_email
            if not status["initialized"]:
                ok, msg = git.init_repo()
                (st.success if ok else st.error)(msg)
            if cfg_repo:
                ok, msg = git.setup_remote()
                (st.success if ok else st.error)(msg)

    st.divider()
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        if st.button("📤 Commit", use_container_width=True):
            ok, msg = git.commit_all()
            (st.success if ok else st.error)(msg)
    with ac2:
        if st.button("⬇️ Pull", use_container_width=True):
            ok, msg = git.pull()
            (st.success if ok else st.error)(msg)
    with ac3:
        if st.button("⬆️ Push", use_container_width=True):
            ok, msg = git.push()
            (st.success if ok else st.error)(msg)

    if st.button("🔄 Full Sync (Commit → Pull → Push)", type="primary",
                 use_container_width=True):
        with st.spinner("Syncing…"):
            ok, msg = git.sync()
        (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")

    st.divider()
    with st.expander("🔐 git-crypt – Unlock Encrypted Repository"):
        crypt_key = st.text_input("git-crypt Key (Base64)", type="password")
        if st.button("🔓 Unlock"):
            if crypt_key:
                os.environ["GIT_CRYPT_KEY"] = crypt_key
            ok, msg = git.unlock_git_crypt()
            (st.success if ok else st.error)(msg)

    if status.get("recent_commits"):
        st.divider()
        st.subheader("Recent Commits")
        for c in status["recent_commits"]:
            st.text(c)


# ===========================================================================
# PAGE: Project Settings  (admin only)
# ===========================================================================

def page_project_settings() -> None:
    _page_header("⚙️", "Project Settings",
                 "Configure categories and custom columns for this project.")

    pm = _proj_mgr()
    project_id = st.session_state["project_id"]
    schema = pm.get_schema(project_id)

    with st.form("settings_form"):
        new_name = st.text_input("Project Name",   value=schema.get("project_name", ""))
        new_desc = st.text_input("Description",    value=schema.get("description", ""))
        st.subheader("Category Options")
        cats_text = st.text_area(
            "Categories (one per line)",
            value="\n".join(schema.get("category_options", [])),
            height=180,
        )
        st.subheader("Storage Location Options")
        locs_text = st.text_area(
            "Locations (one per line)",
            value="\n".join(schema.get("location_options", [])),
            height=180,
        )
        saved = st.form_submit_button("💾 Save", type="primary")

    if saved:
        new_cats = [c.strip() for c in cats_text.splitlines() if c.strip()]
        new_locs = [l.strip() for l in locs_text.splitlines() if l.strip()]
        schema["project_name"]     = new_name.strip() or schema.get("project_name", "")
        schema["description"]      = new_desc.strip()
        schema["category_options"] = new_cats
        schema["location_options"] = new_locs
        pm.save_schema(project_id, schema)
        if new_name.strip():
            pm.rename_project(project_id, new_name.strip())
        st.success("✅ Settings saved.")
        _rerun_clear()

    # ---- Custom fields editor ------------------------------------------
    st.divider()
    st.subheader("📋 Custom Columns")
    st.caption(
        "Define extra columns that appear in Add Item / Batch Add forms "
        "and in stock reports."
    )

    existing_fields: List[Dict[str, Any]] = list(schema.get("custom_fields", []))

    with st.expander("➕ Add New Custom Column"):
        with st.form("add_field_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                f_name  = st.text_input("Internal name *",
                                        placeholder="e.g., expiry_date")
                f_label = st.text_input("Display label *",
                                        placeholder="e.g., Expiry Date")
                f_type  = st.selectbox("Type",
                                       ["text", "number", "select", "checkbox"])
            with fc2:
                f_default  = st.text_input("Default value")
                f_required = st.checkbox("Required")
                f_options  = st.text_input(
                    "Options (comma-separated, for 'select' type)",
                    placeholder="Option A, Option B",
                )
            add_field = st.form_submit_button("➕ Add Column")

        if add_field:
            errs: List[str] = []
            if not f_name.strip():
                errs.append("Internal name is required.")
            if not f_label.strip():
                errs.append("Display label is required.")
            safe_name = f_name.strip().lower().replace(" ", "_")
            if any(f["name"] == safe_name for f in existing_fields):
                errs.append(f"Field '{safe_name}' already exists.")
            for err in errs:
                st.error(err)
            if not errs:
                new_field: Dict[str, Any] = {
                    "name":     safe_name,
                    "label":    f_label.strip(),
                    "type":     f_type,
                    "default":  f_default.strip(),
                    "required": f_required,
                }
                if f_type == "select" and f_options.strip():
                    new_field["options"] = [
                        o.strip() for o in f_options.split(",") if o.strip()
                    ]
                existing_fields.append(new_field)
                schema["custom_fields"] = existing_fields
                pm.save_schema(project_id, schema)
                st.success(f"✅ Column '{f_label}' added.")
                st.rerun()

    if existing_fields:
        st.subheader("Existing Custom Columns")
        for i, field in enumerate(existing_fields):
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.markdown(
                f"**{field.get('label', field['name'])}** "
                f"(`{field['name']}`, type: `{field.get('type', 'text')}`)"
            )
            c2.caption(
                f"Default: {field.get('default', '')}  "
                f"{'• required' if field.get('required') else '• optional'}"
            )
            if c3.button("🗑️ Delete", key=f"del_field_{i}"):
                existing_fields.pop(i)
                schema["custom_fields"] = existing_fields
                pm.save_schema(project_id, schema)
                st.rerun()
    else:
        st.info("No custom columns defined for this project.")


# ===========================================================================
# PAGE: Projects  (admin only)
# ===========================================================================

def page_projects() -> None:
    _page_header("🗂️", "Projects",
                 "Create and manage inventory projects.")

    pm = _proj_mgr()
    projects = pm.list_projects()

    st.subheader("Existing Projects")
    for proj in projects:
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.markdown(f"**{proj['name']}**  \n`{proj['id']}`")
        c2.caption(
            f"{proj.get('description', '')}  \n"
            f"Created: {_fmt_ts(proj.get('created_at', ''))}"
        )
        if c3.button("🗑️ Delete", key=f"del_proj_{proj['id']}",
                     disabled=(len(projects) <= 1)):
            ok, msg = pm.delete_project(proj["id"])
            (st.success if ok else st.error)(msg)
            if ok and st.session_state.get("project_id") == proj["id"]:
                st.session_state["project_id"] = pm.list_projects()[0]["id"]
            _rerun_clear()

    st.divider()
    st.subheader("➕ Create New Project")
    with st.form("create_project_form", clear_on_submit=True):
        p_name = st.text_input("Project Name *")
        p_desc = st.text_area("Description", height=80)
        p_sub  = st.form_submit_button("✅ Create Project", type="primary")

    if p_sub:
        if not p_name.strip():
            st.error("Project name is required.")
        else:
            record, err = pm.create_project(
                name=p_name.strip(),
                description=p_desc.strip(),
                created_by=_user()["username"],
            )
            if err:
                st.error(err)
            else:
                st.success(f"✅ Project **{record['name']}** created.")
                _rerun_clear()


# ===========================================================================
# PAGE: User Management  (admin only)
# ===========================================================================

def page_users() -> None:
    _page_header("👥", "User Management",
                 "Approve pending registrations and manage user roles.")

    auth = _auth_mgr()
    current_username = _user()["username"]

    # ---- Pending approvals ----------------------------------------------
    pending = auth.list_pending()
    if pending:
        st.subheader(f"⏳ Pending Approval ({len(pending)})")
        st.warning(
            "These accounts are waiting for your approval before they can log in."
        )
        for u in pending:
            pc1, pc2, pc3, pc4 = st.columns([2, 2, 1, 1])
            pc1.markdown(
                f"**{u['username']}**  \n{u.get('display_name', '')}"
            )
            pc2.caption(f"Registered: {_fmt_ts(u.get('created_at', ''))}")
            if pc3.button("✅ Approve", key=f"approve_{u['username']}"):
                ok, msg = auth.approve_user(u["username"])
                (st.success if ok else st.error)(msg)
                st.rerun()
            if pc4.button("❌ Reject", key=f"reject_{u['username']}"):
                ok, msg = auth.delete_user(u["username"])
                (st.success if ok else st.error)(msg)
                st.rerun()
        st.divider()

    # ---- Active users ---------------------------------------------------
    st.subheader("Active Users")
    active_users = [u for u in auth.list_users() if u["active"]]

    for u in active_users:
        uc1, uc2, uc3, uc4 = st.columns([2, 2, 2, 1])
        uc1.markdown(f"**{u['display_name']}**  \n`{u['username']}`")
        uc2.caption(f"Role: **{ROLE_LABELS.get(u['role'], u['role'])}**")

        is_self = u["username"] == current_username
        new_role = uc3.selectbox(
            "Change role",
            options=list(ROLE_LABELS.keys()),
            format_func=lambda r: ROLE_LABELS[r],
            index=list(ROLE_LABELS.keys()).index(u["role"]),
            key=f"role_{u['username']}",
            disabled=is_self,
            label_visibility="collapsed",
        )
        if new_role != u["role"] and not is_self:
            if uc3.button("Save", key=f"save_role_{u['username']}"):
                ok, msg = auth.update_role(u["username"], new_role)
                (st.success if ok else st.error)(msg)
                st.rerun()

        if not is_self:
            if uc4.button("🗑️", key=f"del_user_{u['username']}",
                          help=f"Delete {u['username']}"):
                ok, msg = auth.delete_user(u["username"])
                (st.success if ok else st.error)(msg)
                st.rerun()

    # ---- Admin: create user directly ------------------------------------
    st.divider()
    st.subheader("➕ Create User (Admin)")
    with st.form("create_user_form", clear_on_submit=True):
        cu1, cu2 = st.columns(2)
        with cu1:
            new_uname   = st.text_input("Username *")
            new_display = st.text_input("Display Name")
        with cu2:
            new_role_sel = st.selectbox(
                "Role", list(ROLE_LABELS.keys()),
                format_func=lambda r: ROLE_LABELS[r],
            )
            new_pw = st.text_input("Password *", type="password")
        cu_sub = st.form_submit_button("✅ Create User", type="primary")

    if cu_sub:
        if not new_uname.strip() or not new_pw:
            st.error("Username and password are required.")
        else:
            ok, msg = auth.create_user(
                username=new_uname.strip(),
                password=new_pw,
                role=new_role_sel,
                display_name=new_display.strip(),
                active=True,
            )
            (st.success if ok else st.error)(msg)

    # ---- Change own password --------------------------------------------
    st.divider()
    st.subheader("🔑 Change My Password")
    with st.form("change_pw_form", clear_on_submit=True):
        cpw1 = st.text_input("New Password *",     type="password", key="cpw1")
        cpw2 = st.text_input("Confirm Password *", type="password", key="cpw2")
        cpw_sub = st.form_submit_button("💾 Change Password")

    if cpw_sub:
        if cpw1 != cpw2:
            st.error("Passwords do not match.")
        else:
            ok, msg = auth.update_password(current_username, cpw1)
            (st.success if ok else st.error)(msg)


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    auth = _auth_mgr()

    # First-run: no users exist at all
    if not auth.has_any_users():
        page_setup_wizard()
        return

    # Not logged in
    if "user" not in st.session_state:
        page_login()
        return

    # Ensure project_id is populated after login
    if "project_id" not in st.session_state:
        projects = _proj_mgr().list_projects()
        if not projects:
            st.error("No projects found. Please contact your administrator.")
            return
        st.session_state["project_id"] = projects[0]["id"]

    page_key = _render_sidebar()

    pages = {
        "stock":            page_stock,
        "add_item":         page_add_item,
        "batch_add":        page_batch_add,
        "record_change":    page_record_change,
        "batch_change":     page_batch_change,
        "history":          page_history,
        "reports":          page_reports,
        "git_sync":         page_git_sync,
        "project_settings": page_project_settings,
        "projects":         page_projects,
        "users":            page_users,
    }

    role = _role()
    write_pages  = {"add_item", "batch_add", "record_change", "batch_change"}
    admin_pages  = {"git_sync", "project_settings", "projects", "users"}

    if page_key in write_pages and not AuthManager.can_write(role):
        st.error("🚫 You do not have permission to access this page.")
        return
    if page_key in admin_pages and not AuthManager.is_admin(role):
        st.error("🚫 This page is for administrators only.")
        return

    pages.get(page_key, page_stock)()


if __name__ == "__main__":
    main()
