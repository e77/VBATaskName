from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("spoolmanager.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="Spool Manager API", version="0.1.0")


class Spool(BaseModel):
    id: str
    description: str
    status: str
    material: str | None = None
    color: str | None = None
    remaining_g: int | None = None


class SpoolStatusUpdate(BaseModel):
    status: str


class Slot(BaseModel):
    slot_number: int
    status: str
    spool_id: str | None = None


class AmsUnit(BaseModel):
    id: int
    name: str
    slots: List[Slot] = []


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
            Slot(slot_number=1, status="loaded", spool_id="demo-1"),
            Slot(slot_number=2, status="empty"),
        ],
    )
]


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/spools", response_model=List[Spool])
async def list_spools() -> List[Spool]:
    return list(SPOOLS.values())


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

    allowed_statuses = {"in_stock", "opened", "assigned", "retired"}
    if payload.status not in allowed_statuses:
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
    spool_id: str


@app.post("/ams/slots/{slot_id}/assign")
async def assign_slot(slot_id: int, payload: AssignPayload) -> Dict[str, Any]:
    for unit in AMS_UNITS:
        for slot in unit.slots:
            if slot.slot_number == slot_id:
                slot.spool_id = payload.spool_id
                slot.status = "loaded"
                logger.info("Assignment", extra={"slot": slot_id, "spool": payload.spool_id})
                return {"slot": slot_id, "spool": payload.spool_id, "unit": unit.id}
    raise HTTPException(status_code=404, detail="Slot not found")


@app.get("/ams", response_model=List[AmsUnit])
async def list_ams_units() -> List[AmsUnit]:
    return AMS_UNITS


@app.get("/ams/{unit_id}/slots", response_model=List[Slot])
async def list_slots(unit_id: int) -> List[Slot]:
    for unit in AMS_UNITS:
        if unit.id == unit_id:
            return unit.slots
    raise HTTPException(status_code=404, detail="AMS unit not found")
