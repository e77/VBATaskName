from __future__ import annotations

import argparse
import logging
import os
import textwrap
from typing import Dict, List

from blessed import Terminal

from .api_client import SpoolManagerAPI
from .update import UpdateError, apply_updates, check_updates


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

COLOR_MAP: Dict[str, str] = {
    "black": "black",
    "white": "white",
    "silver": "bright_white",
    "gray": "grey",
    "grey": "grey",
    "red": "red",
    "green": "green",
    "blue": "blue",
    "yellow": "yellow",
    "orange": "orange_red",
    "purple": "magenta",
    "pink": "pink",
    "brown": "brown",
}


def wrap(text: str, width: int) -> List[str]:
    return textwrap.wrap(text, width=width) if text else [""]


def color_block(term: Terminal, color: str | None) -> str:
    if not color:
        return "[     ]"
    key = COLOR_MAP.get(color.lower()) if isinstance(color, str) else None
    if key and hasattr(term, key):
        paint = getattr(term, key)
        return paint("[####]") + term.normal
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            return term.on_color_rgb(r, g, b) + "     " + term.normal
        except Exception:
            return "[????]"
    return f"[{color}]"


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
    print("  6) Adjust remaining (±10g with arrows)")
    print("  7) Delete spool / clear demo data")
    print("  8) Edit AMS slot count")
    print("  9) Check for updates / redeploy")
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
        try:
            slots = client.list_slots_for_unit(unit_id)
        except Exception as exc:  # pragma: no cover
            lines.append(term.red(f"[{unit_id}] {name} - failed to load slots: {exc}"))
            continue
        lines.append(term.bold(f"[{unit_id}] {name} (slots: {len(slots)})"))
        for slot in slots:
            slot_no = slot.get("slot_number")
            slot_id = slot.get("id")
            status = slot.get("status", "?")
            spool = slot.get("spool") or slot.get("spool_id")
            color = None
            desc = "<empty>"
            remaining = None
            if isinstance(spool, dict):
                desc = spool.get("description", "<unknown>")
                color = spool.get("color")
                remaining = spool.get("remaining_g")
            elif isinstance(spool, str):
                desc = spool
            patch = color_block(term, color)
            remaining_text = f" | {remaining}g" if remaining is not None else ""
            slot_label = f"  Slot {slot_no} (id {slot_id}):"
            lines.append(f"{slot_label} {status} {patch} {desc}{remaining_text}")
        lines.append("")
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
        desc = spool.get("description", "No description")
        status = spool.get("status")
        remaining = spool.get("remaining_g")
        color = spool.get("color")
        patch = color_block(term, color)
        remaining_text = f" - {remaining}g left" if remaining is not None else ""
        lines.extend(wrap(f"[{spool.get('id')}] {patch} {desc} [{status}]{remaining_text}", width=term.width - 2))
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
    try:
        units = client.list_ams_units()
    except Exception as exc:  # pragma: no cover - runtime feedback only
        display_error(term, exc)
        wait_for_back(term)
        return

    print(term.clear + term.bold("Available slots (enter slot ID):"))
    for unit in units:
        unit_id = unit.get("id")
        name = unit.get("name", "<unnamed>")
        print(term.bold(f"[{unit_id}] {name}"))
        for slot in unit.get("slots", []):
            slot_no = slot.get("slot_number")
            slot_id = slot.get("id")
            spool = slot.get("spool") or slot.get("spool_id")
            spool_display = "<empty>"
            if isinstance(spool, dict):
                spool_display = spool.get("description", spool.get("id", "<unknown>"))
            elif isinstance(spool, str):
                spool_display = spool
            print(f"  Slot {slot_no} -> id {slot_id} ({spool_display})")
        print()

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


def adjust_remaining(term: Terminal, client: SpoolManagerAPI) -> None:
    spool_id = prompt_input(term, "Enter spool ID to adjust: ")
    if not spool_id:
        return
    try:
        spool = client.lookup_spool(spool_id)
    except Exception as exc:  # pragma: no cover
        display_error(term, exc)
        wait_for_back(term)
        return

    current = spool.get("remaining_g") or 0
    value = current
    print(term.clear + term.bold(f"Adjust remaining for {spool_id}"))
    print(term.dim("Use UP/DOWN arrows for ±10g, Enter to save, ESC to cancel."))
    while True:
        print(term.move_x(0) + f"Remaining: {value} g    ", end="", flush=True)
        with term.cbreak():
            key = term.inkey()
        if key.name == "KEY_ESCAPE":
            return
        if key.name == "KEY_UP":
            value += 10
            continue
        if key.name == "KEY_DOWN":
            value = max(0, value - 10)
            continue
        if key.name == "KEY_ENTER":
            try:
                client.update_spool(spool_id, {"remaining_g": value})
                logger.info("remaining_updated", extra={"spool_id": spool_id, "remaining_g": value})
            except Exception as exc:  # pragma: no cover
                display_error(term, exc)
                wait_for_back(term)
                return
            _print_lines(term, "Remaining updated", [f"{spool_id} now has {value} g remaining."])
            wait_for_back(term)
            return


