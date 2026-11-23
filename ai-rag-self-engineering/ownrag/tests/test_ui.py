"""控制台与调试接口契约：页面可取、配置可读、直击库可维护、检索调试返回结构稳定。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ownrag.config import reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    from ownrag.main import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


def test_ui_page_served(client):
    # 入口 /ui 落概览页，仍离线可用、零外链
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "ownrag" in body
    assert "https://" not in body.split("</head>")[0]         # 头部零外链（离线可用）

    # 按功能拆分后的每个页面都可取
    for page in ("overview", "ingest", "review", "chat", "retrieve", "kb", "observe", "plan"):
        pr = client.get(f"/ui/{page}")
        assert pr.status_code == 200
        assert "text/html" in pr.headers["content-type"]
    # 页面必须对着真实接口
    assert "/admin/retrieve" in client.get("/ui/retrieve").text
    assert "/chat" in client.get("/ui/chat").text

    # 共享静态资源可取
    css = client.get("/ui/assets/app.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    js = client.get("/ui/assets/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    # 总菜单文件集中定义全部导航项
    menu = client.get("/ui/assets/menu.js").text
    for label in ("概览", "入库", "解析复核", "问答", "检索调试", "知识库", "观测", "14 天路线"):
        assert label in menu

    # 站点图标必须能从根路径取到（浏览器隐式探测 /favicon.ico，iOS 只认 /apple-touch-icon.png）
    ico = client.get("/favicon.ico")
    assert ico.status_code == 200 and ico.headers["content-type"] == "image/x-icon"
    assert ico.content[:4] == b"\x00\x00\x01\x00"            # ICONDIR，非空占位
    touch = client.get("/apple-touch-icon.png")
    assert touch.status_code == 200 and "image/png" in touch.headers["content-type"]


def test_root_redirects_to_ui(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (307, 302)
    assert r.headers["location"] == "/ui"


def test_config_view(client):
    d = client.get("/admin/config").json()
    assert set(d["pipelines"]) == {"pdf_v1", "av_v1", "excel_v1"}
    assert "policy_qa" in d["apps"]
    assert "policy_strict_v1" in d["prompts"]
    assert d["known_kbs"] == ["policy_v1"]
    assert d["limits"]["max_new_tokens"] > 0
    assert d["apps"]["policy_qa"]["generation"]["max_new_tokens"] > 0


def test_chunks_list_empty(client):
    d = client.get("/admin/chunks").json()
    assert d["mode"] == "list"
    assert d["total"] == 0 and d["chunks"] == []


def test_direct_hit_crud(client):
    created = client.post("/admin/direct_hits", json={
        "kb": "policy_v1", "level": "L0", "question": "报销上限是多少", "answer": "1234 元"
    }).json()
    assert created["status"] == "created"

    hits = client.get("/admin/direct_hits?kb=policy_v1").json()["hits"]
    assert len(hits) == 1 and hits[0]["answer"] == "1234 元"

    assert client.delete(f"/admin/direct_hits/{created['id']}").json()["status"] == "deleted"
    assert client.get("/admin/direct_hits").json()["hits"] == []


def test_direct_hit_rejects_unknown_kb(client):
    r = client.post("/admin/direct_hits", json={
        "kb": "nope", "level": "L0", "question": "q", "answer": "a"})
    assert r.status_code == 422


def test_retrieve_debug_shape(client):
    pytest.importorskip("pandas")
    csv = "名称,口径,金额\nA公司,报销口径说明,1234\n".encode("utf-8-sig")
    r = client.post("/docs/upload", files={"file": ("t.csv", csv, "text/csv")},
                    data={"kb": "policy_v1"})
    doc_id = r.json()["doc_id"]
    assert client.get(f"/docs/{doc_id}/status").json()["task"]["status"] == "done"

    d = client.post("/admin/retrieve", json={"question": "报销口径", "app": "policy_qa"}).json()
    for key in ("channels", "candidates", "budget", "gate_pre", "retrieval_path", "direct_hit"):
        assert key in d
    assert d["budget"]["kept"] >= 1
    assert d["gate_pre"]["passed"] is True
    assert {"bm25", "vector"} == set(d["channels"])
    assert d["candidates"][0]["chunk_id"].startswith(doc_id)


def test_task_detail_404(client):
    assert client.get("/admin/tasks/nope").status_code == 404
