from __future__ import annotations

import argparse
import logging
import os
import subprocess
import textwrap
from typing import Any, Callable, Dict, List, Optional

from blessed import Terminal

from .api_client import SpoolManagerAPI
from .update import UpdateError, check_updates

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
        return "[ ]"

    key = COLOR_MAP.get(color.lower()) if isinstance(color, str) else None
    if key and hasattr(term, key):
        paint = getattr(term, key)
        return paint("[####]") + term.normal

    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            return term.on_color_rgb(r, g, b) + " " + term.normal
        except Exception:
            return "[????]"

    return f"[{color}]"


def _center(text: str, width: int) -> str:
    trimmed = text[: width - 1] if len(text) > width else text
    pad = max(0, width - len(trimmed))
    left = pad // 2
    right = pad - left
    return " " * left + trimmed + " " * right


def _slot_labels(slot: Dict[str, Any]) -> tuple[str, str, str]:
    spool = slot.get("spool") or slot.get("spool_id")
    status = slot.get("status", "?")

    desc = "Empty"
    color_label = "-"
    remaining = None

    if isinstance(spool, dict):
        desc = spool.get("description") or spool.get("material", {}).get("name") or "Spool"
        color_value = spool.get("color")
        if isinstance(color_value, dict):
            color_label = color_value.get("name", "?")
        elif isinstance(color_value, str):
            color_label = color_value
        remaining = spool.get("remaining_g")
    elif isinstance(spool, str):
        desc = spool

    remaining_text = f"{remaining}g" if remaining is not None else ""
    color_display = color_label
    if remaining_text:
        color_display = f"{color_display} | {remaining_text}" if color_display != "-" else remaining_text

    return status, desc, color_display


