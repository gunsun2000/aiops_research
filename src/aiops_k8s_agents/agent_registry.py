from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class AgentRegistryError(ValueError):
    """Raised when an agent registry file is malformed or unsafe."""


@dataclass(frozen=True)
class AgentProfile:
    name: str
    korean_name: str
    role: str
    responsibilities: tuple[str, ...]
    bounded_actions: tuple[str, ...]
    reward_signals: tuple[str, ...]
    implementation_id: str = ""
    supported_runtimes: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        name = str(data.get("name", "")).strip()
        if not name:
            raise AgentRegistryError("agent name is required")
        actions = tuple(str(item) for item in data.get("bounded_actions", []))
        if not actions:
            raise AgentRegistryError(f"agent {name} must define bounded_actions")
        return cls(
            name=name,
            korean_name=str(data.get("korean_name", name)),
            role=str(data.get("role", "")),
            responsibilities=tuple(
                str(item) for item in data.get("responsibilities", [])
            ),
            bounded_actions=actions,
            reward_signals=tuple(str(item) for item in data.get("reward_signals", [])),
            implementation_id=str(data.get("implementation_id", "")),
            supported_runtimes=tuple(
                str(item) for item in data.get("supported_runtimes", [])
            ),
            capabilities=tuple(str(item) for item in data.get("capabilities", [])),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["responsibilities"] = list(self.responsibilities)
        data["bounded_actions"] = list(self.bounded_actions)
        data["reward_signals"] = list(self.reward_signals)
        data["supported_runtimes"] = list(self.supported_runtimes)
        data["capabilities"] = list(self.capabilities)
        return data


@dataclass
class AgentRegistry:
    version: str
    agents: dict[str, AgentProfile]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRegistry:
        profiles: dict[str, AgentProfile] = {}
        for raw_profile in data.get("agents", []):
            profile = AgentProfile.from_dict(dict(raw_profile))
            if profile.name in profiles:
                raise AgentRegistryError(f"duplicate agent: {profile.name}")
            profiles[profile.name] = profile
        if not profiles:
            raise AgentRegistryError("registry must contain at least one agent")
        return cls(version=str(data.get("version", "1")), agents=profiles)

    def agent_names(self) -> list[str]:
        return sorted(self.agents)

    def get(self, name: str) -> AgentProfile:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise AgentRegistryError(f"unknown agent: {name}") from exc

    def validate_action(self, agent_name: str, action: str) -> bool:
        profile = self.get(agent_name)
        return profile.enabled and action in profile.bounded_actions

    def upsert(self, profile: AgentProfile, *, overwrite: bool = True) -> None:
        if profile.name in self.agents and not overwrite:
            raise AgentRegistryError(f"agent already exists: {profile.name}")
        self.agents[profile.name] = profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "agents": [
                self.agents[name].to_dict()
                for name in self.agent_names()
            ],
        }


def load_agent_registry(path: str | Path) -> AgentRegistry:
    registry_path = Path(path)
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    return AgentRegistry.from_dict(data)


def save_agent_registry(registry: AgentRegistry, path: str | Path) -> None:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
