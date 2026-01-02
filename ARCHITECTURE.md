# Spool Manager Architecture

## Overview
A web application for managing filament spools and AMS (Automatic Material System) slots. The stack uses **FastAPI** for the backend, **PostgreSQL** for data storage, and **React** for the frontend. The system supports QR/RFID lookups, tracks spool usage, and provides dashboards for AMS units and inventory.

## Core Requirements
- CRUD for spools, AMS slots, and check-in/out operations.
- Endpoints to look up resources via QR code or RFID tag IDs.
- Record usage events tied to spools and AMS slot movements.
- Authentication with roles (admin vs operator) using JWT sessions.
- Dashboard UI for AMS status, inventory filters, spool detail/history, quick actions, and integrations for QR scanning and RFID.

## High-Level Architecture
- **Frontend (React + Vite)**: SPA served by the backend. Uses React Query for data fetching, Material UI (or Tailwind) for components, and client-side JWT storage via HTTP-only cookies.
- **Backend (FastAPI)**: REST API with dependency-injected services, Pydantic models, and async SQLAlchemy for DB access.
- **Database (PostgreSQL)**: Normalized schema with audit tables for usage events.
- **Integrations**:
  - Browser QR scanning using `jsqr` or `@zxing/browser` to decode camera frames into spool or slot IDs.
  - RFID updates posted from Pi/Arduino via HTTPS webhook or MQTT bridge that forwards to the FastAPI endpoint.

## Database Schema

```sql
CREATE TABLE vendors (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  website TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE materials (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  density_g_cm3 NUMERIC(6,3),
  extrusion_temp_c INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE colors (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  hex TEXT CHECK (hex ~ '^#[0-9A-Fa-f]{6}$'),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE spools (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_id INT REFERENCES vendors(id),
  material_id INT REFERENCES materials(id),
  color_id INT REFERENCES colors(id),
  description TEXT,
  weight_g INT CHECK (weight_g > 0),
  remaining_g INT CHECK (remaining_g >= 0),
  cost_cents INT,
  status TEXT NOT NULL CHECK (status IN ('in_stock','opened','assigned','retired')),
  qr_code TEXT UNIQUE,
  rfid_tag TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','operator')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ams_units (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  location TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ams_slots (
  id SERIAL PRIMARY KEY,
  ams_unit_id INT NOT NULL REFERENCES ams_units(id),
  slot_number INT NOT NULL,
  spool_id UUID REFERENCES spools(id),
  status TEXT NOT NULL CHECK (status IN ('empty','loaded','locked','error')),
  last_checkin TIMESTAMPTZ,
  UNIQUE(ams_unit_id, slot_number)
);

CREATE TABLE usage_events (
  id BIGSERIAL PRIMARY KEY,
  spool_id UUID REFERENCES spools(id) NOT NULL,
  ams_slot_id INT REFERENCES ams_slots(id),
  event_type TEXT NOT NULL CHECK (event_type IN ('check_in','check_out','consume','retire','reopen')),
  amount_g INT,
  source TEXT, -- e.g., 'rfid', 'qr', 'manual', 'mqtt'
  created_by INT REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## API Design (FastAPI)
- **Auth**
  - `POST /auth/login` → issue JWT cookie; `POST /auth/refresh`; `POST /auth/logout`.
- **Spools**
  - `GET /spools` list with filters (material, color, vendor, status, search).
  - `POST /spools` create; `GET /spools/{id}` read; `PATCH /spools/{id}` update; `DELETE /spools/{id}` retire.
  - `POST /spools/{id}/open` mark opened; `POST /spools/{id}/retire` retire; `POST /spools/{id}/check-in` / `check-out` record movement.
  - `GET /spools/lookup/qr/{code}` and `GET /spools/lookup/rfid/{tag}`.
- **AMS**
  - `GET /ams` list units; `POST /ams` create unit.
  - `GET /ams/{id}/slots` list slots; `PATCH /ams/slots/{slotId}` inline assignment/updates.
  - `POST /ams/slots/{slotId}/assign` attach spool; `POST /ams/slots/{slotId}/release` remove.
- **Usage Events**
  - `GET /spools/{id}/events` history; `POST /usage-events` record ad-hoc consumption.

Responses use pagination metadata and return minimal spool/slot DTOs to keep the dashboard fast.

## Authentication & Authorization
- JWT access + refresh tokens stored in HTTP-only cookies. CSRF token header for state-changing requests.
- Roles: **admin** can manage users, vendors, materials, delete/retire spools; **operator** can perform check-in/out, assign slots, and update remaining weight.
- FastAPI dependencies enforce role checks per route; audit with `usage_events.created_by`.

## Integrations
- **QR Scanning**: React page uses `@zxing/browser` or `jsqr` to read camera frames. Once a code is decoded the app calls `POST /api/spools/:id/scan` to load the detail view and optionally start an assignment flow in one step.
- **RFID**: Raspberry Pi/Arduino reads tags over USB or serial and posts `{ "rfid": "TAG", "slot": 3, "unit": "AMS-A" }` to `/integrations/rfid`. The API resolves the spool by the RFID UID, returns the status, and the Pi can drive LED/buzzer feedback based on the response. MQTT bridge optional via paho-mqtt client pushing to the same handler.
- **Manual Lookup**: Operators can fall back to entering a spool ID or scanning a plain barcode to retrieve details when QR/RFID is unavailable.

## Frontend Experience (React)
- **Dashboard**: two AMS unit cards showing per-slot status (color chips for material, badges for remaining/cost). Inline slot assignment via dropdown + quick search.
- **Inventory Table**: filter by material, color, vendor, status (open/stock). Fast search bar across description/vendor/material/color. Bulk receive wizard for multiple spools.
- **Spool Detail**: history timeline from usage events, usage graph (remaining over time), quick actions (assign slot, mark opened, retire/reopen).
- **Components**: color chips, material icons, badges for cost/remaining, modals for check-in/out.
- **State/Data**: React Query hooks (`useSpools`, `useAmsSlots`, `useUsageEvents`). Optimistic updates for slot assignment and status changes.

## Backend Services Structure
- `app/main.py` FastAPI app, mounts routers and static frontend.
- `app/models.py` SQLAlchemy models; `app/schemas.py` Pydantic models.
- `app/routes/` modular routers: `auth.py`, `spools.py`, `ams.py`, `usage.py`, `integrations.py`.
- `app/services/` business logic: spool service, AMS service, usage recorder, auth service.
- `app/deps.py` dependency providers for DB session, current user, role guard.
- `app/events.py` to centralize usage event creation and validations.

## Deployment Notes
- Use Docker Compose: services for `api`, `postgres`, and `frontend` (Vite build served by Nginx or by FastAPI static files).
- Environment variables: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGO`, `FRONTEND_URL`, `MQTT_URI` (optional).
- Nightly job to recalc remaining weights from events can run as a FastAPI background task or separate cron.

## Future Enhancements
- WebSocket push for slot state changes.
- Calibration helpers: prompt operator to input measured remaining weight to reduce drift.
- Reports: per-material usage, vendor spend, and AMS utilization heatmaps.
