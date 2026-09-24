"""Parse project agent definitions (.claude/agents/*.md frontmatter).

The frontmatter is the enforceable configuration surface: the tool list is what
the Claude Code runtime grants, so properties proven over it (read-only
reviewers, worktree isolation) hold for live runs, not just for fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pmpe.domain.errors import PmpeError


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    tools: tuple[str, ...]
    isolation: str  # "" or "worktree"
    path: str


class AgentRegistry:
    def __init__(self, agents_dir: Path) -> None:
        self.agents_dir = Path(agents_dir)
        self._agents: dict[str, AgentDefinition] = {}
        for path in sorted(self.agents_dir.glob("*.md")):
            definition = _parse(path)
            if definition is not None:
                self._agents[definition.name] = definition

    def get(self, name: str) -> AgentDefinition:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise PmpeError(f"no agent definition named '{name}' in {self.agents_dir}") from exc

    def has(self, name: str) -> bool:
        return name in self._agents

    def all(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def v2_agents(self) -> list[AgentDefinition]:
        return [a for a in self._agents.values() if a.name.startswith("v2-")]


def _parse(path: Path) -> AgentDefinition | None:
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    name = fields.get("name", "")
    if not name:
        return None
    tools = tuple(tool.strip() for tool in fields.get("tools", "").split(",") if tool.strip())
    return AgentDefinition(
        name=name,
        description=fields.get("description", ""),
        tools=tools,
        isolation=fields.get("isolation", ""),
        path=str(path),
    )
