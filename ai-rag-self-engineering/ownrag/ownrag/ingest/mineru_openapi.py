"""MinerU 开放平台（mineru.net /api/v4）HTTP 客户端 —— parse_mineru 的第三种模式（open）。

为什么是批量三步流而不是单文件提交（POST /extract/task）：后者只收 URL 不收本地文件。
官方契约（2026-11 按 mineru.net/apiManage/docs 核实）：
    1. POST /file-urls/batch     → batch_id + 预签名 PUT url（24h 有效）
    2. PUT 文件字节到预签名 URL  → 任何附加头（含 Content-Type）都会让 OSS 签名失效返回 403，
       也不带 Authorization；上传后平台自动提交解析，无需再调提交接口
    3. GET /extract-results/batch/{batch_id} 轮询 → waiting-file|pending|running|converting
       为进行中；done → full_zip_url；failed → err_msg
结果 zip：full.md + images/（md 内相对路径引用，须保持同级）+ *_content_list.json 等。

限制：单文件 ≤200MB / ≤200 页，批量 ≤50 个；每日页数额度见控制台（超限 code=-60018）。
错误统一 RuntimeError：pipeline 层 _invoke 兜底转 StepResult.fail → fallback 链，绝不静默丢文档。
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import httpx

from ownrag.ingest.base import Structure

API_BASE_DEFAULT = "https://mineru.net/api/v4"
# 进行中状态集合（官方口径）；waiting-file = 已申请链接但文件还没被平台扫描到
_IN_PROGRESS = {"waiting-file", "pending", "running", "converting"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _api_headers(token: str) -> dict[str, str]:
    """开放平台认证：Bearer + 空格 + Token。"""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 步骤①②：申请链接 + 上传
def _apply_upload(src: Path, *, base_url: str, token: str, doc_id: str,
                  model_version: str, lang: str, is_ocr: bool,
                  enable_formula: bool, enable_table: bool) -> str:
    """申请预签名 URL 并裸 PUT 上传，返回 batch_id。data_id 用 doc_id 便于结果条目对账。"""
    body = {
        "model_version": model_version,        # pipeline=电子版快 / vlm=扫描件准（与 detect_pages 路由对齐）
        "language": lang,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "files": [{"name": src.name, "is_ocr": bool(is_ocr), "data_id": doc_id}],
    }
    resp = httpx.post(f"{base_url}/file-urls/batch", json=body,
                      headers=_api_headers(token), timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(
            f"开放平台申请上传链接失败 code={payload.get('code')} msg={payload.get('msg')}"
            "（code=-60018 通常为每日页额度耗尽）")
    data = payload.get("data") or {}
    urls = data.get("file_urls") or []
    if not urls:
        raise RuntimeError("开放平台未返回上传链接（file_urls 空）")

    # 预签名 URL 必须严格裸 PUT：多一个头（哪怕 Content-Type）都是 403
    put = httpx.put(urls[0], content=src.read_bytes(), timeout=600)
    if put.is_error:
        raise RuntimeError(f"上传文件到预签名 URL 失败 status={put.status_code}")
    return data.get("batch_id") or ""


# ---------------------------------------------------------------- 步骤③：轮询结果
def _poll_result(src_name: str, doc_id: str, *, base_url: str, token: str, batch_id: str,
                 poll_interval: float, poll_timeout: float) -> dict:
    """轮询批量结果直至 done，返回命中条目（含 full_zip_url）。failed / 超时抛 RuntimeError。"""
    url = f"{base_url}/extract-results/batch/{batch_id}"
    deadline = time.monotonic() + poll_timeout
    last_state = None
    while True:
        resp = httpx.get(url, headers=_api_headers(token), timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"开放平台查询结果失败 code={payload.get('code')} msg={payload.get('msg')}")
        entries = (payload.get("data") or {}).get("extract_result") or []
        # data_id 优先（我们提交时就是 doc_id）；缺失再按文件名对账
        hit = next((e for e in entries if e.get("data_id") == doc_id), None) \
            or next((e for e in entries if e.get("file_name") == src_name), None)
        if hit is None:
            if entries:
                raise RuntimeError(
                    f"批量结果缺本文件条目：batch={batch_id} 有 {[e.get('file_name') for e in entries]}")
            # 空条目 = 上传还没被扫描提交，等下一轮
        else:
            state = hit.get("state", "")
            if state == "done":
                if not hit.get("full_zip_url"):
                    raise RuntimeError("开放平台任务 done 但未返回 full_zip_url")
                return hit
            if state == "failed":
                raise RuntimeError(f"开放平台解析失败：{hit.get('err_msg') or '未知错误'}")
            if state != last_state:  # 只在状态变化时打日志，长轮询不刷屏
                prog = hit.get("extract_progress") or {}
                print(f"[MinerU-开放平台] state={state} "
                      f"{prog.get('extracted_pages', '?')}/{prog.get('total_pages', '?')} 页")
                last_state = state
        if time.monotonic() >= deadline:
            raise RuntimeError(f"开放平台解析超时（{poll_timeout:g}s）：batch={batch_id} 仍在进行中")
        time.sleep(poll_interval)


# ---------------------------------------------------------------- 结果落地
def _download_extract(zip_url: str, out_dir: Path) -> None:
    """流式下载结果 zip 并安全解压（防 zip-slip）；解压后删 zip，full.md 与 images/ 保持同级。"""
    zip_path = out_dir / "result.zip"
    with httpx.stream("GET", zip_url, timeout=600) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename)
            # 防路径逃逸：正规产物不会长成绝对路径 / 带父级跳转，长了也不放出去
            if info.filename.startswith("/") or ".." in name.parts or info.filename.startswith("\\"):
                continue
            zf.extract(info, out_dir)
    zip_path.unlink()


def _structures_from_content_list(out_dir: Path) -> tuple[list[Structure], int]:
    """从 *_content_list.json 尽力提取结构清单（image/table）与页数。失败不影响主流程。"""
    structures: list[Structure] = []
    pages = 0
    try:
        cl_paths = list(out_dir.rglob("*_content_list.json"))
        if not cl_paths:
            return structures, pages
        items = json.loads(cl_paths[0].read_text(encoding="utf-8"))
        if not isinstance(items, list):
            return structures, pages
        for item in items:
            page_idx = item.get("page_idx", 0)
            pages = max(pages, int(page_idx) + 1)
            if item.get("type") == "image" and item.get("img_path"):
                structures.append(Structure(kind="image", location=f"page:{page_idx}",
                                            pointer=item["img_path"]))
            elif item.get("type") == "table":
                structures.append(Structure(kind="table", location=f"page:{page_idx}",
                                            text=item.get("table_body") or None))
    except (OSError, ValueError, KeyError, TypeError):
        pass  # 结构清单是增益不是依赖：坏 JSON / 缺字段都只损失增强信息
    return structures, pages


# ---------------------------------------------------------------- 主入口
def parse_via_openapi(
    src: Path, *,
    doc_id: str,
    base_url: str,
    token: str | None,
    model_version: str = "pipeline",
    lang: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    poll_interval: float = 5.0,
    poll_timeout: float = 3600.0,
    out_dir: Path,
) -> tuple[str, dict[str, str], list[Structure], dict]:
    """本地 PDF → 开放平台云端解析 → (markdown, assets, structures, stats)。

    三步流见模块 docstring；产物落 out_dir（full.md + images/），md 内相对图片引用天然可达。
    """
    if not token:
        raise RuntimeError(
            "MINERU_OPEN_TOKEN 未配置：登录 mineru.net → API 管理 → 创建 API Token，填入 ownrag/.env")
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    batch_id = _apply_upload(src, base_url=base_url, token=token, doc_id=doc_id,
                             model_version=model_version, lang=lang, is_ocr=is_ocr,
                             enable_formula=enable_formula, enable_table=enable_table)
    hit = _poll_result(src.name, doc_id, base_url=base_url, token=token, batch_id=batch_id,
                       poll_interval=poll_interval, poll_timeout=poll_timeout)
    _download_extract(hit["full_zip_url"], out_dir)

    md_path = out_dir / "full.md"
    md = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    images_dir = out_dir / "images"
    assets = {p.stem: str(p) for p in sorted(images_dir.glob("*"))
              if p.is_file() and p.suffix.lower() in _IMAGE_EXTS} if images_dir.is_dir() else {}
    structures, pages = _structures_from_content_list(out_dir)
    stats = {"pages": pages, "mode": "open", "model_version": model_version, "batch_id": batch_id}
    return md, assets, structures, stats


# ---------------------------------------------------------------- 冒烟入口
if __name__ == "__main__":
    import argparse
    import os
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台坑：中文输出必须显式 UTF-8
    try:
        from dotenv import load_dotenv
        load_dotenv()  # 冒烟场景从 cwd 的 .env 取 token，与主应用同一来源
    except ImportError:
        pass

    ap = argparse.ArgumentParser(description="MinerU 开放平台单文件解析冒烟（消耗每日页额度）")
    ap.add_argument("input", help="PDF 文件路径")
    ap.add_argument("-o", "--out", default="./mineru_open_out", help="输出目录（默认 ./mineru_open_out）")
    ap.add_argument("-b", "--model-version", default="pipeline", choices=["pipeline", "vlm"],
                    help="pipeline=电子版快 / vlm=扫描件准")
    ap.add_argument("--ocr", action="store_true", help="强制开 OCR（仅对 pipeline/vlm 有效）")
    ap.add_argument("--poll-interval", type=float, default=5.0)
    ap.add_argument("--poll-timeout", type=float, default=3600.0)
    args = ap.parse_args()

    src = Path(args.input)
    if not src.is_file():
        sys.exit(f"输入不存在：{src}")
    md, assets, structures, stats = parse_via_openapi(
        src, doc_id=src.stem,
        base_url=os.environ.get("MINERU_OPEN_BASE_URL") or API_BASE_DEFAULT,
        token=os.environ.get("MINERU_OPEN_TOKEN"),
        model_version=args.model_version, is_ocr=args.ocr,
        poll_interval=args.poll_interval, poll_timeout=args.poll_timeout,
        out_dir=Path(args.out),
    )
    print(f"[MinerU-开放平台] 完成：{Path(args.out) / 'full.md'}")
    print(f"[MinerU-开放平台] stats={stats} images={len(assets)} structures={len(structures)}")
