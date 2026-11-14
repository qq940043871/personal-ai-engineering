"""MinerU 开放平台客户端 + parse_mineru open 模式：外部 HTTP 全打桩，零出网。

覆盖：三步流 happy path / failed 透传 err_msg / 业务 code≠0 / 轮询超时 / 缺 token /
PUT 裸传不带头（OSS 签名坑回归）/ zip-slip 防护 / 步骤级接入与 is_ocr 默认语义。
"""
import io
import json
import types
import zipfile
from pathlib import Path

import pytest

import ownrag.ingest.mineru_openapi as mo
import ownrag.steps  # noqa: F401  触发全部步骤注册（与 test_pipeline 同口径）
from ownrag.core.pipeline import StepContext
from ownrag.core.registry import STEP_REGISTRY


class _Resp:
    """最小 httpx.Response 替身：只实现本客户端用到的方法。"""

    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    @property
    def is_error(self):
        return self.status_code >= 400

    def raise_for_status(self):
        assert not self.is_error, f"测试打桩未预期 HTTP {self.status_code}"

    def json(self):
        return self._payload


def _build_zip_bytes(slip: bool = False) -> bytes:
    """构造结果 zip：full.md + images/ + *_content_list.json（slip=True 追加逃逸成员）。"""
    content_list = [
        {"type": "text", "text": "你好", "page_idx": 0},
        {"type": "image", "img_path": "images/a.jpg", "page_idx": 0},
        {"type": "table", "table_body": "<table><tr><td>1</td></tr></table>", "page_idx": 1},
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# 报告\n\n![img](images/a.jpg)\n")
        zf.writestr("images/a.jpg", b"fake-jpeg")
        zf.writestr("doc_content_list.json", json.dumps(content_list, ensure_ascii=False))
        if slip:
            zf.writestr("../evil.txt", "boom")
    return buf.getvalue()


def _install_fake_api(monkeypatch, calls):
    """打桩三步流的前两步与轮询 GET：申请链接 → 裸 PUT → []/running/done 三轮。"""
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("post", url, json, headers))
        return _Resp({"code": 0, "msg": "ok",
                      "data": {"batch_id": "b1", "file_urls": ["http://oss.test/put-url"]}})

    def fake_put(url, content=None, headers=None, timeout=None):
        calls.append(("put", url, headers))
        return _Resp({})

    poll_seq = iter([
        {"code": 0, "data": {"extract_result": []}},                      # 上传还没被扫描提交
        {"code": 0, "data": {"extract_result": [
            {"file_name": "a.pdf", "data_id": "doc1", "state": "running"}]}},
        {"code": 0, "data": {"extract_result": [
            {"file_name": "a.pdf", "data_id": "doc1", "state": "done",
             "full_zip_url": "http://oss.test/result.zip"}]}},
    ])

    def fake_get(url, headers=None, timeout=None):
        calls.append(("get", url, headers))
        return _Resp(next(poll_seq))

    monkeypatch.setattr(mo.httpx, "post", fake_post)
    monkeypatch.setattr(mo.httpx, "put", fake_put)
    monkeypatch.setattr(mo.httpx, "get", fake_get)


def _install_fake_download(monkeypatch, slip: bool = False):
    zip_bytes = _build_zip_bytes(slip)

    class _StreamResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield zip_bytes

    class _FakeStreamCtx:
        def __enter__(self):
            return _StreamResp()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(mo.httpx, "stream", lambda method, url, timeout=None, **kw: _FakeStreamCtx())


# ---------------------------------------------------------------- 客户端层
def test_openapi_happy_path(monkeypatch, tmp_path):
    calls = []
    _install_fake_api(monkeypatch, calls)
    _install_fake_download(monkeypatch)
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-fake")

    md, assets, structures, stats = mo.parse_via_openapi(
        src, doc_id="doc1", base_url="http://api.test/v4", token="tok",
        model_version="vlm", poll_interval=0, out_dir=tmp_path / "out")

    assert md.startswith("# 报告") and "images/a.jpg" in md      # md 图片相对引用原样保留
    assert set(assets) == {"a"} and Path(assets["a"]).is_file()
    kinds = {s.kind: s for s in structures}
    assert kinds["image"].pointer == "images/a.jpg" and kinds["image"].location == "page:0"
    assert kinds["table"].location == "page:1" and "<table>" in kinds["table"].text
    assert stats == {"pages": 2, "mode": "open", "model_version": "vlm", "batch_id": "b1"}

    (_, post_url, body, post_headers), = [c for c in calls if c[0] == "post"]
    assert post_url == "http://api.test/v4/file-urls/batch"
    assert post_headers["Authorization"] == "Bearer tok"
    assert body["model_version"] == "vlm" and body["files"][0]["data_id"] == "doc1"
    (_, put_url, put_headers), = [c for c in calls if c[0] == "put"]
    assert put_url == "http://oss.test/put-url"
    assert put_headers is None   # 预签名 URL 裸传：任何附加头（Content-Type/Authorization）都会 403
    get_calls = [c for c in calls if c[0] == "get"]
    assert [c[1] for c in get_calls] == ["http://api.test/v4/extract-results/batch/b1"] * 3
    assert get_calls[0][2]["Authorization"] == "Bearer tok"


def test_openapi_failed_state_surfaced(monkeypatch, tmp_path):
    """failed → err_msg 原样进异常消息：错误可见才能进待办人工处理。"""
    monkeypatch.setattr(mo.httpx, "post", lambda url, **kw: _Resp(
        {"code": 0, "data": {"batch_id": "b1", "file_urls": ["u"]}}))
    monkeypatch.setattr(mo.httpx, "put", lambda url, **kw: _Resp({}))
    monkeypatch.setattr(mo.httpx, "get", lambda url, **kw: _Resp(
        {"code": 0, "data": {"extract_result": [
            {"file_name": "a.pdf", "state": "failed", "err_msg": "渲染引擎崩溃"}]}}))
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="渲染引擎崩溃"):
        mo.parse_via_openapi(src, doc_id="d", base_url="http://x", token="t",
                             out_dir=tmp_path / "o")


