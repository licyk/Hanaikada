"""The scanner: status, scans, cancelling."""

from fastapi import APIRouter

from hanaikada.api.deps import ServicesDep
from hanaikada.api.errors import ERROR_RESPONSES
from hanaikada.core.index.models import RootIndexSummary, ScanRequest, ScanStatus

router = APIRouter(prefix="/v1/index", tags=["index"], responses=ERROR_RESPONSES)


@router.get("/status", operation_id="get_index_status")
def get_index_status(services: ServicesDep) -> ScanStatus:
    """The same snapshot the scan events carry, for a client that reconnects."""
    return services.index.status()


@router.post("/scan", operation_id="start_scan")
def start_scan(services: ServicesDep, body: ScanRequest) -> ScanStatus:
    """Queue a scan of one folder, one root or every root. 409 while a full rebuild of the same root runs."""
    return services.index.request_scan(body)


@router.post("/cancel", operation_id="cancel_scan")
def cancel_scan(services: ServicesDep) -> ScanStatus:
    return services.index.cancel()


@router.get("/roots", operation_id="get_index_roots")
def get_index_roots(services: ServicesDep) -> list[RootIndexSummary]:
    """Rows, missing files, parse failures and the last scan, per root."""
    return services.index.roots_summary()
