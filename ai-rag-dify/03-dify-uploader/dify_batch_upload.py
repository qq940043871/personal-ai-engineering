#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dify 知识库批量上传 CLI。

替代 Tkinter 版 dify_uploader.py，用于「一批文档一次性灌库」：
  * 支持文件 / 目录 / 通配符，递归扫描，多扩展名过滤
  * 默认走 create-by-file（multipart，保留 md 原文件），也支持 create-by-text
  * 支持 hierarchical_model（父/子分段）与 text_model（自定义/自动分段）
  * 自动探测正文里的 `@!@` / `@@` 预埋标记并切换父子分隔符
  * --skip-existing 按文档名跳过已存在的、--overwrite 先删后传
  * --dry-run 只列计划不动库；--wait 轮询索引状态直到 completed/failed
  * 结束后输出 JSON 报告（成功/跳过/失败 + document_id + 耗时）

用法示例
--------
# 1) 看看库里有啥
python dify_batch_upload.py list --dataset-id <id>

# 2) 预演：目录下还有哪些没传
python dify_batch_upload.py upload "D:/docs/*.md" --dataset-id <id> --dry-run --skip-existing

# 3) 真传（跳已存在 + 等索引完成 + 出报告）
python dify_batch_upload.py upload D:/docs --dataset-id <id> --recursive --skip-existing --wait

地址与密钥可用参数，也可用环境变量 DIFY_BASE_URL / DIFY_API_KEY / DIFY_DATASET_ID。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：pip install requests")


# 每个扩展名对应的 mime，Dify 侧按 mime/扩展名决定解析器
MIME_MAP = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".epub": "application/epub+zip",
}
DEFAULT_EXTS = ".md,.markdown,.txt,.pdf,.docx,.csv,.xlsx,.html,.htm,.pptx,.epub"

# 索引过程中的中间态，需要轮询等它变 completed / error
PENDING_STATUS = {"waiting", "parsing", "cleaning", "splitting", "indexing", "queuing"}


