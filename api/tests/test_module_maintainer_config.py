"""Config-only test: prove the deployed API environment carries the module
maintainer (trusted principal).

The publish and backend-dispatch gates (`Y_AGENT_MODULE_MAINTAINER_USER_ID`)
fail closed when unset, so the value must be plumbed into the deployed API
Lambda environment from `template.yaml`, the same way `GoogleClientId` is.
This test is intentionally YAML-light (text assertions on the template): it
keeps the api test env free of extra deps and can't import the app.
"""

from pathlib import Path

EXPECTED_USER_ID = "4e3938bd4da22878a12f094f18ffa543_luohycs_at_gmail_dot_com"

_TEMPLATE = Path(__file__).resolve().parents[2] / "template.yaml"


def _template_text():
    return _TEMPLATE.read_text()


def test_maintainer_user_id_parameter_defined_with_expected_default():
    text = _template_text()
    assert "ModuleMaintainerUserId:" in text
    assert EXPECTED_USER_ID in text
    # parameter sits in the Parameters block, next to GoogleClientId
    assert text.index("ModuleMaintainerUserId:") > text.index("GoogleClientId:")
    assert text.index("GoogleClientId:") < text.index("SubnetIds:")


def test_maintainer_user_id_plumbed_into_api_environment():
    text = _template_text()
    # only the API function carries it (publish + dispatch gates live in API)
    assert "Y_AGENT_MODULE_MAINTAINER_USER_ID: !Ref ModuleMaintainerUserId" in text
    api_env = text.index("APIFunction:")
    assert text.index("Y_AGENT_MODULE_MAINTAINER_USER_ID") > api_env
