from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator

logger = logging.getLogger("spoolmanager.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="Spool Manager API", version="0.1.0")


ALLOWED_STATUSES = {"in_stock", "opened", "assigned", "retired"}


class Spool(BaseModel):
    id: str
    description: str
    status: str
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None


class SpoolCreate(BaseModel):
    id: str
    description: str
    status: str = "in_stock"
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None

    @validator("status")
    def validate_status(cls, status: str) -> str:  # noqa: D417
        if status not in ALLOWED_STATUSES:
            raise ValueError("Invalid status")
        return status


class SpoolUpdate(BaseModel):
    description: str | None = None
    status: str | None = None
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None

    @validator("status")
    def validate_status(cls, status: str | None) -> str | None:  # noqa: D417
        if status is not None and status not in ALLOWED_STATUSES:
            raise ValueError("Invalid status")
        return status


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
        status="in_stock",
        material="PLA",
        color="Silver",
        remaining_g=780,
    ),
    "demo-2": Spool(
        id="demo-2",
        description="Carbon PETG",
        status="assigned",
        material="PETG",
        color="Black",
        remaining_g=450,
    ),
}

AMS_UNITS: List[AmsUnit] = [
    AmsUnit(
        id=1,
        name="AMS-01",
        slots=[
            Slot(id=1, slot_number=1, status="loaded", spool_id="demo-1"),
            Slot(id=2, slot_number=2, status="empty"),
            Slot(id=3, slot_number=3, status="empty"),
            Slot(id=4, slot_number=4, status="empty"),
        ],
    ),
    AmsUnit(
        id=2,
        name="AMS-02",
        slots=[
            Slot(id=5, slot_number=1, status="empty"),
            Slot(id=6, slot_number=2, status="empty"),
            Slot(id=7, slot_number=3, status="empty"),
            Slot(id=8, slot_number=4, status="empty"),
        ],
    ),
]


def _next_slot_id() -> int:
    existing_ids = [slot.id for unit in AMS_UNITS for slot in unit.slots]
    return max(existing_ids, default=0) + 1


def _next_unit_id() -> int:
    existing_ids = [unit.id for unit in AMS_UNITS]
    return max(existing_ids, default=0) + 1


def _coerce_spool(spool: Any) -> Spool | None:
    if isinstance(spool, Spool):
        return spool
    if isinstance(spool, dict):
        try:
            return Spool(**spool)
        except Exception:
            return None
    return None


def _hydrate_slot(slot: Slot) -> Slot:
    spool = _coerce_spool(slot.spool) or _coerce_spool(SPOOLS.get(slot.spool_id))
    slot.spool = spool
    slot.spool_id = spool.id if spool else None
    if not isinstance(slot.status, str):
        slot.status = "empty"
    return slot


def _serialize_unit(unit: AmsUnit) -> Dict[str, Any]:
    """Return a JSON-safe view of an AMS unit and its slots.

    This guards against any unexpected runtime state (e.g., a slot pointing to a
    missing spool) so that the AMS endpoints never return a 500 error.
    """

    hydrated_slots: List[Dict[str, Any]] = []
    for slot in sorted(unit.slots, key=lambda s: s.slot_number):
        hydrated_slot = _hydrate_slot(slot)
        hydrated = hydrated_slot.dict()
        spool = _coerce_spool(hydrated_slot.spool) or _coerce_spool(SPOOLS.get(hydrated_slot.spool_id))
        hydrated["spool"] = spool.dict() if spool else None
        hydrated_slots.append(hydrated)

    return {"id": unit.id, "name": unit.name, "slots": hydrated_slots}


def _resize_slots(unit: AmsUnit, slots: int) -> None:
    """Grow or shrink slots while preserving existing assignments."""

    if slots == len(unit.slots):
        return

    if slots > len(unit.slots):
        start_id = _next_slot_id()
        new_slots = [
            Slot(id=start_id + idx, slot_number=len(unit.slots) + idx + 1, status="empty")
            for idx in range(slots - len(unit.slots))
        ]
        unit.slots.extend(new_slots)
    else:
        # Remove highest-numbered slots first
        unit.slots.sort(key=lambda s: s.slot_number)
        to_remove = [s for s in unit.slots if s.slot_number > slots]
        for slot in to_remove:
            slot.spool_id = None
            slot.status = "empty"
        unit.slots = [s for s in unit.slots if s.slot_number <= slots]


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
async def update_spool(spool_id: str, payload: SpoolUpdate) -> Spool:
    spool = SPOOLS.get(spool_id)
    if not spool:
        raise HTTPException(status_code=404, detail="Spool not found")

    updates = payload.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    if "status" in updates and updates["status"] not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    updated_spool = spool.copy(update=updates)
    SPOOLS[spool_id] = updated_spool
    logger.info("spool_updated", extra={"spool_id": spool_id, **updates})
    return updated_spool


@app.delete("/spools/{spool_id}", status_code=204)
async def delete_spool(spool_id: str) -> None:
    if spool_id not in SPOOLS:
        raise HTTPException(status_code=404, detail="Spool not found")

    # Clear any slots referencing this spool
    for unit in AMS_UNITS:
        for slot in unit.slots:
            if slot.spool_id == spool_id:
                slot.spool_id = None
                slot.spool = None
                slot.status = "empty"

    del SPOOLS[spool_id]
    logger.info("spool_deleted", extra={"spool_id": spool_id})


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
    spool = SPOOLS.get(payload.spool_id) if payload.spool_id else None
    if payload.spool_id and not spool:
        raise HTTPException(status_code=404, detail="Spool not found")
    if spool and not isinstance(spool, Spool):
        spool = Spool(**spool)  # type: ignore[arg-type]
        SPOOLS[payload.spool_id] = spool

    for unit in AMS_UNITS:
        for slot in unit.slots:
            if slot.id == slot_id:
                slot.spool_id = payload.spool_id
                slot.spool = spool
                slot.status = "loaded" if payload.spool_id else "empty"
                if payload.spool_id and spool.status != "assigned":
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
async def list_ams_units() -> List[AmsUnit]:
    return [_serialize_unit(unit) for unit in AMS_UNITS]


@app.get("/ams/{unit_id}/slots", response_model=List[Slot])
async def list_slots(unit_id: int) -> List[Slot]:
    for unit in AMS_UNITS:
        if unit.id == unit_id:
            return [_hydrate_slot(slot).dict() for slot in unit.slots]
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
