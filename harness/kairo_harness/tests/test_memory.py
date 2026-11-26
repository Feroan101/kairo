import pytest
from kairo_harness.memory import (
    AgentMemory,
    MemoryRecord,
    MemoryScope,
    PrivateAgentMemory,
    PrivateMemoryQuery,
    PrivateMemoryUpdate,
    SharedTeamMemory,
    TeamMemory,
    TeamMemoryQuery,
    TeamMemoryUpdate,
)
from pydantic import ValidationError


def test_memory_interfaces_are_abstract_and_scope_aliases_are_stable() -> None:
    assert PrivateAgentMemory is AgentMemory
    assert SharedTeamMemory is TeamMemory
    with pytest.raises(TypeError):
        AgentMemory()
    with pytest.raises(TypeError):
        TeamMemory()


def test_private_memory_update_is_bound_to_the_agent() -> None:
    record = MemoryRecord(
        record_id="record-1",
        scope=MemoryScope.PRIVATE,
        owner_id="agent-1",
        content="working note",
    )

    update = PrivateMemoryUpdate(agent_id="agent-1", record=record)
    query = PrivateMemoryQuery(agent_id="agent-1", text="note", limit=5)

    assert update.record is record
    assert query.agent_id == "agent-1"
    with pytest.raises(ValidationError):
        PrivateMemoryUpdate(agent_id="agent-2", record=record)
    with pytest.raises(ValidationError):
        PrivateMemoryUpdate(
            agent_id="agent-1",
            record=record.model_copy(update={"scope": MemoryScope.TEAM}),
        )


def test_team_memory_update_is_bound_to_the_team_and_requester() -> None:
    record = MemoryRecord(
        record_id="record-2",
        scope=MemoryScope.TEAM,
        owner_id="team-1",
        content="shared finding",
        metadata={"source": "tool"},
    )

    update = TeamMemoryUpdate(
        team_id="team-1",
        requester_agent_id="agent-1",
        record=record,
    )
    query = TeamMemoryQuery(
        team_id="team-1",
        requester_agent_id="agent-1",
        tags=frozenset({"research", "python"}),
    )

    assert update.record.owner_id == "team-1"
    assert query.tags == frozenset({"research", "python"})
    with pytest.raises(ValidationError):
        TeamMemoryUpdate(
            team_id="team-2",
            requester_agent_id="agent-1",
            record=record,
        )
    with pytest.raises(ValidationError):
        TeamMemoryQuery(team_id="team-1", requester_agent_id="agent-1", tags=frozenset({"BAD TAG"}))