class DifyError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def norm_base_url(url: str) -> str:
    """把 http://host/v1 、http://host/v1/ 、http://host 统一成 http://host。"""
    base = (url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")].rstrip("/")
    return base


def guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MIME_MAP:
        return MIME_MAP[suffix]
    return "application/octet-stream"


def collect_files(targets: Iterable[str], exts: set, recursive: bool) -> List[Path]:
    """把用户给的路径/通配符展开成去重后的文件列表（保持稳定顺序）。"""
    found: List[Path] = []
    seen = set()
    for raw in targets:
        raw = raw.strip()
        if not raw:
            continue
        # 通配符（Windows 下 glob 也认 * ? []）
        if any(ch in raw for ch in "*?["):
            matches = sorted(Path().glob(raw)) if not os.path.isabs(raw) else sorted(Path(raw).parent.glob(Path(raw).name))
            candidates = [p for p in matches if p.is_file()]
        else:
            p = Path(raw)
            if p.is_dir():
                candidates = sorted(p.rglob("*") if recursive else p.glob("*"))
                candidates = [c for c in candidates if c.is_file()]
            elif p.is_file():
                candidates = [p]
            else:
                print(f"  [warn] 路径不存在，忽略: {raw}")
                candidates = []
        for c in candidates:
            if exts and c.suffix.lower() not in exts:
                continue
            key = str(c.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(c)
    return found


def read_text_safe(path: Path, limit: int = 200_000) -> str:
    """只为探测 @!@ / @@ 标记，不参与实际上传。"""
    if path.suffix.lower() not in {".md", ".markdown", ".txt", ".html", ".htm", ".csv"}:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class DifyClient:
    def __init__(self, base_url: str, api_key: str, dataset_id: str, timeout: int = 60, verbose: bool = True):
        if not base_url:
            raise DifyError("缺少访问地址（--base-url 或 DIFY_BASE_URL）")
        if not api_key:
            raise DifyError("缺少访问密钥（--api-key 或 DIFY_API_KEY）")
        if not dataset_id:
            raise DifyError("缺少知识库ID（--dataset-id 或 DIFY_DATASET_ID）")
        self.base = norm_base_url(base_url)
        self.dataset_id = dataset_id
        self.timeout = timeout
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    # -- 内部请求封装：网络抖动/5xx 重试 -------------------------------------
    def _request(self, method: str, path: str, retries: int = 3, **kwargs) -> requests.Response:
        url = f"{self.base}/v1{path}"
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == retries:
                    raise DifyError(f"{method} {path} 网络异常: {exc}") from exc
                time.sleep(1.5 * attempt)
                continue
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            return resp
        raise DifyError(f"{method} {path} 失败: {last_exc}")

    def _json(self, resp: requests.Response, what: str) -> Dict[str, Any]:
        if resp.status_code >= 400:
            raise DifyError(f"{what} 失败 HTTP {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError:
            raise DifyError(f"{what} 返回非 JSON: {resp.text[:300]}")

    # -- 只读接口 -----------------------------------------------------------
    def list_datasets(self) -> Dict[str, Any]:
        return self._json(self._request("GET", "/datasets", params={"page": 1, "limit": 100}), "列出知识库")

    def list_documents(self) -> List[Dict[str, Any]]:
        """分页拉全量文档。"""
        docs: List[Dict[str, Any]] = []
        page = 1
        while True:
            payload = self._json(
                self._request(
                    "GET",
                    f"/datasets/{self.dataset_id}/documents",
                    params={"page": page, "limit": 100},
                ),
                "列出文档",
            )
            batch = payload.get("data") or []
            docs.extend(batch)
            if not payload.get("has_more") or not batch:
                break
            page += 1
        return docs

    def get_document(self, document_id: str) -> Dict[str, Any]:
        return self._json(
            self._request("GET", f"/datasets/{self.dataset_id}/documents/{document_id}"), "查询文档"
        )

    # -- 写接口 -------------------------------------------------------------
    def create_by_file(self, path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
        with open(path, "rb") as fh:
            files = {"file": (path.name, fh, guess_mime(path))}
            data = {"data": json.dumps(payload, ensure_ascii=False)}
            resp = self._request(
                "POST",
                f"/datasets/{self.dataset_id}/document/create-by-file",
                files=files,
                data=data,
                timeout=max(self.timeout, 300),
            )
        return self._json(resp, "create-by-file")

    def create_by_text(self, name: str, text: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(payload)
        body.update({"name": name, "text": text})
        resp = self._request(
            "POST",
            f"/datasets/{self.dataset_id}/document/create-by-text",
            json=body,
            timeout=max(self.timeout, 300),
        )
        return self._json(resp, "create-by-text")

    def delete_document(self, document_id: str) -> None:
        resp = self._request("DELETE", f"/datasets/{self.dataset_id}/documents/{document_id}")
        if resp.status_code >= 400:
            raise DifyError(f"删除文档 {document_id} 失败 HTTP {resp.status_code}: {resp.text[:300]}")

    def wait_indexed(self, document_id: str, timeout: int = 900, interval: int = 3) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last: Dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_document(document_id)
            status = (last.get("indexing_status") or "").lower()
            if status == "completed":
                return last
            if status in {"error", "stopped"}:
                return last
            if last.get("error"):
                return last
            time.sleep(interval)
        return last


# --------------------------------------------------------------------------- #
# 切分规则
# --------------------------------------------------------------------------- #
def build_payload(args, content_probe: str) -> Dict[str, Any]:
    """按 doc_form 组装 create-by-file / create-by-text 的 data 部分。"""
    payload: Dict[str, Any] = {
        "indexing_technique": args.indexing_technique,
        "doc_form": args.doc_form,
        "doc_language": args.doc_language,
    }

    if args.indexing_technique == "economy":
        # 经济模式不吃 process_rule，交给 Dify 默认
        return payload

    parent_sep = args.separator
    child_sep = args.child_separator
    # 自动探测预埋标记：正文里有 @!@ 就用它当父分隔符，有 @@ 就当子分隔符
    if args.auto_marker and content_probe:
        if "@!@" in content_probe:
            parent_sep = "@!@"
        if "@@" in content_probe:
            child_sep = "@@"

    if args.doc_form == "hierarchical_model":
        payload["process_rule"] = {
            "mode": "hierarchical",
            "rules": {
                "pre_processing_rules": [
                    {"id": "remove_extra_spaces", "enabled": not args.keep_extra_spaces},
                    {"id": "remove_urls_emails", "enabled": args.remove_urls},
                ],
                "parent_mode": "paragraph",
                "segmentation": {
                    "separator": parent_sep,
                    "max_tokens": args.max_tokens,
                    "chunk_overlap": 0,
                },
                "subchunk_segmentation": {
                    "separator": child_sep,
                    "max_tokens": args.child_max_tokens,
                    "chunk_overlap": 0,
                },
            },
        }
    else:
        mode = "automatic" if args.rule_mode == "auto" else "custom"
        rules: Dict[str, Any] = {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": not args.keep_extra_spaces},
                {"id": "remove_urls_emails", "enabled": args.remove_urls},
            ]
        }
        if mode == "custom":
            rules["segmentation"] = {
                "separator": parent_sep,
                "max_tokens": args.max_tokens,
                "chunk_overlap": args.max_tokens // 10,
            }
        payload["process_rule"] = {"mode": mode, "rules": rules}
    return payload


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_list(args, client: DifyClient) -> int:
    datasets = client.list_datasets().get("data") or []
    if not datasets:
        print("该密钥下没有可访问的知识库")
        return 0
    print(f"知识库共 {len(datasets)} 个：")
    for ds in datasets:
        mark = " <== 当前" if ds.get("id") == client.dataset_id else ""
        print(
            f"  - {ds.get('name')}\n"
            f"    id={ds.get('id')}  文档数={ds.get('document_count')}  字数={ds.get('word_count')}\n"
            f"    doc_form={ds.get('doc_form')}  embedding={ds.get('embedding_model')}"
            f"  检索={((ds.get('retrieval_model_dict') or {}).get('search_method'))}{mark}"
        )
    docs = client.list_documents()
    print(f"\n当前知识库文档共 {len(docs)} 个：")
    for d in sorted(docs, key=lambda x: x.get("name") or ""):
        print(
            f"  - {d.get('name')}  [{d.get('indexing_status')}]"
            f"  tokens={d.get('tokens')}  id={d.get('id')}"
        )
    return 0


def cmd_upload(args, client: DifyClient) -> int:
    exts = {e if e.startswith(".") else "." + e for e in args.ext.lower().replace(" ", "").split(",") if e}
    files = collect_files(args.targets, exts, args.recursive)
    if not files:
        print("没有匹配到任何文件")
        return 2
    print(f"待处理文件 {len(files)} 个：")
    for f in files:
        print(f"  - {f}  ({f.stat().st_size} bytes)")

    existing = {}
    if args.skip_existing or args.overwrite:
        existing = {d.get("name"): d for d in client.list_documents()}
        print(f"知识库现有文档 {len(existing)} 个（用于去重判断）")

    started = datetime.now()
    results: List[Dict[str, Any]] = []

    def handle(path: Path) -> Dict[str, Any]:
        name = (args.name_prefix or "") + path.name
        rec: Dict[str, Any] = {"file": str(path), "name": name}
        try:
            if args.overwrite and name in existing:
                client.delete_document(existing[name]["id"])
                rec["deleted_old"] = True
            elif args.skip_existing and name in existing:
                rec["status"] = "skipped"
                rec["reason"] = "已存在同名文档"
                return rec

            probe = read_text_safe(path)
            payload = build_payload(args, probe)
            rec["payload"] = payload
            if args.dry_run:
                rec["status"] = "dry-run"
                return rec

            if args.mode == "text":
                resp = client.create_by_text(name, probe, payload)
            else:
                resp = client.create_by_file(path, payload)
            doc = resp.get("document") or {}
            doc_id = doc.get("id")
            rec["document_id"] = doc_id
            rec["status"] = "uploaded"
            if doc_id and args.wait:
                final = client.wait_indexed(doc_id, timeout=args.wait_timeout)
                rec["indexing_status"] = final.get("indexing_status")
                rec["tokens"] = final.get("tokens")
                rec["error"] = final.get("error")
                if (final.get("indexing_status") or "").lower() != "completed":
                    rec["status"] = "index_failed" if final.get("error") else "index_pending"
            return rec
        except Exception as exc:  # 单文件失败不中断整批
            rec["status"] = "failed"
            rec["error"] = str(exc)
            return rec

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(handle, f): f for f in files}
            for fut in as_completed(futures):
                rec = fut.result()
                results.append(rec)
                _print_rec(rec)
    else:
        for f in files:
            rec = handle(f)
            results.append(rec)
            _print_rec(rec)
            if args.interval and not args.dry_run:
                time.sleep(args.interval)

    if args.dry_run:
        print("\n[dry-run] 未改动知识库。去掉 --dry-run 即执行上传。")
        return 0

    # 报告
    summary = {
        "base_url": client.base,
        "dataset_id": client.dataset_id,
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "uploaded": sum(1 for r in results if r["status"] == "uploaded"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] in {"failed", "index_failed"}),
        "results": results,
    }
    if args.report:
        report_path = Path(args.report)
    else:
        report_path = Path(f"upload_report_{started.strftime('%Y%m%d_%H%M%S')}.json")
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n完成：成功 {summary['uploaded']} / 跳过 {summary['skipped']} / 失败 {summary['failed']}"
        f"  共 {summary['total']}"
    )
    print(f"报告：{report_path.resolve()}")
    return 0 if summary["failed"] == 0 else 1


def _print_rec(rec: Dict[str, Any]) -> None:
    status = rec.get("status")
    tail = ""
    if rec.get("document_id"):
        tail += f"  doc={rec['document_id']}"
    if rec.get("indexing_status"):
        tail += f"  index={rec['indexing_status']}"
    if rec.get("reason"):
        tail += f"  ({rec['reason']})"
    if rec.get("error"):
        tail += f"  error={rec['error']}"
    print(f"  [{status}] {rec.get('name')}{tail}")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=os.getenv("DIFY_BASE_URL", ""), help="如 http://192.168.2.186/v1")
    common.add_argument("--api-key", default=os.getenv("DIFY_API_KEY", ""), help="dataset-xxx")
    common.add_argument("--dataset-id", default=os.getenv("DIFY_DATASET_ID", ""))
    common.add_argument("--timeout", type=int, default=60)

    parser = argparse.ArgumentParser(
        description="Dify 知识库批量上传工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例: python dify_batch_upload.py upload D:/docs --recursive --skip-existing --wait",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", parents=[common], help="列出知识库 / 已有文档")
    p_list.set_defaults(func=cmd_list)

    p_up = sub.add_parser("upload", parents=[common], help="批量上传文件")
    p_up.add_argument("targets", nargs="+", help="文件 / 目录 / 通配符，可多个")
    p_up.add_argument("--recursive", action="store_true", help="目录递归")
    p_up.add_argument("--ext", default=DEFAULT_EXTS, help=f"扩展名过滤，默认 {DEFAULT_EXTS}")
    p_up.add_argument("--mode", choices=["file", "text"], default="file",
                      help="file=create-by-file（默认，保留原文件）；text=create-by-text（读成纯文本）")
    p_up.add_argument("--doc-form", default="hierarchical_model",
                      choices=["hierarchical_model", "text_model", "qa_model"],
                      help="默认 hierarchical_model（父/子分段）；text_model=普通分段")
    p_up.add_argument("--doc-language", default="Chinese Simplified")
    p_up.add_argument("--indexing-technique", default="high_quality", choices=["high_quality", "economy"])
    p_up.add_argument("--rule-mode", default="custom", choices=["custom", "auto"], help="text_model 下的分段方式")

    # hierarchical 父子分段
    p_up.add_argument("--separator", default="\n\n", help="父分段分隔符，默认空行")
    p_up.add_argument("--child-separator", default="\n", help="子分段分隔符，默认换行")
    p_up.add_argument("--max-tokens", type=int, default=1024, help="父分段 token 上限，默认 1024")
    p_up.add_argument("--child-max-tokens", type=int, default=512, help="子分段 token 上限，默认 512")
    p_up.add_argument("--auto-marker", action="store_true", default=True,
                      help="正文含 @!@ / @@ 时自动改用它们做父子分隔符（默认开）")
    p_up.add_argument("--no-auto-marker", dest="auto_marker", action="store_false")
    p_up.add_argument("--keep-extra-spaces", action="store_true", help="关闭「去除多余空格」预处理")
    p_up.add_argument("--remove-urls", action="store_true", help="开启「删除 URL 与邮箱」预处理")

    # 行为控制
    p_up.add_argument("--skip-existing", action="store_true", help="同名文档已存在则跳过")
    p_up.add_argument("--overwrite", action="store_true", help="同名文档先删后传")
    p_up.add_argument("--name-prefix", default="", help="给上传的文档名加前缀")
    p_up.add_argument("--workers", type=int, default=1, help="并发上传数，默认 1（串行，日志清晰）")
    p_up.add_argument("--interval", type=float, default=0.3, help="串行上传间隔秒，默认 0.3")
    p_up.add_argument("--wait", action="store_true", help="上传后轮询索引状态直到完成")
    p_up.add_argument("--wait-timeout", type=int, default=900, help="单文档索引等待上限秒，默认 900")
    p_up.add_argument("--dry-run", action="store_true", help="只打印计划，不写库")
    p_up.add_argument("--report", default="", help="JSON 报告输出路径")
    p_up.set_defaults(func=cmd_upload)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = DifyClient(args.base_url, args.api_key, args.dataset_id, timeout=args.timeout)
    except DifyError as exc:
        print(f"配置错误: {exc}")
        return 2
    print(f"目标：{client.base}/v1  dataset={client.dataset_id}\n")
    return args.func(args, client)


if __name__ == "__main__":
    sys.exit(main())
