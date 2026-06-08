from pydantic import BaseModel, Field
from typing import Literal, List

class Case(BaseModel):
	name: str
	stdin: str = ""

class CharacterizationSpec(BaseModel):
	mode: Literal["stdio", "api"] = "stdio"
	driver: str = ""
	cases: List[Case] = Field(default_factory=list)