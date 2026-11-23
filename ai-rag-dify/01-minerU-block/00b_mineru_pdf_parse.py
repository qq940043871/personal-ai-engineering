# -*- coding: utf-8 -*-
"""第 0 步（增强版，单文件）：PDF / 扫描件 → 结构化 Markdown（MinerU 三通路 + 降级 + 结构归一化）。

为什么再写一个：
    00_pdf_to_md_mineru.py 只覆盖「本地 CLI」和「本地 HTTP 服务」两条通路。
    参考 ai-rag-self-engineering/ownrag/ownrag/ingest/pdf_mineru.py 后补齐三件事：
      1. 三通路同接口：cli / http（自建服务）/ open（mineru.net 开放平台，零 GPU 吃每日页额度）
      2. 页级路由：抽样判「电子版 / 扫描件」，自动选 pipeline（快）或 vlm（准）
      3. 失败兜底 + 产物统计：MinerU 全挂时用 pymupdf 抽纯文本（带页锚点，标 degraded），
         并从 content_list.json 汇总页覆盖 / 表格 / 公式 / 图片数，直接喂给 09_quality_gate.py

链路位置：
    PDF ──00(本脚本)──> md(_norm.md) ──02_add_split_to_periods.py──> md(已插 @@)
        ──01_main_append_title.py──> 切片 md(含 @!@) ──> 灌 Dify 知识库

用法：
    # 最省事：自动选通路（有本地 mineru 走 CLI，否则有 token 走云端，否则 --base-url 走 HTTP）
    python 00b_mineru_pdf_parse.py 结算细则.pdf -o ./mineru_out

    # 指定通路
    python 00b_mineru_pdf_parse.py x.pdf --mode cli  -b vlm          # 扫描件/复杂版式（吃显存）
    python 00b_mineru_pdf_parse.py x.pdf --mode http --base-url http://127.0.0.1:8888
    python 00b_mineru_pdf_parse.py x.pdf --mode open                 # 需环境变量 MINERU_OPEN_TOKEN
    python 00b_mineru_pdf_parse.py ./pdfs -o ./mineru_out            # 目录批量

    # 大书分批（仅 CLI 生效）、只保留原样输出、关闭兜底
    python 00b_mineru_pdf_parse.py 大书.pdf -s 0 -e 199
    python 00b_mineru_pdf_parse.py x.pdf --no-normalize
    python 00b_mineru_pdf_parse.py x.pdf --fallback none

接口契约（与 ai-rag-self-engineering/ownrag/ownrag/ingest/ 对齐）：
    CLI  : mineru -p <pdf> -o <out_dir> [-b <backend>] [-l ch] [-s N] [-e M]
           → 在 out_dir 下 rglob("*.md") 取新产出的第一个；同目录 *.json 即 content_list
    HTTP : POST {base}/file_parse  multipart file + backend/lang
           → {"markdown": str, "pages": int, "assets": dict}
    OPEN : mineru.net /api/v4 三步流
           ① POST /file-urls/batch            → batch_id + 预签名 PUT url
           ② PUT 文件字节（裸传，不加任何头）  → 上传后平台自动提交解析
           ③ GET /extract-results/batch/{id}  → 轮询至 done，取 full_zip_url 下载解压
           产物：full.md + images/（md 内相对路径引用，须保持同级）

产物（保持与 00_ 一致，便于 09_quality_gate.py 直接对接）：
    <out>/<pdf名>/<MinerU 原始 md>
    <out>/<pdf名>/<pdf名>_norm.md           ← 归一化结果，喂给 02_add_split_to_periods.py
    <out>/<pdf名>/<pdf名>_parse_report.json ← 本次解析的元数据与产物统计

依赖：标准库 + requests（http / open 模式）；可选 pymupdf（页级路由与兜底）、
      MinerU 本体（pip install -U "mineru[core]"，仅 cli 模式）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

DEFAULT_OPEN_BASE = "https://mineru.net/api/v4"
_OPEN_IN_PROGRESS = {"waiting-file", "pending", "running", "converting"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_FENCE = re.compile(r"^\s*(```|~~~)")
_H2_RE = re.compile(r"^(\d+)[.、)]\s+\S")
_H3_RE = re.compile(r"^(\d+\.\d+)[.、)]?\s+\S")

# MinerU 2.5+ 把 backend 名改成 vlm-auto-engine / hybrid-auto-engine，老简写 vlm 已不识别
_CLI_BACKEND_ALIAS = {"vlm": "vlm-auto-engine", "auto": None, "pipeline": "pipeline"}
# 开放平台只认 model_version: pipeline | vlm
_OPEN_BACKEND_ALIAS = {"vlm": "vlm", "vlm-auto-engine": "vlm", "auto": "pipeline",
                       "pipeline": "pipeline", "hybrid-auto-engine": "vlm"}


# --------------------------------------------------------------------- 页级探测与路由
def probe_pdf(pdf: Path, sample_pages: int = 3) -> dict:
    """抽样判版式：文本层字符太少 → 扫描件倾向 vlm；有文本层 → pipeline。

    无 pymupdf 时不拦路（probe="none"，路由回落 pipeline，由 MinerU 自身能力决定）。
    """
    info = {"probe": "none", "pages": 0, "sampled": 0, "text_chars": 0,
            "chars_per_page": 0.0, "has_toc": False, "route": "pipeline"}
    try:
        import fitz  # pymupdf（可选依赖）
    except ImportError:
        return info
    try:
        with fitz.open(str(pdf)) as doc:
            info["pages"] = doc.page_count
            info["has_toc"] = bool(doc.get_toc())
            n = max(1, min(sample_pages, doc.page_count))
            info["sampled"] = n
            info["text_chars"] = sum(len(doc[i].get_text("text").strip()) for i in range(n))
            info["chars_per_page"] = round(info["text_chars"] / n, 1)
            info["route"] = "pipeline" if info["chars_per_page"] >= 50 else "vlm"
            info["probe"] = "pymupdf"
    except Exception as e:  # 加密/损坏 PDF：探测失败但别阻断主流程
        info["probe"] = f"pymupdf-error: {e}"
    return info


def resolve_mode(args) -> str:
    """auto 通路优先级：本地 CLI（不限页数）→ --base-url 自建服务 → 云端开放平台。"""
    if args.mode != "auto":
        return args.mode
    if shutil.which(args.mineru):
        return "cli"
    if args.base_url:
        return "http"
    if os.environ.get("MINERU_OPEN_TOKEN"):
        return "open"
    raise RuntimeError(
        "auto 找不到可用通路：请 ① pip install -U \"mineru[core]\" 装本地 CLI；"
        "② 或 --base-url 指向已部署的 MinerU 服务；"
        "③ 或设置环境变量 MINERU_OPEN_TOKEN 走 mineru.net 云端解析。"
    )


def resolve_backend(name: str, mode: str, probe: dict) -> str | None:
    """把用户意图（auto/pipeline/vlm/原生名）翻译成目标通路认识的 backend。"""
    raw = name
    if raw in (None, "", "auto"):
        raw = probe.get("route", "pipeline")
    if mode == "open":
        return _OPEN_BACKEND_ALIAS.get(raw, raw)
    if mode == "cli":
        return _CLI_BACKEND_ALIAS.get(raw, raw)
    return None if raw == "auto" else raw


# --------------------------------------------------------------------- 通路 1：本地 CLI
def _via_cli(pdf: Path, out_dir: Path, args, backend: str | None) -> tuple[Path, str]:
    if not shutil.which(args.mineru):
        raise RuntimeError(
            f"MinerU CLI 不可用：{args.mineru} 未找到。安装：pip install -U \"mineru[core]\"；"
            "或改用 --mode http / --mode open。")
    cmd = [args.mineru, "-p", str(pdf), "-o", str(out_dir)]
    if backend:
        cmd += ["-b", backend]
    if args.lang:
        cmd += ["-l", args.lang]
    if args.start is not None:
        cmd += ["-s", str(args.start)]
    if args.end is not None:
        cmd += ["-e", str(args.end)]

    before = {p.resolve() for p in out_dir.rglob("*.md")}
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=args.timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"MinerU CLI 失败（rc={proc.returncode}）：{(proc.stderr or '')[-500:]}")
    # 优先用本次新增的 md，避免同目录里上一轮的旧产物被误取
    new = sorted({p.resolve() for p in out_dir.rglob("*.md")} - before)
    mds = new or sorted(out_dir.rglob("*.md"))
    if not mds:
        raise RuntimeError(f"MinerU CLI 未产出 Markdown：{out_dir}")
    picked = next((m for m in mds if not m.stem.endswith("_norm")), mds[0])
    return picked, f"cli({time.monotonic() - t0:.0f}s)"


# --------------------------------------------------------------------- 通路 2：本地 HTTP 服务
def _via_http(pdf: Path, out_dir: Path, args, backend: str | None) -> tuple[Path, str]:
    if not args.base_url:
        raise RuntimeError("--mode http 需要同时给 --base-url，如 http://127.0.0.1:8888")
    import requests

    url = f"{args.base_url.rstrip('/')}/file_parse"
    sess = requests.Session()
    sess.trust_env = False  # 本地服务：不穿系统代理
    with open(pdf, "rb") as f:
        resp = sess.post(url,
                         files={"file": (pdf.name, f)},
                         data={"backend": backend or "auto", "lang": args.lang or "ch"},
                         timeout=600)
    resp.raise_for_status()
    payload = resp.json()
    md_text = payload.get("markdown", "")
    if not md_text.strip():
        raise RuntimeError(f"MinerU 服务返回空 Markdown：{url}")
    assets = payload.get("assets") or {}
    if isinstance(assets, dict) and assets:
        (out_dir / "assets_index.json").write_text(
            json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_dir / f"{pdf.stem}.md"
    md_path.write_text(md_text, encoding="utf-8")
    return md_path, f"http(pages={payload.get('pages', 0)})"


# --------------------------------------------------------------------- 通路 3：mineru.net 开放平台
def _open_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _open_apply_upload(pdf: Path, args, backend: str, token: str) -> str:
    """申请预签名 URL 并裸 PUT 上传，返回 batch_id。"""
    import requests

    base = (args.open_base_url or DEFAULT_OPEN_BASE).rstrip("/")
    is_ocr = args.ocr if args.ocr is not None else backend == "pipeline"
    body = {
        "model_version": backend or "pipeline",   # pipeline=电子版快 / vlm=扫描件准
        "language": args.lang or "ch",
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table,
        "files": [{"name": pdf.name, "is_ocr": bool(is_ocr), "data_id": pdf.stem}],
    }
    resp = requests.post(f"{base}/file-urls/batch", json=body,
                         headers=_open_headers(token), timeout=120)
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
    # 预签名 URL 必须严格裸 PUT：多带任何头（含 Content-Type）都会让 OSS 签名失效返回 403
    put = requests.put(urls[0], data=pdf.read_bytes(), timeout=600)
    if put.status_code >= 400:
        raise RuntimeError(f"上传文件到预签名 URL 失败 status={put.status_code}")
    return data.get("batch_id") or ""


def _open_poll(pdf: Path, args, token: str, batch_id: str) -> dict:
    """轮询批量结果直至 done，返回命中条目（含 full_zip_url）。"""
    import requests

    base = (args.open_base_url or DEFAULT_OPEN_BASE).rstrip("/")
    url = f"{base}/extract-results/batch/{batch_id}"
    deadline = time.monotonic() + args.poll_timeout
    last_state = None
    while True:
        resp = requests.get(url, headers=_open_headers(token), timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"开放平台查询结果失败 code={payload.get('code')} msg={payload.get('msg')}")
        entries = (payload.get("data") or {}).get("extract_result") or []
        hit = (next((e for e in entries if e.get("data_id") == pdf.stem), None)
               or next((e for e in entries if e.get("file_name") == pdf.name), None))
        if hit is not None:
            state = hit.get("state", "")
            if state == "done":
                if not hit.get("full_zip_url"):
                    raise RuntimeError("开放平台任务 done 但未返回 full_zip_url")
                return hit
            if state == "failed":
                raise RuntimeError(f"开放平台解析失败：{hit.get('err_msg') or '未知错误'}")
            if state != last_state:  # 只在状态变化时打印，长轮询不刷屏
                prog = hit.get("extract_progress") or {}
                print(f"[MinerU-云端] state={state} "
                      f"{prog.get('extracted_pages', '?')}/{prog.get('total_pages', '?')} 页")
                last_state = state
        elif entries:
            raise RuntimeError(
                f"批量结果缺本文件条目：batch={batch_id} 有 {[e.get('file_name') for e in entries]}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"开放平台解析超时（{args.poll_timeout:g}s）：batch={batch_id}")
        time.sleep(args.poll_interval)


def _open_download(zip_url: str, out_dir: Path) -> None:
    """流式下载结果 zip 并安全解压（防 zip-slip），解压后删 zip。"""
    import requests

    zip_path = out_dir / "result.zip"
    with requests.get(zip_url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename.replace("\\", "/"))
            if info.filename.startswith(("/", "\\")) or ".." in name.parts:
                continue  # 正规产物不会长成绝对路径/父级跳转，长了也不放出去
            zf.extract(info, out_dir)
    zip_path.unlink(missing_ok=True)


def _via_open(pdf: Path, out_dir: Path, args, backend: str | None) -> tuple[Path, str]:
    token = os.environ.get("MINERU_OPEN_TOKEN")
    if not token:
        raise RuntimeError(
            "MINERU_OPEN_TOKEN 未配置：登录 mineru.net → API 管理 → 创建 Token 后写入环境变量。")
    if backend is None:
        backend = "pipeline"
    batch_id = _open_apply_upload(pdf, args, backend, token)
    print(f"[MinerU-云端] batch={batch_id}，开始轮询…")
    hit = _open_poll(pdf, args, token, batch_id)
    _open_download(hit["full_zip_url"], out_dir)
    md_path = out_dir / "full.md"
    if not md_path.is_file():
        mds = sorted(p for p in out_dir.rglob("*.md") if not p.stem.endswith("_norm"))
        if not mds:
            raise RuntimeError(f"开放平台结果解压后没有 Markdown：{out_dir}")
        md_path = mds[0]
    return md_path, f"open(model_version={backend}, batch={batch_id})"


# --------------------------------------------------------------------- 降级：pymupdf 纯文本
def _via_pymupdf(pdf: Path, out_dir: Path) -> Path:
    """MinerU 全挂时的兜底：结构丢了内容也要在，逐页带 page 锚点，降级质量可见。"""
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError("pymupdf 未安装（pip install pymupdf），无可用降级通路") from e
    pages: list[str] = []
    with fitz.open(str(pdf)) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            pages.append(f"<!--page:{i}-->\n{text}" if text else f"<!--page:{i}-->（本页无可提取文本）")
    md_text = "\n\n".join(pages)
    if not md_text.strip():
        raise RuntimeError("pymupdf 也未抽出任何文本")
    md_path = out_dir / f"{pdf.stem}_pymupdf_fallback.md"
    md_path.write_text(md_text, encoding="utf-8")
    return md_path


# --------------------------------------------------------------------- 结构归一化
def _drop_repeated_headers(lines, repeat: int):
    """删掉重复出现的短行（页眉/页脚/页码），跳过代码块与标题行。"""
    counter = Counter()
    in_fence = False
    for line in lines:
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            continue
        if in_fence or not t or t.startswith("#") or t.startswith("|"):
            continue
        if len(t) <= 60:
            counter[t] += 1
    drop = {s for s, n in counter.items() if n >= repeat}
    if not drop:
        return lines

    out, in_fence = [], False
    for line in lines:
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and t in drop:
            continue
        out.append(line)
    return out


def _scan_levels(lines):
    """统计标题层级与行首编号，跳过代码块（避免把代码里的 ### 当成真标题）。"""
    h1 = h2 = h3 = num = 0
    in_fence = False
    for line in lines:
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if t.startswith("# "):
            h1 += 1
        elif t.startswith("## "):
            h2 += 1
        elif t.startswith("### "):
            h3 += 1
        elif re.match(r"^(\d+\.)+\d+", t):
            num += 1
    return h1, h2, h3, num


