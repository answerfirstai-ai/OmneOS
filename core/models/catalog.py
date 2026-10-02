"""User-managed model list. Entries are metadata. Weights are not downloaded."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Difficulty = Literal["easy", "normal", "hard"]
_RANK = {"easy": 0, "normal": 1, "hard": 2}


class CatalogModel(BaseModel):
    """One model the core or an agent may use. There is no weight file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    provider: Literal["mock", "xai", "local", "nvidia"]
    difficulty: Difficulty
    local: bool = False


class ModelCatalog:
    """Add and remove models, then pick one for a difficulty."""

    def __init__(self) -> None:
        self._models: dict[str, CatalogModel] = {}
        self._agents: dict[str, list[str]] = {}

    def add(self, model: CatalogModel) -> CatalogModel:
        if model.id in self._models:
            raise ValueError(f"duplicate model identifier: {model.id}")
        self._models[model.id] = model
        return model

    def remove(self, model_id: str) -> None:
        if model_id not in self._models:
            raise KeyError(f"unknown model: {model_id}")
        del self._models[model_id]
        for agent_id, models in self._agents.items():
            self._agents[agent_id] = [item for item in models if item != model_id]

    def add_to_agent(self, agent_id: str, model_id: str) -> None:
        if model_id not in self._models:
            raise KeyError(f"unknown model: {model_id}")
        models = self._agents.setdefault(agent_id, [])
        if model_id not in models:
            models.append(model_id)

    def remove_from_agent(self, agent_id: str, model_id: str) -> None:
        models = self._agents.get(agent_id)
        if models is None or model_id not in models:
            raise KeyError(f"agent {agent_id} does not use {model_id}")
        self._agents[agent_id] = [item for item in models if item != model_id]

    def models_for(self, agent_id: str) -> list[str]:
        return list(self._agents.get(agent_id, []))

    def route(self, difficulty: str, *, agent_id: str | None = None) -> CatalogModel:
        """Pick a model for this difficulty. An agent route uses only its models."""

        if difficulty not in _RANK:
            raise ValueError("unknown difficulty")
        pool = self._pool(agent_id)
        exact = [model for model in pool if model.difficulty == difficulty]
        if exact:
            return sorted(exact, key=lambda model: model.id)[0]
        target = _RANK[difficulty]
        return sorted(pool, key=lambda model: (abs(_RANK[model.difficulty] - target), model.id))[0]

    def _pool(self, agent_id: str | None) -> list[CatalogModel]:
        if agent_id is None:
            pool = list(self._models.values())
        else:
            pool = [
                self._models[model_id]
                for model_id in self._agents.get(agent_id, [])
                if model_id in self._models
            ]
        if not pool:
            raise KeyError("no model is available")
        return pool
