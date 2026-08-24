"""
tests/test_contracts/test_wx_speak_contract.py — 小程序口语对练契约（2026-08-24）
"""
from __future__ import annotations


def test_wx_speak_start_contract(client, auth_headers):
    res = client.post("/api/wx/speak/practice/start", headers=auth_headers)
    if res.status_code == 200:
        body = res.json()
        required = {"session_id", "part", "part_label", "topic_id", "topic", "question", "vocab", "sample_answer", "tips"}
        missing = required - body.keys()
        assert not missing, f"start 响应缺字段: {missing}; 实际: {body.keys()}"


def test_wx_speak_submit_unauthenticated(client):
    res = client.post("/api/wx/speak/practice/submit", json={})
    assert res.status_code in (401, 403, 422)


def test_wx_speak_history_contract(client, auth_headers):
    res = client.get("/api/wx/speak/practice/history", headers=auth_headers)
    if res.status_code == 200:
        body = res.json()
        assert "items" in body


def test_wx_speak_record_detail_route_exists(client, auth_headers):
    res = client.get("/api/wx/speak/practice/1", headers=auth_headers)
    assert res.status_code != 404


def test_wx_speak_endpoints_all_exist(client, auth_headers):
    endpoints = [
        ("POST", "/api/wx/speak/practice/start"),
        ("POST", "/api/wx/speak/practice/submit"),
        ("GET", "/api/wx/speak/practice/history"),
        ("GET", "/api/wx/speak/practice/1"),
    ]
    for method, url in endpoints:
        if method == "GET":
            r = client.get(url, headers=auth_headers)
        else:
            r = client.post(url, headers=auth_headers, data={})
        assert r.status_code != 404