import pytest

from icm_harness.policies import WriteScope, WriteScopeCheck


def test_permits_within_allowlist():
    scope = WriteScope("builder", allowed_paths=("src/**", "tests/**"))
    assert scope.permits("src/pkg/mod.py")
    assert scope.permits("tests/test_mod.py")
    assert not scope.permits("docs/readme.md")


def test_deny_wins_over_allow():
    scope = WriteScope(
        "builder", allowed_paths=("src/**",), denied_paths=("src/secrets/*",)
    )
    assert scope.permits("src/app.py")
    assert not scope.permits("src/secrets/keys.py")


def test_leading_dot_slash_and_backslashes_normalize():
    scope = WriteScope("builder", allowed_paths=("src/*",))
    assert scope.permits("./src/app.py")
    assert scope.permits("src\\app.py")


def test_traversal_is_rejected():
    scope = WriteScope("builder", allowed_paths=("src/**",))
    with pytest.raises(ValueError):
        scope.permits("src/../etc/passwd")


def test_empty_path_is_rejected():
    scope = WriteScope("builder", allowed_paths=("src/**",))
    with pytest.raises(ValueError):
        scope.permits("   ")


def test_violations_are_ordered_and_deduplicated():
    scope = WriteScope("builder", allowed_paths=("src/**",))
    result = scope.violations(["src/a.py", "docs/x.md", "./docs/x.md", "cfg.toml"])
    assert result == ("docs/x.md", "cfg.toml")


def test_violations_rejects_bare_string():
    scope = WriteScope("builder", allowed_paths=("src/**",))
    with pytest.raises(TypeError):
        scope.violations("src/a.py")


def test_empty_allowlist_permits_nothing():
    scope = WriteScope("observer")
    assert scope.violations(["anything.py"]) == ("anything.py",)


def test_check_reports_verdict():
    scope = WriteScope("builder", allowed_paths=("src/**",))
    ok = scope.check(["src/a.py"])
    assert ok == WriteScopeCheck("builder", in_scope=True, violations=())
    bad = scope.check(["docs/x.md"])
    assert not bad.in_scope
    assert bad.violations == ("docs/x.md",)
