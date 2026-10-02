"""The desktop stays up without a model. Intelligence, agents, and notes are seams."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.agents.create import AgentPathError, agent_for_task, load_created, write_agent
from core.agents.registry import AgentRegistry
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.models.catalog import CatalogModel, ModelCatalog
from core.workers.pool import admit_worker
from omne.connection import ConnectionPathError, connect_api_key, select_local_model
from omne.firstboot import apply_theme
from omne.secrets.providers.memory import MemorySecretProvider
from omne.secrets.service import SecretService
from omne.vault import ObsidianVault, remember_task

THEME = {
    "colors": {
        "accent": "#e4c27a",
        "desktop": "#152433",
        "glass": "#12171d",
        "ink": "#f3efe6",
        "muted": "#c5c0b6",
    },
    "type": '"Segoe UI", ui-sans-serif, system-ui, sans-serif',
    "wallpaper": "linear-gradient(180deg, #24384c 0%, #152433 100%)",
}
SECRET = "sk-test-secret-value"


def _secrets() -> SecretService:
    def allow(tool_id: str, agent_id: str, grants: object, environment: str, arguments: object):
        del tool_id, agent_id, grants, environment, arguments
        return "ALLOW", "test"

    return SecretService(MemorySecretProvider(), authorize=allow)


def test_desktop_works_while_intelligence_is_off(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    status, body = route_get(omne, "/intelligence", {})

    assert status.value == 200
    assert body["enabled"] is False
    assert body["desktop"] is True
    assert "tasks" in omne.desktop_view()
    assert isinstance(omne.network_view(), dict)
    assert isinstance(omne.applications_view(), dict)


def test_api_key_stays_out_of_the_theme_and_a_local_model_is_only_an_id(
    tmp_path: Path,
) -> None:
    data = tmp_path / "memory"
    data.mkdir()
    apply_theme(data, THEME)
    secrets = _secrets()

    connected = connect_api_key(data, secrets, environment="testing", provider="xai", key=SECRET)

    assert connected["enabled"] is True
    assert connected["provider"] == "xai"
    combined = (data / "theme.json").read_text(encoding="utf-8")
    combined += (data / "intelligence.json").read_text(encoding="utf-8")
    assert SECRET not in combined
    assert "password" not in (data / "intelligence.json").read_text(encoding="utf-8")
    selected = select_local_model(data, "local-notes", secrets=secrets, environment="testing")
    assert selected["local_model"] == "local-notes"
    assert selected["enabled"] is True
    assert list(data.rglob("*.gguf")) == []
    assert list(data.rglob("*.bin")) == []
    with pytest.raises(ConnectionPathError):
        select_local_model(Path("/boot"), "local-notes", secrets=None, environment="testing")
    with pytest.raises(ValueError):
        select_local_model(data, "/usr/share/weights", secrets=None, environment="testing")


def test_models_can_be_added_removed_and_routed_by_difficulty() -> None:
    catalog = ModelCatalog()
    catalog.add(CatalogModel(id="draft", provider="local", difficulty="easy", local=True))
    catalog.add(CatalogModel(id="reasoner", provider="xai", difficulty="hard", local=False))

    assert catalog.route("easy").id == "draft"
    assert catalog.route("hard").id == "reasoner"
    catalog.add_to_agent("notes", "reasoner")
    assert catalog.route("easy", agent_id="notes").id == "reasoner"
    catalog.remove_from_agent("notes", "reasoner")
    assert catalog.models_for("notes") == []
    catalog.remove("draft")
    assert catalog.route("easy").id == "reasoner"
    with pytest.raises(KeyError):
        catalog.remove("draft")
    with pytest.raises(KeyError):
        catalog.route("normal", agent_id="notes")


def test_a_task_sentence_creates_an_agent_workers_can_admit(tmp_path: Path) -> None:
    manifest = agent_for_task("review my notes")
    path = write_agent(tmp_path / "agents", manifest)
    loaded = load_created(path)
    registry = AgentRegistry()
    registry.register(loaded)

    assert registry.get(loaded.id).description == "review my notes"
    assert (
        admit_worker(
            active=0,
            max_workers=loaded.max_workers,
            cpu_percent=1.0,
            requested_ram_mb=64,
            ram_limit_mb=1024,
        )
        == "ALLOW"
    )
    with pytest.raises(AgentPathError):
        write_agent(Path("/usr/lib/omne/agents"), manifest)


def test_a_task_writes_a_vault_note_and_a_later_read_sees_it(tmp_path: Path) -> None:
    vault = ObsidianVault(tmp_path / "vault")

    remember_task(vault, "shopping list", "buy milk")
    assert "buy milk" in vault.read_note("shopping list")
    remember_task(vault, "shopping list", "buy bread")
    text = vault.read_note("shopping list")

    assert "buy milk" in text
    assert "buy bread" in text
    assert list(vault.root.glob("*.md"))
    assert not (tmp_path / "boot").exists()


def test_intelligence_route_does_not_echo_a_key(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    status, body = route_post(omne, "/intelligence/key", {"provider": "xai", "key": SECRET})

    assert status.value == 200
    assert body["enabled"] is True
    assert SECRET not in str(body)
    status, body = route_post(omne, "/intelligence/local", {"model_id": "local-notes"})
    assert status.value == 200
    assert body["local_model"] == "local-notes"
    assert list((tmp_path / "memory").rglob("*.gguf")) == []


def test_unlocked_shell_can_create_an_agent_without_downloading_weights(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_post(omne, "/intelligence/local", {"model_id": "local-notes"})
    assert status.value == 200
    assert body["enabled"] is True

    status, body = route_post(omne, "/agents", {"task": "review my notes"})

    assert status.value == 200
    assert body["weights"] is False
    assert body["agent"]["id"] == "review-my-notes"
    assert body["agent"]["created"] is True
    assert body["model"] == "local-notes"
    assert body["models"] == ["local-notes"]
    written = tmp_path / "memory" / "agents" / "review-my-notes" / "agent.toml"
    assert written.is_file()
    stored = written.read_text(encoding="utf-8")
    assert SECRET not in stored
    assert list((tmp_path / "memory").rglob("*.gguf")) == []
    status, again = route_post(omne, "/agents", {"task": "review my notes"})
    assert status.value == 200
    assert again["agent"]["created"] is False
    status, listing = route_get(omne, "/agents", {})
    assert "review-my-notes" in {item["id"] for item in listing["agents"]}
    rebooted = build_OMNE(runtime_settings(tmp_path))
    status, listing = route_get(rebooted, "/agents", {})
    assert "review-my-notes" in {item["id"] for item in listing["agents"]}