def delete_spool(term: Terminal, client: SpoolManagerAPI) -> None:
    spool_id = prompt_input(term, "Enter spool ID to delete: ")
    if not spool_id:
        return
    print(term.clear + term.bold(f"Delete {spool_id}?"))
    print(term.red("This will remove it from any AMS slot."))
    print("Press y to confirm, anything else to cancel.")
    with term.cbreak():
        key = term.inkey()
    if str(key).lower() != "y":
        return
    try:
        client.delete_spool(spool_id)
        logger.info("spool_deleted", extra={"spool_id": spool_id})
    except Exception as exc:  # pragma: no cover
        display_error(term, exc)
        wait_for_back(term)
        return
    _print_lines(term, "Spool deleted", [f"{spool_id} removed and any slots cleared."])
    wait_for_back(term)


def edit_ams_slots(term: Terminal, client: SpoolManagerAPI) -> None:
    unit_id_input = prompt_input(term, "Enter AMS unit ID to resize: ")
    if not unit_id_input:
        return
    slots_input = prompt_input(term, "How many slots should it have (1-16)? ")
    if not slots_input:
        return
    try:
        unit_id = int(unit_id_input)
        slots = int(slots_input)
    except ValueError:
        display_error(term, ValueError("Please enter numeric values."))
        wait_for_back(term)
        return
    try:
        client.update_ams_unit(unit_id, {"slots": slots})
        logger.info("ams_resized", extra={"unit_id": unit_id, "slots": slots})
    except Exception as exc:  # pragma: no cover
        display_error(term, exc)
        wait_for_back(term)
        return
    _print_lines(term, "AMS updated", [f"Unit {unit_id} now has {slots} slots."])
    wait_for_back(term)


def check_for_updates(term: Terminal) -> None:
    try:
        status = check_updates()
    except UpdateError as exc:  # pragma: no cover - environment dependent
        display_error(term, exc)
        wait_for_back(term)
        return

    lines: List[str] = [
        f"Repository: {status.repo_root}",
        f"Remote: {status.remote}/{status.branch}",
        f"Local revision: {status.local_revision}",
        f"Remote revision: {status.remote_revision}",
        f"Ahead of remote: {status.ahead} commits",
        f"Behind remote: {status.behind} commits",
    ]
    if status.dirty:
        lines.append(term.yellow("Working tree has local changes; update may fail."))

    print(term.clear + term.bold("Update check"))
    for line in lines:
        print(line)

    if status.behind == 0:
        print(term.green("Already up to date."))
        print(term.dim("Press b to go back."))
        wait_for_back(term)
        return

    print(term.bold("Press u to pull latest and restart containers, or b to go back."))
    with term.cbreak():
        while True:
            key = term.inkey()
            if not key:
                continue
            key_str = str(key).lower()
            if key_str == "b" or key.name == "KEY_ESCAPE":
                return
            if key_str == "u":
                _print_lines(
                    term,
                    "Applying updates",
                    [
                        "Fetching latest code and restarting containers…",
                        "This may take a minute; logs will appear once complete.",
                    ],
                )
                try:
                    refreshed_status, logs = apply_updates(status)
                except UpdateError as exc:  # pragma: no cover - environment dependent
                    display_error(term, exc)
                    wait_for_back(term)
                    return

                log_lines = logs or ["No output emitted by update commands."]
                summary = [
                    term.green("Update complete."),
                    f"Now at {refreshed_status.local_revision}",
                    "Containers restarted via docker compose.",
                ]
                _print_lines(term, "Updates applied", log_lines + ["", *summary])
                wait_for_back(term)
                return


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
            elif key_str == "6":
                adjust_remaining(term, client)
            elif key_str == "7":
                delete_spool(term, client)
            elif key_str == "8":
                edit_ams_slots(term, client)
            elif key_str == "9":
                check_for_updates(term)
    print(term.clear + term.bold("Farewell, adventurer."))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
