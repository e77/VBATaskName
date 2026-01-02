"""HTTP client for the Spool Manager API.

This client is intentionally lightweight so it can run on a Raspberry Pi or
any terminal environment where the curses/Blessed TUI is used. Endpoints are
aligned with the architecture doc shipped with this repository.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


class APIError(Exception):
    """Raised when the API responds with an unexpected status."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SpoolManagerAPI:
    """Simple wrapper around the Spool Manager REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.base_url = (base_url or os.getenv("SPOOL_API_BASE_URL") or "http://localhost:8000").rstrip(
            "/"
        )
        self.token = token or os.getenv("SPOOL_API_TOKEN")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, headers=self._headers(), timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json()
                message = detail.get("detail") or detail
            except Exception:
                message = response.text
            raise APIError(f"{response.status_code}: {message}", status_code=response.status_code)
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.text

    def list_ams_units(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/ams")

    def list_slots_for_unit(self, unit_id: int) -> List[Dict[str, Any]]:
        return self._request("GET", f"/ams/{unit_id}/slots")

    def list_inventory(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"status": status} if status else None
        return self._request("GET", "/spools", params=params)

    def lookup_spool(self, identifier: str, mode: str = "id") -> Dict[str, Any]:
        if mode == "qr":
            path = f"/spools/lookup/qr/{identifier}"
        elif mode == "rfid":
            path = f"/spools/lookup/rfid/{identifier}"
        else:
            path = f"/spools/{identifier}"
        return self._request("GET", path)

    def assign_slot(self, slot_id: int, spool_id: str) -> Dict[str, Any]:
        payload = {"spool_id": spool_id}
        return self._request("POST", f"/ams/slots/{slot_id}/assign", json=payload)

    def mark_spool_status(self, spool_id: str, status: str) -> Dict[str, Any]:
        payload = {"status": status}
        return self._request("PATCH", f"/spools/{spool_id}", json=payload)

    def list_usage_events(self, spool_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/spools/{spool_id}/events")
