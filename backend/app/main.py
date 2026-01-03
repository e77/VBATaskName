from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field, validator

def configure_logging() -> logging.Logger:
    """Configure a module-level logger with optional level override.

    A simple helper keeps logging consistent and allows operators to
    increase verbosity (for example when diagnosing 500 errors such as
    /openapi.json failures) by setting the ``SPOOL_API_LOG_LEVEL``
    environment variable.
    """

    log_level = os.getenv("SPOOL_API_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger_instance = logging.getLogger("spoolmanager.api")
    logger_instance.debug("Logger configured", extra={"level": log_level})
    return logger_instance


logger = configure_logging()

app = FastAPI(title="Spool Manager API", version="0.1.0")


def generate_openapi_schema() -> Dict[str, Any]:
    """Build and cache the OpenAPI schema with detailed logging.

    FastAPI will call ``app.openapi`` for ``/openapi.json``. When schema generation
    fails, the endpoint returns a 500 without much context. We log the failure so
    operators can see the stack trace in container logs. The schema is cached once
    so subsequent requests can't regress into errors if data mutates at runtime.
    """

    if getattr(app, "openapi_schema", None):
        return app.openapi_schema

    try:
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        logger.debug(
            "openapi_schema_built",
            extra={"paths": len(schema.get("paths", {}))},
        )
        app.openapi_schema = schema
        return schema
    except Exception:
        logger.exception("openapi_schema_generation_failed")
        raise


def custom_openapi() -> Dict[str, Any]:  # pragma: no cover - runtime wiring
    return generate_openapi_schema()


app.openapi = custom_openapi  # type: ignore[assignment]


ALLOWED_STATUSES = {"in_stock", "opened", "assigned", "retired"}


ALLOWED_FILAMENT_TYPES = {"spool", "bulk"}


class Spool(BaseModel):
    id: str
    description: str
    status: str
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None
    spool_type: str = Field(default="spool")

    @validator("spool_type")
    def validate_spool_type(cls, value: str) -> str:  # noqa: D417 - pydantic signature
        if value not in ALLOWED_FILAMENT_TYPES:
            raise ValueError(f"spool_type must be one of {sorted(ALLOWED_FILAMENT_TYPES)}")
        return value


class SpoolCreate(BaseModel):
    id: str
    description: str
    status: str = Field("in_stock")
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None
    spool_type: str = Field(default="spool")

    @validator("status")
    def validate_status(cls, value: str) -> str:  # noqa: D417 - pydantic signature
        if value not in ALLOWED_STATUSES:
            raise ValueError(f"Status must be one of {sorted(ALLOWED_STATUSES)}")
        return value

    @validator("remaining_g")
    def validate_remaining(cls, value: int | None) -> int | None:  # noqa: D417
        if value is not None and value < 0:
            raise ValueError("remaining_g must be non-negative")
        return value

    @validator("spool_type")
    def validate_spool_type(cls, value: str) -> str:  # noqa: D417 - pydantic signature
        if value not in ALLOWED_FILAMENT_TYPES:
            raise ValueError(f"spool_type must be one of {sorted(ALLOWED_FILAMENT_TYPES)}")
        return value


class SpoolCreate(BaseModel):
    id: str
    description: str
    status: str = Field("in_stock")
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None

    @validator("status")
    def validate_status(cls, value: str) -> str:  # noqa: D417 - pydantic signature
        if value not in ALLOWED_STATUSES:
            raise ValueError(f"Status must be one of {sorted(ALLOWED_STATUSES)}")
        return value

    @validator("remaining_g")
    def validate_remaining(cls, value: int | None) -> int | None:  # noqa: D417
        if value is not None and value < 0:
            raise ValueError("remaining_g must be non-negative")
        return value


class SpoolStatusUpdate(BaseModel):
    status: str

    @validator("status")
    def validate_status(cls, value: str) -> str:  # noqa: D417 - pydantic signature
        if value not in ALLOWED_STATUSES:
            raise ValueError(f"Status must be one of {sorted(ALLOWED_STATUSES)}")
        return value


class Slot(BaseModel):
    id: int
    slot_number: int
    status: str
    spool_id: str | None = None
    spool: Spool | None = None


class AmsUnit(BaseModel):
    id: int
    name: str
    slots: List[Slot] = Field(default_factory=list)


class BulkFilament(BaseModel):
    id: str
    description: str
    material: str | None = None
    color: str | None = None
    weight_g: int | None = None
    stage: str = Field(default="delivered")


class AmsUnitCreate(BaseModel):
    name: str
    slots: int = Field(default=4, ge=1, le=16)


class AmsUnitUpdate(BaseModel):
    name: str | None = None
    slots: int | None = Field(default=None, ge=1, le=16)


SPOOLS: Dict[str, Spool] = {
    "demo-1": Spool(
        id="demo-1",
        description="Sample PLA spool",
        status="assigned",
        material="PLA",
        color="Silver",
        remaining_g=780,
        spool_type="spool",
    ),
    "demo-2": Spool(
        id="demo-2",
        description="Carbon PETG",
        status="assigned",
        material="PETG",
        color="Black",
        remaining_g=450,
        spool_type="spool",
    ),
}

AMS_UNITS: List[AmsUnit] = [
    AmsUnit(
        id=1,
        name="AMS-01",
        slots=[
            Slot(id=1, slot_number=1, status="loaded", spool_id="demo-1"),
            Slot(id=2, slot_number=2, status="loaded", spool_id="demo-2"),
            Slot(id=3, slot_number=3, status="empty"),
            Slot(id=4, slot_number=4, status="empty"),
        ],
    ),
]

LIBRARY_BULK: List[BulkFilament] = [
    BulkFilament(
        id="bulk-pla-natural",
        description="Natural PLA 2kg box",
        material="PLA",
        color="Natural",
        weight_g=2000,
        stage="delivered",
    ),
    BulkFilament(
        id="bulk-abs-black",
        description="ABS pellets",
        material="ABS",
        color="Black",
        weight_g=1500,
        stage="delivered",
    ),
]


def _hydrate_slot(slot: Slot) -> Slot:
    if slot.spool_id:
        spool = SPOOLS.get(slot.spool_id)
        if spool:
            return slot.copy(update={"spool": spool})
    return slot


def _hydrate_slot(slot: Slot) -> Slot:
    if slot.spool_id:
        spool = SPOOLS.get(slot.spool_id)
        if spool:
            return slot.copy(update={"spool": spool})
    return slot


def _next_slot_id() -> int:
    existing_ids = [slot.id for unit in AMS_UNITS for slot in unit.slots]
    return max(existing_ids, default=0) + 1


def _next_unit_id() -> int:
    existing_ids = [unit.id for unit in AMS_UNITS]
    return max(existing_ids, default=0) + 1


def _resize_slots(unit: AmsUnit, new_size: int) -> None:
    current_slots = len(unit.slots)
    if new_size == current_slots:
        return

    if new_size < current_slots:
        unit.slots = unit.slots[:new_size]
        return

    next_slot_id = _next_slot_id()
    additional_slots = [
        Slot(
            id=next_slot_id + index,
            slot_number=current_slots + index + 1,
            status="empty",
        )
        for index in range(new_size - current_slots)
    ]
    unit.slots.extend(additional_slots)


@app.middleware("http")
async def log_requests(request, call_next):  # type: ignore[override]
    start = time.perf_counter()
    logger.info(
        "request_started",
        extra={"method": request.method, "path": request.url.path},
    )

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed", extra={"method": request.method, "path": request.url.path}
        )
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration_ms, 2),
            },
        )

    return response


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/spools", response_model=List[Spool])
async def list_spools(status: str | None = None) -> List[Spool]:
    spools = list(SPOOLS.values())
    if status:
        spools = [spool for spool in spools if spool.status == status]
    return spools


