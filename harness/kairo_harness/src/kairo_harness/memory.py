from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kairo_harness.domain import validate_permission_names


class MemoryScope(StrEnum):
    PRIVATE = "private"
    TEAM = "team"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=200)
    scope: MemoryScope
    owner_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PrivateMemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)


class PrivateMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=200)
    record: MemoryRecord

    @model_validator(mode="after")
    def validate_private_scope(self) -> PrivateMemoryUpdate:
        if self.record.scope is not MemoryScope.PRIVATE:
            raise ValueError("private memory updates require a private record")
        if self.record.owner_id != self.agent_id:
            raise ValueError("private memory records must belong to the updating agent")
        return self


class TeamMemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(min_length=1, max_length=200)
    requester_agent_id: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=1000)
    tags: frozenset[str] = Field(default_factory=frozenset)
    limit: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_tags(self) -> TeamMemoryQuery:
        self.tags = validate_permission_names(self.tags)
        return self


class TeamMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(min_length=1, max_length=200)
    requester_agent_id: str = Field(min_length=1, max_length=200)
    record: MemoryRecord

    @model_validator(mode="after")
    def validate_team_scope(self) -> TeamMemoryUpdate:
        if self.record.scope is not MemoryScope.TEAM:
            raise ValueError("team memory updates require a team record")
        if self.record.owner_id != self.team_id:
            raise ValueError("team memory records must belong to the updating team")
        return self


class AgentMemory(ABC):
    @abstractmethod
    async def retrieve(self, query: PrivateMemoryQuery) -> list[MemoryRecord]: ...

    @abstractmethod
    async def update(self, update: PrivateMemoryUpdate) -> None: ...


class TeamMemory(ABC):
    @abstractmethod
    async def retrieve(self, query: TeamMemoryQuery) -> list[MemoryRecord]: ...

    @abstractmethod
    async def update(self, update: TeamMemoryUpdate) -> None: ...


PrivateAgentMemory = AgentMemory
SharedTeamMemory = TeamMemory
