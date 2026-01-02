from __future__ import annotations

import argparse
import logging
import os
import textwrap
from typing import List

from blessed import Terminal

from .api_client import SpoolManagerAPI


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename=os.getenv("SPOOL_TUI_LOG", "spooltui.log"),
)
logger = logging.getLogger("spooltui")


DUNGEON_FLAVOR = [
    "You step into the Filament Keep—rows of reels echo like stalactites.",
    "Faint whirs of AMS sentinels guard the treasure slots ahead.",
    "Crates of color and material line the hall; choose your next action wisely.",
]


def wrap(text: str, width: int) -> List[str]:
    return textwrap.wrap(text, width=width) if text else [""]


def prompt_input(term: Terminal, label: str) -> str:
    print(term.clear + term.bold(label))
    print(term.dim("Press Enter when done. ESC cancels."))
    buf: List[str] = []
    with term.cbreak():
        while True:
            key = term.inkey()
            if not key:
                continue
            if key.name == "KEY_ESCAPE":
                return ""
            if key.is_sequence and key.name == "KEY_ENTER":
                print()
                return "".join(buf).strip()
            if key.is_sequence and key.name == "KEY_BACKSPACE":
                if buf:
                    buf.pop()
                    print(term.move_left + " " + term.move_left, end="", flush=True)
                continue
            buf.append(str(key))
            print(key, end="", flush=True)


def render_menu(term: Terminal) -> None:
    print(term.clear + term.bold_underline("Spool Manager Terminal"))
    print(term.bold("Dungeon Trail"))
    for line in DUNGEON_FLAVOR:
        print(term.dim("  " + line))
    print()
    print(term.bold("Choose your path (press key):"))
    print("  1) AMS status overview")
    print("  2) Inventory list")
    print("  3) Spool lookup (ID / QR / RFID)")
    print("  4) Assign slot")
    print("  5) Mark spool opened / back to stock")
    print("  q) Quit")


def _print_lines(term: Terminal, title: str, lines: List[str]) -> None:
    print(term.clear + term.bold(title))
    for line in lines:
        print(line)
    print(term.dim("Press b to go back."))


def display_error(term: Terminal, error: Exception) -> None:
    _print_lines(term, "Something went wrong", [term.red(str(error))])


def view_ams_status(term: Terminal, client: SpoolManagerAPI) -> None:
    try:
        units = client.list_ams_units()
    except Exception as exc:  # pragma: no cover - runtime feedback only
        display_error(term, exc)
        wait_for_back(term)
        return

    lines: List[str] = []
    if not units:
        lines.append("No AMS units reported.")
    for unit in units:
        unit_id = unit.get("id")
        name = unit.get("name", "<unnamed>")
        lines.append(f"[{unit_id}] {name}")
        try:
            slots = client.list_slots_for_unit(unit_id)
        except Exception as exc:  # pragma: no cover
            lines.append(term.red(f"  Failed to load slots: {exc}"))
            continue
        for slot in slots:
            slot_no = slot.get("slot_number")
            status = slot.get("status", "?")
            spool = slot.get("spool") or slot.get("spool_id")
            display = spool.get("description") if isinstance(spool, dict) else spool or "<empty>"
            lines.append(f"  Slot {slot_no}: {status} | {display}")
    _print_lines(term, "AMS Status", lines)
    wait_for_back(term)


def view_inventory(term: Terminal, client: SpoolManagerAPI) -> None:
    try:
        spools = client.list_inventory()
    except Exception as exc:  # pragma: no cover
        display_error(term, exc)
        wait_for_back(term)
        return

    lines: List[str] = []
    if not spools:
        lines.append("No spools found.")
    for spool in spools:
        line = f"[{spool.get('id')}] {spool.get('description', 'No description')}"
        status = spool.get("status")
        material = spool.get("material", {}).get("name") if isinstance(spool.get("material"), dict) else spool.get(
            "material"
        )
        color = spool.get("color", {}).get("name") if isinstance(spool.get("color"), dict) else spool.get("color")
        meta = [part for part in [material, color, status] if part]
        if meta:
            line += " | " + ", ".join(meta)
        lines.extend(wrap(line, width=term.width - 2))
    _print_lines(term, "Inventory", lines)
    wait_for_back(term)


