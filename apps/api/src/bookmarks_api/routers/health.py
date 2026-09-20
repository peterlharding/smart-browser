from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import API_CONTRACT_VERSION, __version__
from ..db import get_db
from ..schema_guard import current_revision
from ..schemas import Health

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
def health(db: Annotated[Session, Depends(get_db)]) -> Health:
    """Liveness plus the two numbers a client needs to check compatibility."""
    try:
        db.execute(text("SELECT 1"))
        ok = True
    except Exception:
        ok = False

    revision = None
    if ok and db.bind is not None:
        try:
            revision = current_revision(db.bind)  # type: ignore[arg-type]
        except Exception:
            revision = None

    return Health(
        status="ok" if ok else "degraded",
        database=ok,
        version=__version__,
        contract=API_CONTRACT_VERSION,
        schema_revision=revision,
    )