def render_ams_ascii(unit_id: int | str, name: str, slots: List[Dict[str, Any]]) -> List[str]:
    if not slots:
        return ["(no slots reported)"]

    cell_width = max(12, min(18, (80 // max(1, len(slots))) - 1))
    border = "+" + "+".join(["-" * cell_width for _ in slots]) + "+"
    title_inner_width = len(border) - 2
    title_line = "|" + _center(f"AMS {unit_id}: {name}", title_inner_width) + "|"

    slot_labels = [f"Slot {slot.get('slot_number')}" for slot in slots]
    status_labels = []
    desc_labels = []
    color_labels = []
    for slot in slots:
        status, desc, color_label = _slot_labels(slot)
        status_labels.append(status)
        desc_labels.append(desc)
        color_labels.append(color_label)

    row_slot = "|" + "|".join(_center(text, cell_width) for text in slot_labels) + "|"
    row_status = "|" + "|".join(_center(text, cell_width) for text in status_labels) + "|"
    row_desc = "|" + "|".join(_center(text, cell_width) for text in desc_labels) + "|"
    row_color = "|" + "|".join(_center(text, cell_width) for text in color_labels) + "|"

    return [border, title_line, border, row_slot, row_desc, row_color, border]


def prompt_input(term: Terminal, label: str) -> str:
    print(term.clear + term.bold(label))
    print(faint("Press Enter when done.\nESC cancels."))
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


def faint(s: str) -> str:
    # DO NOT use term.dim() or any terminal capability here.
    # Some terminals/terminfo entries break blessed's dim handling.
    # Plain text is the only safe "faint".
    return s


def render_menu(term: Terminal) -> None:
    print(term.clear + term.bold_underline("Spool Manager Terminal"))
    print(term.bold("Dungeon Trail"))
    for line in DUNGEON_FLAVOR:
        print(faint(" " + line))
    print()
    print(term.bold("Choose your path (press key):"))
    print(" 1) AMS status overview")
    print(" 2) Inventory list")
    print(" 3) Spool lookup (ID / QR / RFID)")
    print(" 4) Assign slot")
    print(" 5) Mark spool opened / back to stock")
    print(" 6) Check for updates / redeploy")
    print(" a) Admin / configuration")
    print(" q) Quit")


def _print_lines(term: Terminal, title: str, lines: List[str]) -> None:
    print(term.clear + term.bold(title))
    for line in lines:
        print(line)
    print(faint("Press b to go back."))


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
        name = unit.get("name", "")
        try:
            slots = client.list_slots_for_unit(unit_id)
        except Exception as exc:  # pragma: no cover
            lines.append(term.red(f"[{unit_id}] {name} - failed to load slots: {exc}"))
            continue

        lines.append(term.bold(f"[{unit_id}] {name} (slots: {len(slots)})"))
        lines.extend(render_ams_ascii(unit_id, name, slots))
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
        lines.extend(
            wrap(
                f"[{spool.get('id')}] {patch} {desc} [{status}]{remaining_text}",
                width=max(10, term.width - 2),
            )
        )

    _print_lines(term, "Inventory", lines)
    wait_for_back(term)


def view_spool_lookup(term: Terminal, client: SpoolManagerAPI) -> None:
    mode_map = {"i": "id", "q": "qr", "r": "rfid"}
    print(term.clear + term.bold("Lookup mode"))
    print("Press i for Spool ID, q for QR code, r for RFID tag.\nESC to cancel.")
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
            lines.append(f" - {ev.get('event_type')} {ev.get('amount_g') or ''}g")

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
        name = unit.get("name", "")
        print(term.bold(f"[{unit_id}] {name}"))
        for slot in unit.get("slots", []):
            slot_no = slot.get("slot_number")
            slot_id = slot.get("id")
            spool = slot.get("spool") or slot.get("spool_id")
            spool_display = ""
            if isinstance(spool, dict):
                spool_display = spool.get("description", spool.get("id", ""))
            elif isinstance(spool, str):
                spool_display = spool
            print(f" Slot {slot_no} -> id {slot_id} ({spool_display})")
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
    print("Press o for opened, s for in_stock.\nESC to cancel.")
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


def _choose_unit(term: Terminal, units: List[Dict[str, Any]]) -> int | None:
    print(term.clear + term.bold("Select AMS unit (default 1):"))
    for unit in units:
        print(f" [{unit.get('id')}] {unit.get('name', '')} ({len(unit.get('slots', []))} slots)")

    raw = prompt_input(term, "Enter AMS unit ID (or Enter for 1): ")
    if raw == "":
        return 1

    try:
        return int(raw)
    except ValueError:
        display_error(term, ValueError("Invalid AMS unit ID"))
        wait_for_back(term)
        return None


def configure_ams_slots(term: Terminal, client: SpoolManagerAPI) -> None:
    try:
        units = client.list_ams_units()
    except Exception as exc:  # pragma: no cover - runtime feedback only
        display_error(term, exc)
        wait_for_back(term)
        return

    unit_id = _choose_unit(term, units)
    if unit_id is None:
        return

    raw_slots = prompt_input(term, f"Enter desired slot count for AMS {unit_id} (1-16): ")
    if raw_slots == "":
        return

    try:
        slots = int(raw_slots)
    except ValueError:
        display_error(term, ValueError("Slot count must be a number"))
        wait_for_back(term)
        return

    if slots < 1 or slots > 16:
        display_error(term, ValueError("Slot count must be between 1 and 16"))
        wait_for_back(term)
        return

    try:
        result = client.update_ams_unit(unit_id, {"slots": slots})
        logger.info("ams_slots_updated", extra={"unit_id": unit_id, "slots": slots})
    except Exception as exc:  # pragma: no cover - runtime feedback only
        display_error(term, exc)
        wait_for_back(term)
        return

    lines = [
        f"AMS {unit_id} slots updated to {slots}.",
        f"Name: {result.get('name', '')}",
    ]
    _print_lines(term, "AMS updated", lines)
    wait_for_back(term)


def admin_menu(term: Terminal, client: SpoolManagerAPI) -> None:
    while True:
        print(term.clear + term.bold("Admin / configuration"))
        print(" 1) Change AMS slot count")
        print(" b) Back")

        with term.cbreak():
            key = term.inkey()

        if not key:
            continue

        key_str = str(key).lower()
        if key_str == "1":
            configure_ams_slots(term, client)
        elif key_str == "b" or key.name == "KEY_ESCAPE":
            return


def _run(cmd: List[str], cwd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def _tracked_dirty(repo_root: str) -> bool:
    # IMPORTANT: ignore untracked files (.env/logs/dumps/__pycache__).
    code, out = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_root)
    if code != 0:
        return True  # be conservative if git itself fails
    return out.strip() != ""


def _remote_master_update(
    repo_root: str, remote: str, branch: str, progress: Optional[Callable[[str], None]] = None
) -> List[str]:
    """
    Remote is the master: force local checkout to match remote/branch, then restart containers.
    Keeps local runtime/config files by excluding them from git clean.

    A ``progress`` callback can be provided to surface incremental updates while commands run,
    so the TUI doesn't appear to hang on long operations (e.g., docker builds).
    """
    logs: List[str] = []

    def emit(line: str) -> None:
        if progress:
            progress(line)
        logs.append(line)

    def run_or_raise(cmd: List[str]) -> None:
        emit(f"$ {' '.join(cmd)}")
        code, out = _run(cmd, cwd=repo_root)
        if out:
            for segment in out.splitlines():
                emit(segment)
        if code != 0:
            emit(f"Command failed ({code})")
            raise UpdateError(f"Command failed ({code}): {' '.join(cmd)}\n{out}")

    emit("Starting update...")
    run_or_raise(["git", "fetch", remote])
    run_or_raise(["git", "reset", "--hard", f"{remote}/{branch}"])

    emit("Cleaning untracked files (preserving runtime/config)")
    # Clean untracked, but KEEP your runtime/config stuff.
    run_or_raise(
        [
            "git",
            "clean",
            "-fd",
            "-e",
            ".env",
            "-e",
            "backup/dumps",
            "-e",
            "spooltui.log",
            "-e",
            "spooltui/__pycache__",
        ]
    )

    emit("Rebuilding containers via docker compose...")
    run_or_raise(["docker", "compose", "up", "-d", "--build"])
    emit("Update finished.")
    return logs


def check_for_updates(term: Terminal) -> None:
    try:
        status = check_updates()
    except UpdateError as exc:  # pragma: no cover - environment dependent
        display_error(term, exc)
        wait_for_back(term)
        return

    tracked_dirty = _tracked_dirty(status.repo_root)

    lines: List[str] = [
        f"Repository: {status.repo_root}",
        f"Remote: {status.remote}/{status.branch}",
        f"Local revision: {status.local_revision}",
        f"Remote revision: {status.remote_revision}",
        f"Ahead of remote: {status.ahead} commits",
        f"Behind remote: {status.behind} commits",
    ]

    if tracked_dirty:
        lines.append(term.yellow("Tracked files modified locally; update will discard them (remote is master)."))

    print(term.clear + term.bold("Update check"))
    for line in lines:
        print(line)

    if status.behind == 0:
        print(term.green("Already up to date."))
        print(faint("Press b to go back."))
        wait_for_back(term)
        return

    print(term.bold("Press u to update from remote main and restart containers, or b to go back."))

    with term.cbreak():
        while True:
            key = term.inkey()
            if not key:
                continue
            key_str = str(key).lower()
            if key_str == "b" or key.name == "KEY_ESCAPE":
                return
            if key_str == "u":
                try:
                    print(term.clear + term.bold("Running update..."))
                    logs = _remote_master_update(
                        status.repo_root,
                        status.remote,
                        status.branch,
                        progress=lambda line: print(line, flush=True),
                    )
                    refreshed_status = check_updates()
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
        print(faint(f"Warning: API health check failed at {client.base_url}: {exc}"))

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
                check_for_updates(term)
            elif key_str == "a":
                admin_menu(term, client)

    print(term.clear + term.bold("Farewell, adventurer."))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