def view_spool_lookup(term: Terminal, client: SpoolManagerAPI) -> None:
    mode_map = {"i": "id", "q": "qr", "r": "rfid"}
    print(term.clear + term.bold("Lookup mode"))
    print("Press i for Spool ID, q for QR code, r for RFID tag. ESC to cancel.")
    with term.cbreak():
        key = term.inkey()
        if key.name == "KEY_ESCAPE":
            return
    mode = mode_map.get(str(key), "id")
    identifier = prompt_input(term, f"Enter {mode.upper()} value: ")
    if not identifier:
        return
    try:
        spool = client.lookup_spool(identifier, mode=mode)
        logger.info("lookup", extra={"mode": mode, "identifier": identifier})
    except Exception as exc:  # pragma: no cover
        logger.warning("lookup_failed", extra={"mode": mode, "identifier": identifier, "error": str(exc)})
        display_error(term, exc)
        wait_for_back(term)
        return
    lines = [f"ID: {spool.get('id')}", f"Description: {spool.get('description', 'n/a')}"]
    status = spool.get("status")
    if status:
        lines.append(f"Status: {status}")
    remaining = spool.get("remaining_g")
    if remaining is not None:
        lines.append(f"Remaining: {remaining} g")
    material = spool.get("material")
    if isinstance(material, dict):
        lines.append(f"Material: {material.get('name')}")
    color = spool.get("color")
    if isinstance(color, dict):
        lines.append(f"Color: {color.get('name')} ({color.get('hex', '')})")
    events = spool.get("events")
    if events:
        lines.append("Recent events:")
        for ev in events[:5]:
            lines.append(f"  - {ev.get('event_type')} {ev.get('amount_g') or ''}g")
    _print_lines(term, "Lookup Result", lines)
    wait_for_back(term)


def assign_slot(term: Terminal, client: SpoolManagerAPI) -> None:
    slot_id = prompt_input(term, "Enter slot ID to assign: ")
    if not slot_id:
        return
    spool_id = prompt_input(term, "Enter spool ID to load into slot: ")
    if not spool_id:
        return
    try:
        result = client.assign_slot(int(slot_id), spool_id)
        logger.info("assign_slot", extra={"slot_id": slot_id, "spool_id": spool_id})
    except Exception as exc:  # pragma: no cover
        logger.warning("assign_slot_failed", extra={"slot_id": slot_id, "spool_id": spool_id, "error": str(exc)})
        display_error(term, exc)
        wait_for_back(term)
        return
    _print_lines(term, "Slot Assigned", [f"Slot {slot_id} now holds spool {spool_id}.", str(result)])
    wait_for_back(term)


def mark_status(term: Terminal, client: SpoolManagerAPI) -> None:
    spool_id = prompt_input(term, "Enter spool ID: ")
    if not spool_id:
        return
    print(term.clear + term.bold("Set status"))
    print("Press o for opened, s for in_stock. ESC to cancel.")
    with term.cbreak():
        key = term.inkey()
        if key.name == "KEY_ESCAPE":
            return
    status = "opened" if str(key) == "o" else "in_stock"
    try:
        result = client.mark_spool_status(spool_id, status=status)
        logger.info("mark_status", extra={"spool_id": spool_id, "status": status})
    except Exception as exc:  # pragma: no cover
        logger.warning("mark_status_failed", extra={"spool_id": spool_id, "status": status, "error": str(exc)})
        display_error(term, exc)
        wait_for_back(term)
        return
    _print_lines(term, "Status Updated", [f"Spool {spool_id} is now {status}.", str(result)])
    wait_for_back(term)


def wait_for_back(term: Terminal) -> None:
    with term.cbreak():
        while True:
            key = term.inkey()
            if str(key).lower() == "b" or key.name == "KEY_ESCAPE":
                break


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Terminal UI for Spool Manager")
    parser.add_argument("--base-url", default=os.getenv("SPOOL_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("SPOOL_API_TOKEN"), help="Bearer token for authenticated endpoints")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout in seconds")
    args = parser.parse_args(argv)

    client = SpoolManagerAPI(
        base_url=args.base_url,
        token=args.token,
        timeout=args.timeout,
        offline_cache=os.getenv("SPOOL_OFFLINE_CACHE") is not None,
    )
    term = Terminal()

    try:
        client.health_check()
        logger.info("health_ok", extra={"base_url": client.base_url})
    except Exception as exc:  # pragma: no cover
        logger.warning("health_failed", extra={"base_url": client.base_url, "error": str(exc)})
        print(term.dim(f"Warning: API health check failed at {client.base_url}: {exc}"))

    with term.fullscreen(), term.hidden_cursor():
        while True:
            render_menu(term)
            with term.cbreak():
                key = term.inkey()
            if not key:
                continue
            key_str = str(key).lower()
            if key_str == "q" or key.name == "KEY_ESCAPE":
                break
            if key_str == "1":
                view_ams_status(term, client)
            elif key_str == "2":
                view_inventory(term, client)
            elif key_str == "3":
                view_spool_lookup(term, client)
            elif key_str == "4":
                assign_slot(term, client)
            elif key_str == "5":
                mark_status(term, client)
    print(term.clear + term.bold("Farewell, adventurer."))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
