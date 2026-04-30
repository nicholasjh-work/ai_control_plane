# FastAPI router exposing the SQL validation endpoint — Nicholas Hidalgo
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.sql.safety import validate_query

router = APIRouter()


class SQLRequest(BaseModel):
    query: str


@router.post("/sql/validate")
def sql_validate(req: SQLRequest) -> JSONResponse:
    result = validate_query(req.query)
    if result.allowed:
        return JSONResponse({"allowed": True, "reason": result.reason})
    return JSONResponse(
        {"allowed": False, "reason": result.reason},
        status_code=422,
    )