@app.post("/spools", response_model=Spool, status_code=201)
async def create_spool(payload: SpoolCreate) -> Spool:
    if payload.id in SPOOLS:
        raise HTTPException(status_code=409, detail="Spool already exists")
    spool = Spool(**payload.dict())
    SPOOLS[spool.id] = spool
    logger.info("spool_created", extra={"spool_id": spool.id, "status": spool.status})
    return spool


@app.get("/spools/{spool_id}", response_model=Spool)
async def get_spool(spool_id: str) -> Spool:
    spool = SPOOLS.get(spool_id)
    if not spool:
        raise HTTPException(status_code=404, detail="Spool not found")
    return spool


@app.patch("/spools/{spool_id}", response_model=Spool)
async def update_spool(spool_id: str, payload: SpoolStatusUpdate) -> Spool:
    spool = SPOOLS.get(spool_id)
    if not spool:
        raise HTTPException(status_code=404, detail="Spool not found")

    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    updated_spool = spool.copy(update={"status": payload.status})
    SPOOLS[spool_id] = updated_spool
    logger.info(
        "spool_status_updated", extra={"spool_id": spool_id, "status": payload.status}
    )
    return updated_spool


@app.get("/spools/lookup/qr/{code}", response_model=Spool)
async def lookup_qr(code: str) -> Spool:
    logger.info("QR scan received", extra={"code": code})
    return await get_spool(code)