def normalize(md_text: str, title: str | None = None, dedup_repeat: int = 5) -> str:
    """只做结构保底：保证 1 个 H1、尽量有 H2/H3，不动行首编号正文（留给 02_ 插 @@）。"""
    lines = md_text.replace("\u3000", " ").splitlines()
    if dedup_repeat and dedup_repeat > 1:
        lines = _drop_repeated_headers(lines, dedup_repeat)

    h1_cnt, h2_cnt, h3_cnt, _ = _scan_levels(lines)
    has_h1, has_h2, has_h3 = h1_cnt > 0, h2_cnt > 0, h3_cnt > 0

    out, in_fence, h1_seen = [], False, False
    for line in lines:
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        # 1) 多个 H1：保留第一个，其余降级 H2（MinerU 常把每章都识别成 H1）
        if t.startswith("# "):
            if h1_seen:
                out.append("## " + t[2:].strip())
            else:
                h1_seen = True
                out.append(line)
            continue
        # 2) 缺 H2：顶层编号行（"1. 总则"）提升为 H2
        if not has_h2 and _H2_RE.match(t) and not t.startswith("|"):
            out.append("## " + t)
            continue
        # 3) 缺 H3：二级编号行（"1.1. 制定目的"）提升为 H3
        if not has_h3 and _H3_RE.match(t) and not t.startswith("|"):
            out.append("### " + t)
            continue
        out.append(line)

    if not has_h1:
        # 全文无 H1：补一行，否则 01_ 直接抛「未找到一级标题」
        out.insert(0, f"# {title or '未命名文档'}")
        out.insert(1, "")

    return "\n".join(out).strip() + "\n"


