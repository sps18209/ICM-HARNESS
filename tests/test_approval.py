from icm_harness.policies import ActionRequest, ApprovalClass, classify, requires_human_gate


def test_local_reversible_is_the_only_ungated_class():
    for cls in ApprovalClass:
        expected = cls is not ApprovalClass.LOCAL_REVERSIBLE
        assert cls.requires_human_approval is expected


def test_default_action_is_local_reversible():
    req = ActionRequest("edit a local branch file")
    assert classify(req) is ApprovalClass.LOCAL_REVERSIBLE
    assert requires_human_gate(req) is False


def test_project_scope_change():
    req = ActionRequest("add a user-visible workflow", changes_approved_scope=True)
    assert classify(req) is ApprovalClass.PROJECT_SCOPE
    assert requires_human_gate(req) is True


def test_external_action_outranks_project_scope():
    req = ActionRequest(
        "deploy the change", changes_approved_scope=True, touches_external_surface=True
    )
    assert classify(req) is ApprovalClass.EXTERNAL_ACTION


def test_destructive_has_highest_precedence():
    req = ActionRequest(
        "force-push and drop a table",
        touches_external_surface=True,
        is_destructive=True,
        is_security_sensitive=True,
    )
    assert classify(req) is ApprovalClass.DESTRUCTIVE


def test_security_sensitive_outranks_external():
    req = ActionRequest(
        "transmit sensitive data",
        touches_external_surface=True,
        is_security_sensitive=True,
    )
    assert classify(req) is ApprovalClass.SECURITY_SENSITIVE


def test_safe_local_inspection_exempts_only_security_class():
    req = ActionRequest(
        "read secret config locally",
        is_security_sensitive=True,
        is_safe_local_inspection=True,
    )
    assert classify(req) is ApprovalClass.LOCAL_REVERSIBLE
    assert requires_human_gate(req) is False


def test_safe_local_inspection_does_not_exempt_destructive():
    req = ActionRequest(
        "wipe local secret store",
        is_destructive=True,
        is_security_sensitive=True,
        is_safe_local_inspection=True,
    )
    assert classify(req) is ApprovalClass.DESTRUCTIVE
