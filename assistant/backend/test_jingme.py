import asyncio
import json

from assistant.backend.jingme import JingMeMockAdapter, O2JingMeAdapter, build_jingme_message, get_jingme_status
from assistant.backend.main import JingMeSendRequest, jingme_send


def result():
    return {
        "tool": "station_summary",
        "province": "脱敏省区",
        "date": "2026-10-12",
        "stations": [{"erp": "erp-demo-01", "visits": 3}],
    }


def test_mock_runs_and_uses_structured_result():
    message = build_jingme_message(result())
    assert "erp-demo-01：3" in message
    response = asyncio.run(JingMeMockAdapter().send_text(analysis_result=result(), erp="erp-demo-01"))
    assert response == {"success": True, "channel": "jingme-mock", "message": "已模拟发送京ME通报", "dry_run": True}


def test_real_adapter_calls_jdme_after_confirmation_layer_passes_payload(monkeypatch):
    calls = []

    def runner(request, dry_run):
        calls.append((request, dry_run))
        return {"ok": True, "data": {"packet_id": "packet-demo"}}

    monkeypatch.setenv("JINGME_ENABLED", "true")
    monkeypatch.setenv("JME_APP_KEY", "secret-key")
    monkeypatch.setenv("JME_APP_SECRET", "secret-value")
    monkeypatch.setenv("JME_OPEN_TEAM_ID", "team-secret")
    monkeypatch.setenv("JME_ROBOT_ID", "robot-secret")
    monkeypatch.setattr("assistant.backend.jingme.shutil.which", lambda command: command)
    response = asyncio.run(O2JingMeAdapter(runner).send_text(
        analysis_result=result(), erp="erp-demo-01"
    ))
    assert response["success"] is True
    assert response["packet_id"] == "packet-demo"
    assert calls[0][0]["content"] == build_jingme_message(result())
    assert calls[0][0]["erp"] == "erp-demo-01"


def test_dry_run_does_not_require_credentials_and_marks_request():
    calls = []

    def runner(request, dry_run):
        calls.append(dry_run)
        return {"ok": True, "data": {"dry_run": True}}

    response = asyncio.run(O2JingMeAdapter(runner).send_text(
        analysis_result=result(), group_id="group-demo", dry_run=True
    ))
    assert response["dry_run"] is True
    assert calls == [True]


def test_status_does_not_expose_secret_or_recipient(monkeypatch):
    monkeypatch.setenv("JME_APP_SECRET", "do-not-log")
    monkeypatch.setenv("JINGME_GROUP_ID", "group-secret")
    rendered = json.dumps(get_jingme_status(), ensure_ascii=False)
    assert "do-not-log" not in rendered
    assert "group-secret" not in rendered


def test_failed_cli_never_becomes_success():
    def runner(request, dry_run):
        return {"ok": False, "error": {"code": "JME_API_ERROR"}}

    try:
        asyncio.run(O2JingMeAdapter(runner).send_text(
            analysis_result=result(), erp="erp-demo-01", dry_run=True
        ))
    except RuntimeError as exc:
        assert "发送失败" in str(exc)
    else:
        raise AssertionError("失败的京ME调用不应返回成功")


def test_unconfirmed_request_does_not_call_adapter(monkeypatch):
    class NeverCalled:
        async def send_text(self, **kwargs):
            raise AssertionError("未确认请求不应触发发送")

    monkeypatch.setattr("assistant.backend.main.get_jingme_adapter", lambda: NeverCalled())
    response = asyncio.run(jingme_send(JingMeSendRequest(
        analysis_result=result(), confirmed=False, erp="erp-demo-01"
    )))
    assert response.status_code == 400