def _stats(text: str) -> dict:
    h1, h2, h3, num = _scan_levels(text.splitlines())
    return {"H1": h1, "H2": h2, "H3": h3, "行首编号": num}


# --------------------------------------------------------------------- 产物统计（content_list）
def _collect_facts(out_dir: Path) -> dict:
    """汇总 MinerU 的 content_list.json：页覆盖 / 表格 / 公式 / 图片数。坏 JSON 只损失统计。"""
    facts = {"content_list": None, "pages_covered": 0, "tables": 0,
             "equations": 0, "images": 0, "assets": 0}
    cands = sorted(p for p in out_dir.rglob("*content_list*.json") if p.is_file())
    if cands:
        facts["content_list"] = str(cands[0])
        try:
            items = json.loads(cands[0].read_text(encoding="utf-8"))
            if isinstance(items, list):
                page_idx = set()
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    idx = it.get("page_idx")
                    if isinstance(idx, int):
                        page_idx.add(idx)
                    kind = it.get("type")
                    if kind == "table":
                        facts["tables"] += 1
                    elif kind in ("equation", "interline_equation"):
                        facts["equations"] += 1
                    elif kind == "image":
                        facts["images"] += 1
                facts["pages_covered"] = len(page_idx)
        except (OSError, ValueError, TypeError):
            pass
    facts["assets"] = sum(1 for p in out_dir.rglob("*")
                          if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)
    return facts


