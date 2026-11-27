"""FastAPI entry point for the placement-query-bot deployment."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from query_service import ask, get_usage

app = FastAPI(title="BNMIT Placement Query Bot", version="1.0.0")


class QueryInput(BaseModel):
    question: str = Field(min_length=3, max_length=3000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "placement-query-bot"}


@app.get("/usage")
def usage() -> dict[str, int | str]:
    return get_usage()


@app.post("/query")
def query(data: QueryInput) -> dict[str, str | float | int]:
    return ask(data.question)
