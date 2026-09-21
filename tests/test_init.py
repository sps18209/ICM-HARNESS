from __future__ import annotations

from icm_harness.cli.app import main
from icm_harness.templates.engine import ENGINE_MD, POINTER_START


def _init(path) -> int:
    return main(["init", str(path)])


def test_fresh_init_scaffolds_engine_and_pointer(tmp_path):
    assert _init(tmp_path) == 0
    assert (tmp_path / ".harness/config.toml").exists()
    assert (tmp_path / "0_Context_Wiki").is_dir()
    assert (tmp_path / ".icm/ENGINE.md").read_text(encoding="utf-8") == ENGINE_MD
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert POINTER_START in claude


def test_existing_claude_md_is_preserved_and_pointer_appended(tmp_path):
    keep = "# NoCoast\n\nCarefully-built 98-line context layer.\n"
    (tmp_path / "CLAUDE.md").write_text(keep, encoding="utf-8")

    assert _init(tmp_path) == 0

    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Carefully-built 98-line context layer." in text  # original content intact
    assert POINTER_START in text  # engine pointer appended
    assert (tmp_path / ".icm/ENGINE.md").exists()


def test_init_is_idempotent_no_duplicate_pointer(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# NoCoast\n", encoding="utf-8")
    assert _init(tmp_path) == 0
    assert _init(tmp_path) == 0
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count(POINTER_START) == 1


def test_existing_template_file_and_config_are_not_clobbered(tmp_path):
    (tmp_path / "AGENTS.md").write_text("MY AGENTS RULES\n", encoding="utf-8")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness/config.toml").write_text("# my custom config\n", encoding="utf-8")

    assert _init(tmp_path) == 0

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "MY AGENTS RULES\n"
    assert (tmp_path / ".harness/config.toml").read_text(encoding="utf-8") == "# my custom config\n"


def test_force_overwrites_existing_files(tmp_path):
    (tmp_path / "AGENTS.md").write_text("MY AGENTS RULES\n", encoding="utf-8")
    assert main(["init", str(tmp_path), "--force"]) == 0
    # The shipped template AGENTS.md replaced the user's file under --force.
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") != "MY AGENTS RULES\n"
    assert "CONTEXT.md" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_init_typesafe_flag_enables_jev_intake(tmp_path, capsys):
    assert main(["init", str(tmp_path), "--typesafe"]) == 0
    config = (tmp_path / ".harness/config.toml").read_text(encoding="utf-8")
    assert 'profiler = "typesafe"' in config
    assert 'profiler = "claude-cli"' not in config
    assert "intake=typesafe" in capsys.readouterr().out


def test_init_typesafe_flag_is_idempotent(tmp_path):
    assert main(["init", str(tmp_path), "--typesafe"]) == 0
    assert main(["init", str(tmp_path), "--typesafe"]) == 0
    config = (tmp_path / ".harness/config.toml").read_text(encoding="utf-8")
    assert config.count('profiler = "typesafe"') == 1


def test_init_does_not_prompt_or_enable_without_a_terminal(tmp_path, monkeypatch):
    # Even with a discoverable key, non-interactive init must not opt in.
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_test")
    assert main(["init", str(tmp_path)]) == 0
    config = (tmp_path / ".harness/config.toml").read_text(encoding="utf-8")
    assert 'profiler = "claude-cli"' in config


def test_init_prompt_enables_on_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_test")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(
        "icm_harness.cli.app.importlib.util.find_spec", lambda name: object()
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert main(["init", str(tmp_path)]) == 0
    config = (tmp_path / ".harness/config.toml").read_text(encoding="utf-8")
    assert 'profiler = "typesafe"' in config


def test_init_prompt_respects_no(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_test")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(
        "icm_harness.cli.app.importlib.util.find_spec", lambda name: object()
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(["init", str(tmp_path)]) == 0
    config = (tmp_path / ".harness/config.toml").read_text(encoding="utf-8")
    assert 'profiler = "claude-cli"' in config