# --------------------------------------------------------------------- 单文件主流程
def process_one(pdf: Path, args) -> dict:
    t0 = time.monotonic()
    out_dir = Path(args.out) / pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    probe = probe_pdf(pdf, args.sample_pages)
    print(f"[MinerU] {pdf.name} → {out_dir}")

    report = {"source": str(pdf), "mode": None, "backend": None, "probe": probe,
              "status": "ok", "degraded": False}
    try:
        mode = resolve_mode(args)
        backend = resolve_backend(args.backend, mode, probe)
        report.update(mode=mode, backend=backend)
        if probe["pages"] > 200 and mode == "open":
            print(f"[警告] {pdf.name} 有 {probe['pages']} 页，开放平台单文件上限 200 页，可能被拒。"
                  "建议 --mode cli 或先用 -s/-e 分批。")
        print(f"[MinerU] 通路={mode} backend={backend or '默认'} 探测={probe['probe']} "
              f"页数={probe['pages'] or '?'} 每页字数={probe['chars_per_page']}")
        if mode == "cli":
            raw_md, note = _via_cli(pdf, out_dir, args, backend)
        elif mode == "http":
            raw_md, note = _via_http(pdf, out_dir, args, backend)
        elif mode == "open":
            raw_md, note = _via_open(pdf, out_dir, args, backend)
        else:
            raise RuntimeError(f"未知通路：{mode}")
        report["note"] = note
    except Exception as e:
        if args.fallback != "pymupdf":
            raise
        # 通关失败（无 CLI/无服务/无 token/解析报错）统一走兜底，绝不静默丢文档
        print(f"[降级] MinerU 失败（{e}），改用 pymupdf 纯文本兜底")
        try:
            raw_md = _via_pymupdf(pdf, out_dir)
        except Exception as e2:
            raise RuntimeError(f"MinerU 失败（{e}）；兜底也失败（{e2}）") from e2
        report.update(status="degraded", degraded=True,
                      error=str(e), note="pymupdf 纯文本兜底，结构信息缺失")

    raw = raw_md.read_text(encoding="utf-8")
    if not raw.strip():
        raise RuntimeError(f"MinerU 产出空 Markdown：{raw_md}")
    before = _stats(raw)

    if args.no_normalize:
        final_path, after = raw_md, before
    else:
        fixed = normalize(raw, args.title or pdf.stem, args.dedup_repeat)
        final_path = out_dir / f"{pdf.stem}_norm.md"
        final_path.write_text(fixed, encoding="utf-8")
        after = _stats(fixed)

    facts = _collect_facts(out_dir)
    report.update(raw_md=str(raw_md), output_md=str(final_path),
                  stats_before=before, stats_after=after, facts=facts,
                  elapsed_sec=round(time.monotonic() - t0, 1))

    if not args.no_report:
        (out_dir / f"{pdf.stem}_parse_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[MinerU] 原始 md : {raw_md}")
    print(f"[MinerU] 归一化后: {final_path}")
    print(f"[MinerU] 结构统计: 原始 {before} → 输出 {after}")
    print(f"[MinerU] 产物统计: 页覆盖 {facts['pages_covered'] or '?'}/{probe['pages'] or '?'}，"
          f"表格 {facts['tables']}，公式 {facts['equations']}，图片 {facts['images']}")
    if after["H2"] == 0:
        print("[警告] 没有二级标题：01_main_append_title.py 会产出空文件，请人工补 ## 或检查解析结果。")
    if after["行首编号"] == 0:
        print("[提示] 未发现行首编号（如 3.2.1）：02_add_split_to_periods.py 将插不到 @@ 子分段标记。")
    if report["degraded"]:
        print("[警告] 本次为降级产物（无标题层级），只适合做兜底检索，不要直接进 01_/02_ 流水线。")
    return report


