"""API 层契约：配置解析、kb 白名单、上传体积上限、无依据分支。

全部用例不依赖外部服务（Ollama 不在也能跑）：无依据分支会先撞检索降级，再走闸门拒答。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ownrag.config import get_settings, reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    from ownrag.main import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


@pytest.fixture()
def tiny_limit_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OWNRAG_MAX_UPLOAD_MB", "1")
    reset_settings_cache()
    from ownrag.main import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


def test_config_解析到包内目录():
    settings = get_settings()
    assert (settings.config_dir / "pipelines.yaml").is_file()
    assert (settings.prompts_dir / "policy_strict_v1.yaml").is_file()
    assert settings.known_kbs == {"policy_v1"}
    assert settings.max_upload_mb > 0 and settings.max_new_tokens > 0


def test_health_and_admin_health(client):
    assert client.get("/health").json()["ok"] is True
    body = client.get("/admin/health").json()
    assert body["pipeline_missing_steps"] == []          # 启动期 DSL 校验必须干净
    assert body["known_kbs"] == ["policy_v1"]
    assert body["limits"]["max_new_tokens"] > 0
    assert body["config_dir"].endswith("configs")


def test_拒绝未声明的知识库(client):
    r = client.post("/docs/upload", files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")},
                    data={"kb": "not_declared"})
    assert r.status_code == 422
    assert "未声明的知识库" in r.json()["detail"]


def test_拒绝不支持的扩展名(client):
    r = client.post("/docs/upload", files={"file": ("a.exe", b"MZ", "application/octet-stream")},
                    data={"kb": "policy_v1"})
    assert r.status_code == 415


def test_上传超限拒绝并清理(tiny_limit_client):
    payload = b"x" * (2 * 1024 * 1024)                    # 2MB > 1MB 上限
    r = tiny_limit_client.post("/docs/upload",
                               files={"file": ("big.csv", payload, "text/csv")},
                               data={"kb": "policy_v1"})
    assert r.status_code == 413
    files_dir = get_settings().files_dir
    assert not files_dir.exists() or not any(files_dir.iterdir())   # 不留半截文件


def test_无依据不生成(client):
    with client.stream("POST", "/chat", json={"app": "policy_qa",
                                              "question": "完全无关的问题 zzzz"}) as resp:
        body = "".join(resp.iter_lines())
    assert "event: no_evidence" in body
    assert "event: done" in body


def test_未定义应用返回404(client):
    r = client.post("/chat", json={"app": "nope", "question": "x"})
    assert r.status_code == 404


@pytest.mark.parametrize("ext", [".csv"])
def test_csv_入库成功(client, ext):
    pytest.importorskip("pandas")
    csv = "名称,金额\nA公司,1234\n".encode("utf-8-sig")
    r = client.post("/docs/upload", files={"file": (f"t{ext}", csv, "text/csv")},
                    data={"kb": "policy_v1"})
    assert r.status_code == 200
    doc_id = r.json()["doc_id"]
    status = client.get(f"/docs/{doc_id}/status").json()
    assert status["task"]["status"] == "done"
    assert any(s["step"] == "main:index_upsert" and s["status"] == "ok"
               for s in status["steps"])
