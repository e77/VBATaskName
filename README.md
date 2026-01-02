# Spool Manager Terminal UI

A keyboard-first terminal interface built with [Blessed](https://pypi.org/project/blessed/) for navigating AMS status, spool inventory, and quick actions like slot assignment or marking a spool as opened/stock. It connects to the same FastAPI backend described in `ARCHITECTURE.md` and runs cleanly on Raspberry Pi or any POSIX terminal.

## Features
- **AMS status**: list AMS units and per-slot occupancy.
- **Inventory list**: browse spools with material/color/status context.
- **Lookup**: search by spool ID, QR code, or RFID tag.
- **Actions**: assign a spool to a slot, mark a spool opened, or return it to stock.
- **Keyboard shortcuts**: numbered menu with `b`/`ESC` to back out, `q` to quit.
- **Dungeon flavor**: lightweight ASCII narration during navigation.

## Quickstart
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Ensure the FastAPI service is reachable (defaults to `http://localhost:8000`). Set overrides as needed:
   ```bash
   export SPOOL_API_BASE_URL="https://your-api-host"
   export SPOOL_API_TOKEN="<jwt token>"
   ```
3. Run the TUI:
   ```bash
   python spool_tui.py
   ```

### Docker Compose stack
Run the full kiosk stack (FastAPI backend, Nginx-served frontend, PostgreSQL, Caddy proxy, and pg_dump backups) for either AMD64 or Raspberry Pi:

```bash
cp .env.example .env
docker compose up --build
```

Set `DOCKER_PLATFORM=linux/arm64/v8` in `.env` for Pi builds. Health checks are enabled for all services, and nightly backups drop into `backup/dumps/` by default.

Flags can override environment variables:
- `--base-url` – API root URL
- `--token` – bearer token
- `--timeout` – HTTP timeout in seconds

## Controls
- `1` – AMS status overview
- `2` – Inventory list
- `3` – Spool lookup (ID / QR / RFID)
- `4` – Assign slot
- `5` – Mark spool opened / back to stock
- `b` or `ESC` – back from subview
- `q` – quit the app

## Notes
- API errors are surfaced inline so operators can spot connectivity/auth issues quickly.
- The app uses only standard POSIX terminal capabilities via Blessed—no GUI stack required.
