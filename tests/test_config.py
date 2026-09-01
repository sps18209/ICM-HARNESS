from icm_harness.config import load_config, write_default_config


def test_default_config_round_trips(tmp_path):
    path = write_default_config(tmp_path / ".harness/config.toml")
    config = load_config(tmp_path)
    assert path.exists()
    assert config.agent.provider == "codex-cli"
    assert config.models[0].name == "default"
    assert config.stage_budgets["build.planner"] == 9000


def test_environment_can_select_agent_without_rewriting_config(tmp_path):
    write_default_config(tmp_path / ".harness/config.toml")
    config = load_config(
        tmp_path,
        environ={
            "ICM_AGENT_PROVIDER": "dry-run",
            "ICM_AGENT_EXECUTABLE": "ignored",
            "ICM_AGENT_MODEL": "smoke",
        },
    )
    assert config.agent.provider == "dry-run"
    assert config.agent.model == "smoke"
