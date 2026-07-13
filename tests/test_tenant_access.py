import pytest
from fastapi import HTTPException

from app.core.tenant_access import enforce_active


def test_active_is_allowed():
    enforce_active("active")  # should not raise


def test_trial_is_allowed():
    enforce_active("trial")  # should not raise


def test_suspended_is_blocked():
    with pytest.raises(HTTPException) as exc_info:
        enforce_active("suspended")
    assert exc_info.value.status_code == 403


def test_unknown_status_raises_value_error():
    with pytest.raises(ValueError):
        enforce_active("deleted")
