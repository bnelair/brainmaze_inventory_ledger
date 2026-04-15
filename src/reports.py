"""
PDF Report Generation for Brainmaze Inventory Ledger.

Uses fpdf2 to produce two document types:

1. **Stock Sheet** – landscape A4 table of current inventory, suitable for
   printing and posting on closet doors / bin labels.
2. **Change Slip** – single-page confirmation document for one transaction,
   with ULID, item name, quantity change, reason, and dual signature lines
   for researcher and supervisor.
3. **Item History** – full chronological change log for a single item.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fpdf import FPDF


# ---------------------------------------------------------------------------
# Base PDF class
# ---------------------------------------------------------------------------

class _LabPDF(FPDF):
    """FPDF subclass that adds a branded header and page-numbering footer."""

    def __init__(self, project_name: str = "Brainmaze Inventory", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_name = project_name

    def header(self) -> None:
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(30, 64, 120)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, self.project_name, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}  |  Generated: {ts}  |  CONFIDENTIAL", align="C")
        self.set_text_color(0, 0, 0)


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates printable PDF documents for the inventory ledger."""

    # Column display configuration for the stock table
    _STOCK_COLS = [
        ("item_name",       "Item Name",    55),
        ("quantity",        "Qty",          15),
        ("unit",            "Unit",         15),
        ("category",        "Category",     28),
        ("location",        "Location",     33),
        ("min_stock_level", "Min Stock",    18),
        ("supplier",        "Supplier",     38),
        ("catalog_number",  "Catalog #",    33),
    ]

    def __init__(self, project_name: str = "Brainmaze Inventory") -> None:
        self.project_name = project_name

    # ------------------------------------------------------------------
    # 1. Stock sheet
    # ------------------------------------------------------------------

    def generate_stock_pdf(self, df: pd.DataFrame) -> bytes:
        """
        Create a landscape A4 stock-level table.

        The table highlights rows where quantity ≤ min_stock_level in red.
        A signature / posting line is added at the bottom.

        Returns
        -------
        bytes
            Raw PDF bytes, ready for ``st.download_button``.
        """
        pdf = _LabPDF(project_name=self.project_name, orientation="L")
        pdf.alias_nb_pages()
        pdf.add_page()

        # ---- title block -----------------------------------------------
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Current Stock Report", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(
            0, 6,
            f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        if df.empty:
            pdf.set_font("Helvetica", "I", 12)
            pdf.cell(0, 10, "No inventory items found.", align="C")
            return bytes(pdf.output())

        # ---- determine which columns are present ----------------------
        available = [(col, label, width) for col, label, width in self._STOCK_COLS if col in df.columns]

        # Scale widths proportionally to fill the printable area
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        total_w = sum(w for _, _, w in available)
        scale = page_w / total_w if total_w > 0 else 1.0
        col_data = [(col, label, round(width * scale, 1)) for col, label, width in available]

        row_h = 8.0

        # ---- table header row -----------------------------------------
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(200, 220, 255)
        for _, label, width in col_data:
            pdf.cell(width, row_h, label, border=1, align="C", fill=True)
        pdf.ln()

        # ---- table data rows ------------------------------------------
        pdf.set_font("Helvetica", "", 8)
        for i, (_, row) in enumerate(df.iterrows()):
            qty = row.get("quantity", 0)
            min_stock = row.get("min_stock_level", 0)

            low = (
                pd.notna(min_stock)
                and int(min_stock) > 0
                and int(qty) <= int(min_stock)
            )
            if low:
                pdf.set_fill_color(255, 200, 200)
            elif i % 2 == 0:
                pdf.set_fill_color(245, 248, 255)
            else:
                pdf.set_fill_color(255, 255, 255)

            fill = low or (i % 2 == 0)
            for col, _, width in col_data:
                val = row.get(col, "")
                val = "" if pd.isna(val) else str(val)
                pdf.cell(width, row_h, val, border=1, fill=fill)
            pdf.ln()

        # ---- summary ---------------------------------------------------
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 8, f"Total Items: {len(df)}", new_x="LMARGIN", new_y="NEXT")

        if "min_stock_level" in df.columns and "quantity" in df.columns:
            low_df = df[(df["min_stock_level"] > 0) & (df["quantity"] <= df["min_stock_level"])]
            if not low_df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.cell(
                    0, 8,
                    f"\u26a0  Low-Stock Alert: {len(low_df)} item(s) at or below minimum threshold \u2014 reorder required",
                    new_x="LMARGIN", new_y="NEXT",
                )
                pdf.set_text_color(0, 0, 0)

        # ---- physical posting / verification line ----------------------
        pdf.ln(10)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(80, 8, "Verified by: _________________________")
        pdf.cell(60, 8, "Date: ____________________")
        pdf.cell(70, 8, "Posted on bin/closet: ________________")

        return bytes(pdf.output())

    # ------------------------------------------------------------------
    # 2. Change confirmation slip
    # ------------------------------------------------------------------

    def generate_change_slip(
        self,
        event_data: Dict[str, Any],
        item_name: str = "",
    ) -> bytes:
        """
        Create a single-page confirmation slip for one transaction.

        The slip includes: ULID, item name, transaction type, timestamp,
        quantity change, researcher name, reason, and two signature lines.

        Returns
        -------
        bytes
            Raw PDF bytes.
        """
        pdf = _LabPDF(project_name=self.project_name)
        pdf.alias_nb_pages()
        pdf.add_page()

        payload = event_data.get("payload", {})
        etype = event_data.get("type", "")

        # ---- document title -------------------------------------------
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, "Inventory Change Confirmation Slip", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # ---- helper: draw one labelled field row ----------------------
        lbl_w, val_w, row_h = 62.0, 118.0, 10.0

        def field(label: str, value: str, value_bold: bool = False) -> None:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(235, 242, 255)
            pdf.cell(lbl_w, row_h, label + ":", border=1, fill=True)
            pdf.set_font("Helvetica", "B" if value_bold else "", 10)
            pdf.cell(val_w, row_h, str(value), border=1, new_x="LMARGIN", new_y="NEXT")

        field("Transaction ID (ULID)", event_data.get("id", ""), value_bold=True)
        field("Item ID", event_data.get("item_id", ""))
        field("Item Name", item_name or payload.get("item_name", "—"))
        field("Transaction Type", etype.replace("_", " ").title())

        ts_raw = event_data.get("timestamp", "")
        ts_display = ts_raw[:19].replace("T", " ") + " UTC" if ts_raw else "—"
        field("Timestamp (UTC)", ts_display)

        if etype == "STOCK_CHANGED":
            delta = int(payload.get("qty_delta", 0))
            prefix = "+" if delta >= 0 else ""
            field("Quantity Change", f"{prefix}{delta}", value_bold=True)
        elif etype == "ITEM_CREATED":
            field("Initial Quantity", str(payload.get("quantity", 0)), value_bold=True)

        field("Researcher / Responsible", payload.get("researcher", "—"))

        # ---- reason (may span multiple lines) -------------------------
        reason = payload.get("reason", "—")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(235, 242, 255)
        pdf.cell(lbl_w, row_h, "Reason / Notes:", border=1, fill=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(val_w, row_h, reason, border=1, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(14)

        # ---- signature section ----------------------------------------
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(210, 225, 255)
        pdf.cell(0, 10, "Authorization & Signatures", border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        sig_w = (pdf.w - pdf.l_margin - pdf.r_margin - 10) / 2
        pdf.cell(sig_w, 22, "", border=1)
        pdf.cell(10, 22, "")
        pdf.cell(sig_w, 22, "", border=1, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(sig_w, 6, "Researcher Signature / Date", align="C")
        pdf.cell(10, 6, "")
        pdf.cell(sig_w, 6, "Supervisor Signature / Date", align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(128, 128, 128)
        pdf.cell(
            0, 6,
            "This document is an official Brainmaze Inventory change record. Please sign and retain for physical filing.",
            align="C",
        )

        return bytes(pdf.output())

    # ------------------------------------------------------------------
    # 3. Item history report
    # ------------------------------------------------------------------

    def generate_item_history_pdf(
        self,
        events: List[Dict[str, Any]],
        item_name: str,
        df_stock: Optional[pd.DataFrame] = None,
    ) -> bytes:
        """
        Generate a chronological history report for one item.

        Returns
        -------
        bytes
            Raw PDF bytes.
        """
        pdf = _LabPDF(project_name=self.project_name)
        pdf.alias_nb_pages()
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, f"Item History: {item_name}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(
            0, 6,
            f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        # Current stock summary banner
        if df_stock is not None and not df_stock.empty and "item_name" in df_stock.columns:
            match = df_stock[df_stock["item_name"] == item_name]
            if not match.empty:
                item_row = match.iloc[0]
                qty = item_row.get("quantity", 0)
                unit = item_row.get("unit", "")
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_fill_color(200, 230, 200)
                pdf.cell(
                    0, 10, f"Current Stock: {qty} {unit}",
                    border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT",
                )
                pdf.ln(4)

        if not events:
            pdf.set_font("Helvetica", "I", 11)
            pdf.cell(0, 10, "No history available.", align="C")
            return bytes(pdf.output())

        # History table
        col_defs = [
            ("Timestamp", 50),
            ("Type", 38),
            ("Researcher", 42),
            ("Qty +/-", 18),
            ("Reason", 52),
        ]
        row_h = 8.0

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(200, 220, 255)
        for label, width in col_defs:
            pdf.cell(width, row_h, label, border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for i, event in enumerate(events):
            payload = event.get("payload", {})
            ts = event.get("timestamp", "")[:19].replace("T", " ")
            etype = event.get("type", "").replace("_", " ").title()
            researcher = payload.get("researcher", "")
            if event.get("type") == "STOCK_CHANGED":
                delta = int(payload.get("qty_delta", 0))
                qty_str = f"+{delta}" if delta >= 0 else str(delta)
            else:
                qty_str = str(payload.get("quantity", ""))
            reason = (payload.get("reason", "") or "")[:55]

            fill = i % 2 == 0
            pdf.set_fill_color(245, 248, 255 if fill else 255)
            for val, (_, width) in zip([ts, etype, researcher, qty_str, reason], col_defs):
                pdf.cell(width, row_h, str(val), border=1, fill=fill)
            pdf.ln()

        return bytes(pdf.output())
