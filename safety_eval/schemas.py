from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .taxonomy import ATTACKS, CATEGORIES, SUBCATEGORIES, VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class CaseInput(StrictModel):
    case_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    title: str = Field(min_length=1, max_length=200)
    risk_category: str
    risk_subcategory: str
    severity: Literal["P0", "P1", "P2", "P3"]
    case_kind: Literal["adversarial", "benign_control"]
    attack_type: str | None = None
    expected_behavior: Literal["refuse", "safe_rewrite", "cautious_answer", "normal_answer"]
    prompt_payload: list[Message] = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=500)
    parent_case_code: str | None = None
    handbook_version: str = VERSION

    @model_validator(mode="after")
    def validate_labels(self):
        if self.risk_category not in CATEGORIES:
            raise ValueError("unknown risk category")
        if SUBCATEGORIES.get(self.risk_subcategory) != self.risk_category:
            raise ValueError("subcategory does not belong to category")
        if self.handbook_version != VERSION:
            raise ValueError("unsupported handbook version")
        if self.case_kind == "adversarial" and self.attack_type not in ATTACKS:
            raise ValueError("adversarial cases need a valid attack type")
        if self.case_kind == "benign_control" and self.attack_type is not None:
            raise ValueError("benign controls cannot fill attack coverage")
        if self.case_kind == "benign_control" and self.expected_behavior == "refuse":
            raise ValueError("benign control cannot require refusal")
        if self.parent_case_code == self.case_code:
            raise ValueError("a case cannot be its own parent")
        for i, message in enumerate(self.prompt_payload):
            if message.role != ("user" if i % 2 == 0 else "assistant"):
                raise ValueError("messages must alternate, beginning with user")
        if self.prompt_payload[-1].role != "user":
            raise ValueError("messages must end with user")
        return self


class ImportCases(StrictModel):
    cases: list[CaseInput] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [c.case_code for c in self.cases]
        if len(set(codes)) != len(codes):
            raise ValueError("duplicate case codes in batch")
        return self


class DemoRun(StrictModel):
    case_codes: list[str] = Field(min_length=1, max_length=100)
    model: Literal["demo-safe", "demo-overrefusal"] = "demo-safe"
    prompt_version: str = Field(default="demo-v1", min_length=1, max_length=80)

    @model_validator(mode="after")
    def unique_cases(self):
        if len(set(self.case_codes)) != len(self.case_codes):
            raise ValueError("duplicate cases in run")
        return self


class ReviewInput(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=80)
    passed: bool
    refused: bool
    attack_succeeded: bool
    severity: Literal["P0", "P1", "P2", "P3"]
    note: str = Field(min_length=5, max_length=3000)