def collect_pdfs(target: Path, recursive: bool = False) -> list[Path]:
    if target.is_dir():
        return sorted(target.rglob("*.pdf") if recursive else target.glob("*.pdf"))
    return [target]


# --------------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="第 0 步：MinerU 把 PDF 解析为结构化 Markdown（cli / http / open 三通路 + 降级 + 归一化）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="PDF 文件或含 PDF 的目录")
    ap.add_argument("-o", "--out", default="./mineru_out", help="输出根目录（默认 ./mineru_out）")
    ap.add_argument("--mode", default="auto", choices=["auto", "cli", "http", "open"],
                    help="auto=有本地 CLI 走 cli，否则 --base-url 走 http，否则 token 走 open（默认 auto）")
    ap.add_argument("-b", "--backend", default="auto",
                    help="auto=按页级探测选（默认）/ pipeline=电子版快 / vlm=扫描件准；"
                         "也可直传原生名（如 hybrid-auto-engine，仅 cli 生效）")
    ap.add_argument("-l", "--lang", default="ch", help="文档语言（默认 ch）")
    ap.add_argument("--mineru", default="mineru", help="MinerU 可执行名或路径（默认 mineru）")
    ap.add_argument("--base-url", default=None,
                    help="--mode http 时的 MinerU 服务地址，如 http://127.0.0.1:8888")
    ap.add_argument("--open-base-url", default=None,
                    help=f"开放平台 API 基址（默认 {DEFAULT_OPEN_BASE}，可用 MINERU_OPEN_BASE_URL 覆盖）")
    ap.add_argument("--ocr", dest="ocr", action="store_true", default=None,
                    help="开放平台强制开 OCR（默认仅 pipeline 且判为扫描件时开）")
    ap.add_argument("--no-formula", action="store_true", help="开放平台关闭公式识别")
    ap.add_argument("--no-table", action="store_true", help="开放平台关闭表格识别")
    ap.add_argument("--poll-interval", type=float, default=5.0, help="开放平台轮询间隔秒（默认 5）")
    ap.add_argument("--poll-timeout", type=float, default=3600.0, help="开放平台轮询超时秒（默认 3600）")
    ap.add_argument("--timeout", type=int, default=21600,
                    help="MinerU CLI 超时秒（默认 21600=6 小时，纯 CPU 解析大书很慢）")
    ap.add_argument("-s", "--start", type=int, default=None,
                    help="只解析从第几页开始（0 起，含）；仅 cli 生效")
    ap.add_argument("-e", "--end", type=int, default=None,
                    help="只解析到第几页（含）；仅 cli 生效")
    ap.add_argument("--sample-pages", type=int, default=3, help="页级探测抽样页数（默认 3）")
    ap.add_argument("--fallback", default="pymupdf", choices=["pymupdf", "none"],
                    help="MinerU 失败时是否用 pymupdf 纯文本兜底（默认 pymupdf）")
    ap.add_argument("--title", default=None, help="全文无 H1 时补的一级标题（默认用文件名）")
    ap.add_argument("--dedup-repeat", type=int, default=5,
                    help="重复出现 >=N 次的短行按页眉/页脚删除，0 关闭（默认 5）")
    ap.add_argument("--no-normalize", action="store_true", help="跳过结构归一化，保留 MinerU 原样输出")
    ap.add_argument("--no-report", action="store_true", help="不写 <pdf名>_parse_report.json")
    ap.add_argument("-r", "--recursive", action="store_true", help="目录输入时递归子目录")
    return ap


def main():
    # Windows 控制台默认 GBK，中文日志/路径会直接抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

    args = build_parser().parse_args()
    args.open_base_url = args.open_base_url or os.environ.get("MINERU_OPEN_BASE_URL")

    target = Path(args.input)
    if not target.exists():
        sys.exit(f"输入不存在：{target}")
    pdfs = collect_pdfs(target, args.recursive)
    if not pdfs:
        sys.exit(f"目录下没有 PDF：{target}")

    ok, fail = [], []
    for pdf in pdfs:
        try:
            ok.append(process_one(pdf, args))
        except Exception as e:  # 单份失败不阻断批量
            fail.append((pdf.name, str(e)))
            print(f"[错误] {pdf.name}：{e}", file=sys.stderr)

    print(f"\n完成 {len(ok)} 份（其中降级 {sum(1 for r in ok if r['degraded'])} 份），失败 {len(fail)} 份。")
    if ok:
        print(f"下一步：python 02_add_split_to_periods.py \"{ok[0]['output_md']}\" 1_1_new_process.md")
        print("自查（可选）：python 09_quality_gate.py parse --pdf <原PDF> --md <上面的 _norm.md>")
    if fail:
        for name, why in fail:
            print(f"  - {name}: {why}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