def test_openapi_business_error_code(monkeypatch, tmp_path):
    """code≠0（如 -60018 每日额度）直接抛，不进轮询。"""
    monkeypatch.setattr(mo.httpx, "post", lambda url, **kw: _Resp(
        {"code": -60018, "msg": "今日任务数已达上限"}))
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="-60018"):
        mo.parse_via_openapi(src, doc_id="d", base_url="http://x", token="t",
                             out_dir=tmp_path / "o")


def test_openapi_poll_timeout(monkeypatch, tmp_path):
    """一直 running → 按 poll_timeout 超时，错误带现场状态。"""
    monkeypatch.setattr(mo.httpx, "post", lambda url, **kw: _Resp(
        {"code": 0, "data": {"batch_id": "b1", "file_urls": ["u"]}}))
    monkeypatch.setattr(mo.httpx, "put", lambda url, **kw: _Resp({}))
    monkeypatch.setattr(mo.httpx, "get", lambda url, **kw: _Resp(
        {"code": 0, "data": {"extract_result": [
            {"file_name": "a.pdf", "state": "running", "extract_progress":
                {"extracted_pages": 1, "total_pages": 2}}]}}))
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="超时"):
        mo.parse_via_openapi(src, doc_id="d", base_url="http://x", token="t",
                             poll_interval=0, poll_timeout=0.05, out_dir=tmp_path / "o")


def test_openapi_missing_token(tmp_path):
    """缺 token 在提交前就炸（配置错误不该消耗任何云端调用）。"""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="MINERU_OPEN_TOKEN"):
        mo.parse_via_openapi(src, doc_id="d", base_url="http://x", token=None,
                             out_dir=tmp_path / "o")


def test_download_extract_blocks_zip_slip(monkeypatch, tmp_path):
    """防路径逃逸：父级跳转成员被丢弃，正常产物完整落地。"""
    _install_fake_download(monkeypatch, slip=True)
    out = tmp_path / "out"
    out.mkdir()
    mo._download_extract("http://oss.test/result.zip", out)
    assert (out / "full.md").is_file()
    assert (out / "images" / "a.jpg").is_file()
    assert not (tmp_path / "evil.txt").exists()
    assert not (out / "evil.txt").exists()


# ---------------------------------------------------------------- 步骤层
def _step_ctx(settings, data):
    return StepContext(doc_id="doc1", trace_id="t", kb="policy_v1", conn=None,
                       settings=settings, data=data)


def _open_settings(tmp_path, token="tok"):
    return types.SimpleNamespace(
        mineru_mode="open", mineru_open_token=token,
        mineru_open_base_url="http://api.test/v4", parsed_dir=tmp_path / "parsed")


def test_step_open_mode(monkeypatch, tmp_path):
    """open 模式整链：步骤产出 parsed 落黑板，metrics 带路由出的 backend。"""
    calls = []
    _install_fake_api(monkeypatch, calls)
    _install_fake_download(monkeypatch)
    src = tmp_path / "source.pdf"
    src.write_bytes(b"%PDF")
    step = STEP_REGISTRY["parse_mineru"]()
    ctx = _step_ctx(_open_settings(tmp_path),
                    {"source_path": str(src), "page_route": "vlm",
                     "source_meta": {"source_file": "书.pdf"}})
    result = step.run(ctx, {"backend": "auto", "lang": "ch"})
    assert result.status == "ok" and result.metrics["backend"] == "vlm"
    parsed = ctx.data["parsed"]
    assert parsed["markdown"].startswith("# 报告")
    assert parsed["metadata"]["source_file"] == "书.pdf"
    assert parsed["stats"]["mode"] == "open" and parsed["stats"]["backend"] == "vlm"
    body = next(c[2] for c in calls if c[0] == "post")
    # 路由判了扫描件但 model_version 已是 vlm（内置视觉理解）→ 不强制 is_ocr
    assert body["files"][0]["is_ocr"] is False


def test_step_open_mode_ocr_default_when_pipeline_on_scan(monkeypatch, tmp_path):
    """路由判了扫描件（page_route=vlm）却显式走 pipeline → is_ocr 默认强制开。"""
    calls = []
    _install_fake_api(monkeypatch, calls)
    _install_fake_download(monkeypatch)
    src = tmp_path / "source.pdf"
    src.write_bytes(b"%PDF")
    step = STEP_REGISTRY["parse_mineru"]()
    ctx = _step_ctx(_open_settings(tmp_path),
                    {"source_path": str(src), "page_route": "vlm", "source_meta": {}})
    assert step.run(ctx, {"backend": "pipeline"}).status == "ok"
    body = next(c[2] for c in calls if c[0] == "post")
    assert body["model_version"] == "pipeline" and body["files"][0]["is_ocr"] is True


def test_step_open_mode_missing_token_fails_before_cloud(tmp_path):
    """缺 token 抛 RuntimeError（真实管道由 _invoke 兜底转 StepResult.fail → fallback 链）。"""
    src = tmp_path / "source.pdf"
    src.write_bytes(b"%PDF")
    step = STEP_REGISTRY["parse_mineru"]()
    ctx = _step_ctx(_open_settings(tmp_path, token=None),
                    {"source_path": str(src), "page_route": "pipeline", "source_meta": {}})
    with pytest.raises(RuntimeError, match="MINERU_OPEN_TOKEN"):
        step.run(ctx, {})