@app.get("/spools/lookup/rfid/{tag}", response_model=Spool)
async def lookup_rfid(tag: str) -> Spool:
    logger.info("RFID scan received", extra={"tag": tag})
    return await get_spool(tag)


class AssignPayload(BaseModel):
    spool_id: str | None = None


@app.post("/ams/slots/{slot_id}/assign")
async def assign_slot(slot_id: int, payload: AssignPayload) -> Dict[str, Any]:
    spool = SPOOLS.get(payload.spool_id)
    if not spool:
        raise HTTPException(status_code=404, detail="Spool not found")

    for unit in AMS_UNITS:
        for slot in unit.slots:
            if slot.id == slot_id:
                slot.spool_id = payload.spool_id
                slot.status = "loaded"
                if spool.status != "assigned":
                    SPOOLS[payload.spool_id] = spool.copy(update={"status": "assigned"})
                logger.info(
                    "Assignment",
                    extra={"slot": slot_id, "spool": payload.spool_id, "unit": unit.id},
                )
                return {
                    "slot": slot_id,
                    "slot_number": slot.slot_number,
                    "spool": payload.spool_id,
                    "unit": unit.id,
                }
    raise HTTPException(status_code=404, detail="Slot not found")


@app.get("/ams", response_model=List[AmsUnit])
async def list_ams_units(include_library: bool = True) -> List[AmsUnit]:
    hydrated_units: List[AmsUnit] = []

    for unit in AMS_UNITS:
        hydrated_units.append(
            unit.copy(update={"slots": [_hydrate_slot(slot) for slot in unit.slots]})
        )

    if include_library:
        hydrated_units.append(_library_unit())

    return hydrated_units


@app.get("/ams/{unit_id}/slots", response_model=List[Slot])
async def list_slots(unit_id: int) -> List[Slot]:
    if unit_id == 0:
        return [_hydrate_slot(slot) for slot in _library_slots()]

    for unit in AMS_UNITS:
        if unit.id == unit_id:
            return [_hydrate_slot(slot) for slot in unit.slots]
    raise HTTPException(status_code=404, detail="AMS unit not found")


@app.post("/ams", response_model=AmsUnit, status_code=201)
async def create_ams_unit(payload: AmsUnitCreate) -> AmsUnit:
    unit_id = _next_unit_id()
    next_slot_id = _next_slot_id()
    slots = [
        Slot(id=next_slot_id + index, slot_number=index + 1, status="empty")
        for index in range(payload.slots)
    ]
    unit = AmsUnit(id=unit_id, name=payload.name, slots=slots)
    AMS_UNITS.append(unit)
    logger.info("ams_unit_created", extra={"unit_id": unit_id, "slots": payload.slots})
    return unit


@app.patch("/ams/{unit_id}", response_model=AmsUnit)
async def update_ams_unit(unit_id: int, payload: AmsUnitUpdate) -> AmsUnit:
    for unit in AMS_UNITS:
        if unit.id == unit_id:
            updates = payload.dict(exclude_unset=True)
            if not updates:
                raise HTTPException(status_code=400, detail="No updates provided")
            unit.name = updates.get("name", unit.name)
            if "slots" in updates:
                _resize_slots(unit, int(updates["slots"]))
            logger.info("ams_unit_updated", extra={"unit_id": unit_id, **updates})
            return unit
    raise HTTPException(status_code=404, detail="AMS unit not found")
