import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

class ExperimentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=1000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    custom_code: str | None = Field(default=None, max_length=50_000)
    input_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_data")
    @classmethod
    def validate_input_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        except (TypeError, ValueError):
            raise ValueError("Input data must contain valid JSON values.")
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("Input data must be no larger than 1 MB.")
        return value

class ExperimentOut(BaseModel):
    id: int
    name: str
    description: str
    parameters: dict[str, Any]
    status: str
    created_at: str
    last_run_id: int | None = None
