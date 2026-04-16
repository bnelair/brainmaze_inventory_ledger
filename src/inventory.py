"""
Core Event-Sourcing Inventory Engine for Brainmaze Inventory Ledger.

All state changes are recorded as immutable, append-only events stored in a
newline-delimited JSON file (JSONL).  Current stock is derived by replaying
every event from the beginning of time, guaranteeing a full audit trail.

Event types
-----------
ITEM_CREATED   – registers a new item and sets its initial quantity
STOCK_CHANGED  – records a positive or negative quantity delta
ITEM_UPDATED   – updates any non-quantity metadata field
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from ulid import ULID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
EVENT_ITEM_CREATED = "ITEM_CREATED"
EVENT_STOCK_CHANGED = "STOCK_CHANGED"
EVENT_ITEM_UPDATED = "ITEM_UPDATED"

# Fields that should never be overwritten by ITEM_UPDATED payload keys
_SYSTEM_FIELDS = {"researcher", "reason"}


class InventoryLedger:
    """
    Event-sourced inventory management engine.

    Parameters
    ----------
    data_dir : str | Path
        Directory where ``events.jsonl`` lives.  Created automatically.
    """

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.data_dir / "events.jsonl"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_ulid() -> str:
        return str(ULID())

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_event(self, event: Dict[str, Any]) -> None:
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _load_events(self) -> List[Dict[str, Any]]:
        if not self.events_file.exists():
            return []
        events: List[Dict[str, Any]] = []
        with self.events_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Skipping malformed event line in %s: %s — %r",
                            self.events_file,
                            exc,
                            line[:120],
                        )
                        continue
        return events

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def add_item(
        self,
        item_name: str,
        initial_quantity: int,
        researcher: str,
        reason: str,
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        """Register a new inventory item and record its initial stock."""
        item_id = self._new_ulid()
        event: Dict[str, Any] = {
            "id": self._new_ulid(),
            "item_id": item_id,
            "timestamp": self._now_iso(),
            "type": EVENT_ITEM_CREATED,
            "payload": {
                "item_name": item_name,
                "quantity": int(initial_quantity),
                "researcher": researcher,
                "reason": reason,
                **extra_fields,
            },
        }
        self._append_event(event)
        return event

    def record_change(
        self,
        item_id: str,
        qty_delta: int,
        researcher: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Record a positive or negative quantity change for an existing item."""
        event: Dict[str, Any] = {
            "id": self._new_ulid(),
            "item_id": item_id,
            "timestamp": self._now_iso(),
            "type": EVENT_STOCK_CHANGED,
            "payload": {
                "qty_delta": int(qty_delta),
                "researcher": researcher,
                "reason": reason,
            },
        }
        self._append_event(event)
        return event

    def update_item_metadata(
        self,
        item_id: str,
        researcher: str,
        reason: str,
        **updated_fields: Any,
    ) -> Dict[str, Any]:
        """Update non-quantity metadata for an existing item."""
        event: Dict[str, Any] = {
            "id": self._new_ulid(),
            "item_id": item_id,
            "timestamp": self._now_iso(),
            "type": EVENT_ITEM_UPDATED,
            "payload": {
                "researcher": researcher,
                "reason": reason,
                **updated_fields,
            },
        }
        self._append_event(event)
        return event

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_current_stock(self) -> pd.DataFrame:
        """Replay all events and return current inventory as a DataFrame."""
        items: Dict[str, Dict[str, Any]] = {}

        for event in self._load_events():
            item_id: str = event.get("item_id", "")
            if not item_id:
                continue

            etype: str = event.get("type", "")
            payload: Dict[str, Any] = event.get("payload", {})
            ts: str = event.get("timestamp", "")

            if etype == EVENT_ITEM_CREATED:
                items[item_id] = {
                    "item_id": item_id,
                    "item_name": payload.get("item_name", ""),
                    "quantity": int(payload.get("quantity", 0)),
                    "unit": payload.get("unit", "pcs"),
                    "category": payload.get("category", ""),
                    "location": payload.get("location", ""),
                    "supplier": payload.get("supplier", ""),
                    "item_id_label": payload.get("item_id_label", ""),
                    "notes": payload.get("notes", ""),
                    "created_at": ts,
                    "last_updated": ts,
                    "created_by": payload.get("researcher", ""),
                }
                # Carry any additional custom fields from payload
                for k, v in payload.items():
                    if k not in items[item_id]:
                        items[item_id][k] = v

            elif etype == EVENT_STOCK_CHANGED and item_id in items:
                items[item_id]["quantity"] += int(payload.get("qty_delta", 0))
                items[item_id]["last_updated"] = ts

            elif etype == EVENT_ITEM_UPDATED and item_id in items:
                for k, v in payload.items():
                    if k not in _SYSTEM_FIELDS:
                        items[item_id][k] = v
                items[item_id]["last_updated"] = ts

        if not items:
            return pd.DataFrame()

        return pd.DataFrame(list(items.values()))

    def record_batch_changes(
        self,
        changes: List[Dict[str, Any]],
        researcher: str,
        batch_reason: str,
    ) -> List[Dict[str, Any]]:
        """
        Record multiple stock changes belonging to the same batch/order.

        Parameters
        ----------
        changes : list of dict
            Each dict must have ``item_id`` (str) and ``qty_delta`` (int).
            An optional per-item ``reason`` key overrides ``batch_reason``.
        researcher : str
            Display name of the logged-in user performing the batch.
        batch_reason : str
            Shared reason / order reference for the whole batch.

        Returns
        -------
        list of event dicts
        """
        batch_id = self._new_ulid()
        events: List[Dict[str, Any]] = []
        ts = self._now_iso()

        for change in changes:
            event: Dict[str, Any] = {
                "id":        self._new_ulid(),
                "item_id":   change["item_id"],
                "timestamp": ts,
                "type":      EVENT_STOCK_CHANGED,
                "payload": {
                    "qty_delta":    int(change["qty_delta"]),
                    "researcher":   researcher,
                    "reason":       change.get("reason", batch_reason),
                    "batch_id":     batch_id,
                    "batch_reason": batch_reason,
                },
            }
            self._append_event(event)
            events.append(event)

        return events

    def add_batch_items(
        self,
        items: List[Dict[str, Any]],
        researcher: str,
        batch_reason: str,
    ) -> List[Dict[str, Any]]:
        """
        Register multiple new inventory items in one operation.

        Parameters
        ----------
        items : list of dict
            Each dict must have ``item_name`` (str) and ``quantity`` (int).
            Additional keys become extra fields on the item.
        researcher : str
            Display name of the logged-in user.
        batch_reason : str
            Shared reason / order reference.

        Returns
        -------
        list of ITEM_CREATED event dicts
        """
        batch_id = self._new_ulid()
        events: List[Dict[str, Any]] = []
        ts = self._now_iso()

        for item in items:
            item_id = self._new_ulid()
            payload: Dict[str, Any] = {
                "item_name": item.get("item_name", "").strip(),
                "quantity":  int(item.get("quantity", 0)),
                "researcher": researcher,
                "reason":    item.get("reason", batch_reason),
                "batch_id":  batch_id,
                "batch_reason": batch_reason,
            }
            # Carry any additional fields (custom schema fields etc.)
            for k, v in item.items():
                if k not in ("item_name", "quantity", "researcher", "reason"):
                    payload[k] = v

            event: Dict[str, Any] = {
                "id":        self._new_ulid(),
                "item_id":   item_id,
                "timestamp": ts,
                "type":      EVENT_ITEM_CREATED,
                "payload":   payload,
            }
            self._append_event(event)
            events.append(event)

        return events

    def transfer_quantity(
        self,
        source_item_id: str,
        qty: int,
        destination_location: str,
        researcher: str,
        reason: str,
        batch_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Transfer ``qty`` units of an item to a different storage location.

        If an item with the same name already exists at the destination
        location, its stock is incremented via ``STOCK_CHANGED``.  Otherwise
        a new item record is created there (``ITEM_CREATED``) copying all
        metadata from the source item.

        Parameters
        ----------
        source_item_id : str
        qty : int
            Number of units to move (must be > 0).
        destination_location : str
        researcher : str
        reason : str
        batch_id : str, optional
            Shared batch identifier to group transfer events.

        Returns
        -------
        list of event dicts
        """
        ts = self._now_iso()

        if qty <= 0:
            raise ValueError(f"Transfer qty must be > 0, got {qty!r}.")

        current_stock = self.get_current_stock()

        if current_stock.empty:
            raise ValueError("Inventory is empty — no items available to transfer.")
        if "item_id" not in current_stock.columns:
            raise ValueError(
                "Inventory data is missing the 'item_id' column; the event log may be corrupt."
            )

        source_rows = current_stock[current_stock["item_id"] == source_item_id]
        if source_rows.empty:
            raise ValueError(f"Source item '{source_item_id}' not found.")

        source = source_rows.iloc[0]
        source_name = str(source.get("item_name", ""))
        source_location = str(source.get("location", ""))
        available = int(source.get("quantity", 0))
        if qty > available:
            raise ValueError(
                f"Cannot transfer {qty} units of '{source_name}': only {available} available."
            )

        events: List[Dict[str, Any]] = []

        # 1. Deduct from source
        deduct_payload: Dict[str, Any] = {
            "qty_delta": -int(qty),
            "researcher": researcher,
            "reason": reason,
            "transfer_to": destination_location,
        }
        if batch_id:
            deduct_payload["batch_id"] = batch_id
        deduct_event: Dict[str, Any] = {
            "id": self._new_ulid(),
            "item_id": source_item_id,
            "timestamp": ts,
            "type": EVENT_STOCK_CHANGED,
            "payload": deduct_payload,
        }
        self._append_event(deduct_event)
        events.append(deduct_event)

        # 2. Find existing destination item or create a new one
        dest_rows = current_stock[
            (current_stock["item_name"] == source_name)
            & (current_stock["location"] == destination_location)
        ]

        if not dest_rows.empty:
            dest_item_id = str(dest_rows.iloc[0]["item_id"])
            add_payload: Dict[str, Any] = {
                "qty_delta": int(qty),
                "researcher": researcher,
                "reason": reason,
                "transfer_from": source_location,
            }
            if batch_id:
                add_payload["batch_id"] = batch_id
            add_event: Dict[str, Any] = {
                "id": self._new_ulid(),
                "item_id": dest_item_id,
                "timestamp": ts,
                "type": EVENT_STOCK_CHANGED,
                "payload": add_payload,
            }
            self._append_event(add_event)
            events.append(add_event)
        else:
            new_item_id = self._new_ulid()
            create_payload: Dict[str, Any] = {
                "item_name": source_name,
                "quantity": int(qty),
                "researcher": researcher,
                "reason": reason,
                "location": destination_location,
                "transfer_from": source_location,
            }
            if batch_id:
                create_payload["batch_id"] = batch_id
            for field in ("unit", "category", "supplier", "item_id_label", "notes"):
                val = source.get(field, "")
                if val:
                    create_payload[field] = val
            create_event: Dict[str, Any] = {
                "id": self._new_ulid(),
                "item_id": new_item_id,
                "timestamp": ts,
                "type": EVENT_ITEM_CREATED,
                "payload": create_payload,
            }
            self._append_event(create_event)
            events.append(create_event)

        return events

    def batch_transfer(
        self,
        transfers: List[Dict[str, Any]],
        researcher: str,
        batch_reason: str,
    ) -> List[Dict[str, Any]]:
        """
        Transfer multiple item quantities to different locations in one operation.

        Parameters
        ----------
        transfers : list of dict
            Each dict must have ``source_item_id`` (str), ``qty`` (int), and
            ``destination_location`` (str).  An optional ``reason`` key
            overrides ``batch_reason`` for that row.
        researcher : str
        batch_reason : str

        Returns
        -------
        list of all event dicts generated
        """
        batch_id = self._new_ulid()
        all_events: List[Dict[str, Any]] = []
        for t in transfers:
            row_events = self.transfer_quantity(
                source_item_id=t["source_item_id"],
                qty=int(t["qty"]),
                destination_location=t["destination_location"],
                researcher=researcher,
                reason=str(t.get("reason") or batch_reason),
                batch_id=batch_id,
            )
            all_events.extend(row_events)
        return all_events

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_event_history(self) -> List[Dict[str, Any]]:
        """Return all events in chronological order."""
        return self._load_events()

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Find a specific event by its ULID string."""
        for event in self._load_events():
            if event.get("id") == event_id:
                return event
        return None

    def get_item_history(self, item_id: str) -> List[Dict[str, Any]]:
        """Return all events belonging to a specific item."""
        return [e for e in self._load_events() if e.get("item_id") == item_id]

    def get_item_names(self) -> Dict[str, str]:
        """Return a mapping of ``item_id → item_name`` for all known items."""
        names: Dict[str, str] = {}
        for event in self._load_events():
            if event.get("type") == EVENT_ITEM_CREATED:
                names[event["item_id"]] = event["payload"]["item_name"]
            elif event.get("type") == EVENT_ITEM_UPDATED:
                if "item_name" in event.get("payload", {}):
                    names[event["item_id"]] = event["payload"]["item_name"]
        return names
