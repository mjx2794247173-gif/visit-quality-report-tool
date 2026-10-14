import json

import pytest

from feishu import MAX_MESSAGE_CHARS, build_message_arguments, get_feishu_status, validate_message


def test_status_never_exposes_credentials(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_secret_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "super-secret")
    monkeypatch.setenv("FEISHU_RECEIVE_ID", "oc_group")
    status = get_feishu_status()
    rendered = json.dumps(status)
    assert "super-secret" not in rendered
    assert "oc_group" not in rendered


def test_message_payload_is_text_and_target_comes_from_server(monkeypatch):
    monkeypatch.setenv("FEISHU_RECEIVE_ID", "oc_group")
    monkeypatch.setenv("FEISHU_RECEIVE_ID_TYPE", "chat_id")
    payload = build_message_arguments("浙江省区主要问题为拍照不规范。")
    assert payload["params"] == {"receive_id_type": "chat_id"}
    assert payload["data"]["receive_id"] == "oc_group"
    assert payload["data"]["msg_type"] == "text"
    assert json.loads(payload["data"]["content"])["text"].startswith("浙江省区")


def test_message_validation_rejects_empty_and_oversized_content():
    with pytest.raises(ValueError):
        validate_message("   ")
    with pytest.raises(ValueError):
        validate_message("字" * (MAX_MESSAGE_CHARS + 1))
