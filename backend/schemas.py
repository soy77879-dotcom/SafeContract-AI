
from typing import Literal

from pydantic import BaseModel, Field, model_validator


RiskType = Literal[
    "deposit_return",
    "repair_cost",
    "termination",
    "restoration",
    "fee",
    "other",
    "none",
]

RiskStatus = Literal[
    "potential_risk",
    "needs_review",
    "no_risk_detected",
]


class Clause(BaseModel):
    clause_id: str = Field(pattern=r"^C\d{3,}$")
    page: int = Field(ge=1)
    text: str = Field(min_length=1)


class OCRResponse(BaseModel):
    document_id: str = Field(min_length=1)
    clauses: list[Clause]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [clause.clause_id for clause in self.clauses]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate clause_id")
        return self


class AnalyzeRequest(OCRResponse):
    clauses: list[Clause] = Field(min_length=1)


class RiskResult(BaseModel):
    clause_id: str
    risk_type: RiskType
    risk_status: RiskStatus
    evidence: str
    reason: str
    possible_disadvantage: str
    question: str
    recommended_action: str


class AnalyzeResponse(BaseModel):
    document_id: str = Field(min_length=1)
    status: Literal["completed", "partial"]
    results: list[RiskResult]
    warnings: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorDetail
