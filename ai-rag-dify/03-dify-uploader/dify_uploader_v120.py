# -*- coding: utf-8 -*-
"""Dify 1.20.0 知识库上传工具（Tkinter GUI）

由 dify_uploader.py 复制改写而来，专门适配 Dify 1.20.0 的 API 契约。
实测（http://192.168.2.186/v1 实例）发现的破坏性变化与对应改法：

1. **embedding 字段不能硬编码**
   旧版 payload 里写死 `embedding_model / embedding_model_provider = langgenius/gpustack/gpustack`，
   1.20.0 会直接 400：`Provider langgenius/gpustack/gpustack does not exist.`
   → 新版默认不传这两项（跟随知识库自身的 embedding 配置），需要时才在「高级」里填。

2. **空文档必须索引完成才能推分段**
   旧版「创建」拿完 document_id 立刻 POST /segments，1.20.0 会 404
   `Document is not completed.`（空文档也要走完 waiting→indexing→completed，实测约 10~50s）。
   → 新版「创建」后自动轮询 indexing_status，到 completed 才放开「上传分段」按钮。

3. **segments 已支持数组批量提交**
   旧版一条一次请求，几百段就是几百次 RTT；新版按「每批条数」批量 POST。

4. **整篇上传才是 1.20 的推荐路径**
   1.20.0 的 create-by-file / create-by-text 服务端就会按 `@!@`(父) / `@@`(子) 切好父子分段，
   比「空文档 + 手工推分段」稳（后者父子结构靠客户端猜）。新版把「整篇上传」放在第一位。

5. **新增清空分段**（重灌前用）：删文档下全部父分段。

6. **日志改走队列 + after 轮询**：旧版在工作线程里直接操作 Tk 控件，跨线程不安全。

7. **知识库ID 改下拉选择**：点「刷新列表」用密钥拉 `GET /v1/datasets`，下拉框列出可见知识库，
   选中即回填 ID（仍保留手填输入框；dataset- 密钥可见范围由 Dify 侧控制）。

8. **支持整目录批量上传**：选文件夹后递归扫描受支持扩展名，逐个 `create-by-file`，
   可选「跳过库内同名」「上传后等索引完成」，最后汇总成功/跳过/失败。

依赖：requests（tkinter 为 Windows 自带）
用法：python dify_uploader_v120.py
"""
from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional

import requests

# 本机 1.20.0 实例，按需修改
DEFAULT_BASE_URL = "http://192.168.2.186/v1"
PLACEHOLDER_KEY = "dataset-REPLACE_WITH_YOUR_KEY"

MIME_MAP = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
}
PENDING_STATUS = {"waiting", "parsing", "cleaning", "splitting", "indexing", "queuing"}  # 仅备注，wait_indexed 只认终态

# 文件夹批量上传时认的扩展名（与 MIME_MAP 保持一致）
SUPPORTED_EXTS = (".md", ".markdown", ".txt", ".pdf", ".docx", ".doc", ".csv", ".xlsx", ".html", ".htm")


class DifyError(RuntimeError):
    pass


def norm_base_url(url: str) -> str:
    """http://host/v1 、http://host/v1/ 、http://host  →  http://host（内部统一再拼 /v1）。"""
    base = (url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")].rstrip("/")
    return base


class DifyClient:
    """只封装 1.20.0 用到的接口，统一超时、重试与错误文案。"""

    def __init__(self, base_url: str, api_key: str, dataset_id: str, timeout: int = 60):
        self.base = norm_base_url(base_url)
        self.dataset_id = dataset_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _request(self, method: str, path: str, retries: int = 3, **kwargs) -> requests.Response:
        url = f"{self.base}/v1{path}"
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                if attempt == retries:
                    raise DifyError(f"网络异常：{exc}")
                time.sleep(1.5 * attempt)
                continue
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            return resp
        raise DifyError("请求重试次数用尽")

    @staticmethod
    def _raise_for_error(resp: requests.Response, what: str) -> None:
        if resp.status_code < 400:
            return
        detail = resp.text[:500]
        try:  # 1.20.0 的错误体统一为 {"code":..,"message":..,"status":..}
            body = resp.json()
            detail = f"{body.get('code')} / {body.get('message')}"
        except ValueError:
            pass
        raise DifyError(f"{what} 失败 HTTP {resp.status_code}：{detail}")

    # ---------------- 读 ----------------
    def dataset_info(self) -> Dict[str, Any]:
        resp = self._request("GET", f"/datasets/{self.dataset_id}")
        self._raise_for_error(resp, "查询知识库")
        return resp.json()

    def list_datasets(self) -> List[Dict[str, Any]]:
        """当前密钥可见的知识库（dataset- 密钥的可见范围由 Dify 侧权限决定）。"""
        resp = self._request("GET", "/datasets", params={"page": 1, "limit": 100})
        self._raise_for_error(resp, "列出知识库")
        return resp.json().get("data") or []

    def list_documents(self) -> List[Dict[str, Any]]:
        """分页拉全量文档，用于批量上传时判断同名文档。"""
        docs: List[Dict[str, Any]] = []
        page = 1
        while True:
            resp = self._request(
                "GET", f"/datasets/{self.dataset_id}/documents",
                params={"page": page, "limit": 100},
            )
            self._raise_for_error(resp, "列出文档")
            body = resp.json()
            docs.extend(body.get("data") or [])
            if not body.get("has_more"):
                return docs
            page += 1

    def get_document(self, document_id: str) -> Dict[str, Any]:
        resp = self._request("GET", f"/datasets/{self.dataset_id}/documents/{document_id}")
        self._raise_for_error(resp, "查询文档")
        return resp.json()

    def list_segments(self, document_id: str, limit: int = 100) -> Dict[str, Any]:
        resp = self._request(
            "GET",
            f"/datasets/{self.dataset_id}/documents/{document_id}/segments",
            params={"page": 1, "limit": limit},
        )
        self._raise_for_error(resp, "查询分段")
        return resp.json()

    # ---------------- 写 ----------------
    def create_by_text(self, name: str, text: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(payload)
        body.update({"name": name, "text": text})
        resp = self._request(
            "POST", f"/datasets/{self.dataset_id}/document/create-by-text",
            json=body, timeout=max(self.timeout, 300),
        )
        self._raise_for_error(resp, "create-by-text")
        return resp.json()

    def create_by_file(self, path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
        mime = MIME_MAP.get(path.suffix.lower(), "application/octet-stream")
        with open(path, "rb") as fh:
            resp = self._request(
                "POST", f"/datasets/{self.dataset_id}/document/create-by-file",
                files={"file": (path.name, fh, mime)},
                data={"data": json.dumps(payload, ensure_ascii=False)},
                timeout=max(self.timeout, 600),
            )
        self._raise_for_error(resp, "create-by-file")
        return resp.json()

    def add_segments(self, document_id: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """1.20.0 支持一次提交多条；文档必须已 completed，否则 404 Document is not completed."""
        resp = self._request(
            "POST", f"/datasets/{self.dataset_id}/documents/{document_id}/segments",
            json={"segments": segments}, timeout=max(self.timeout, 300),
        )
        self._raise_for_error(resp, "上传分段")
        return resp.json()

    def delete_segment(self, document_id: str, segment_id: str) -> None:
        resp = self._request("DELETE", f"/datasets/{self.dataset_id}/documents/{document_id}/segments/{segment_id}")
        self._raise_for_error(resp, "删除分段")

    def delete_document(self, document_id: str) -> None:
        resp = self._request("DELETE", f"/datasets/{self.dataset_id}/documents/{document_id}")
        self._raise_for_error(resp, "删除文档")

    def wait_indexed(
        self,
        document_id: str,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cancel: Optional[threading.Event] = None,
        timeout: int = 900,
        interval: float = 2.0,
    ) -> Dict[str, Any]:
        """轮询到 completed / error / stopped，返回最后一次文档详情。"""
        deadline = time.time() + timeout
        last: Dict[str, Any] = {}
        prev = None
        while time.time() < deadline:
            if cancel is not None and cancel.is_set():
                return last or {"indexing_status": "cancelled"}
            last = self.get_document(document_id)
            status = (last.get("indexing_status") or "").lower()
            if status != prev:
                prev = status
                if on_status:
                    on_status(status, last)
            if status in {"completed", "error", "stopped"}:
                return last
            time.sleep(interval)
        return last


class DifyUploaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Dify 1.20.0 知识库上传工具")
        self.root.geometry("900x760")
        self.root.minsize(820, 680)

        self.font = ("Microsoft YaHei UI", 10)
        self.bold = ("Microsoft YaHei UI", 10, "bold")

        # ---- 状态 ----
        self.api_base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        self.api_key = tk.StringVar(value=PLACEHOLDER_KEY)
        self.dataset_id = tk.StringVar()
        self.kb_choice = tk.StringVar()            # 知识库下拉框显示文本
        self.selected_file = tk.StringVar()
        self.folder = tk.StringVar()
        self.doc_name = tk.StringVar()
        self.document_id = tk.StringVar()          # 空文档创建后回填
        self.doc_ready = False                     # 索引是否完成（决定能否推分段）

        self.parent_sep = tk.StringVar(value="@!@")
        self.parent_tokens = tk.StringVar(value="2000")
        self.child_sep = tk.StringVar(value="@@")
        self.child_tokens = tk.StringVar(value="1000")
        self.batch_size = tk.StringVar(value="10")
        self.remove_urls = tk.BooleanVar(value=False)
        self.skip_existing = tk.BooleanVar(value=True)   # 批量上传：跳过库内同名
        self.wait_index = tk.BooleanVar(value=True)      # 批量上传：等索引完成再下一个

        # 高级（默认空 = 不传，跟随知识库配置）
        self.embedding_model = tk.StringVar()
        self.embedding_provider = tk.StringVar()
        self.extra_json = tk.StringVar()

        self.cancel_event = threading.Event()
        self.busy = False
        self.file_path: Optional[Path] = None
        self.file_text: Optional[str] = None
        self.batch_files: List[Path] = []           # 文件夹模式下的待上传清单
        self._datasets: Dict[str, Dict[str, Any]] = {}  # 下拉显示文本 → 知识库对象
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self._build_ui()
        self.root.after(120, self._drain_log)
        self.log("已适配 Dify 1.20.0：embedding 默认不传；建空文档后需等索引 completed 才能推分段。")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 1. 连接配置
        cfg = ttk.LabelFrame(main, text="① 连接配置", padding=8)
        cfg.pack(fill=tk.X, pady=(0, 8))
        cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="访问地址:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(cfg, textvariable=self.api_base_url, font=self.font).grid(row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Button(cfg, text="校验", width=8, command=self.start_check).grid(row=0, column=2, padx=6)

        ttk.Label(cfg, text="访问密钥:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(cfg, textvariable=self.api_key, show="*", font=self.font).grid(row=1, column=1, sticky=tk.EW, pady=3)

        ttk.Label(cfg, text="知识库:", font=self.font).grid(row=2, column=0, sticky=tk.W, pady=3)
        self.kb_combo = ttk.Combobox(cfg, textvariable=self.kb_choice, state="readonly", font=self.font)
        self.kb_combo.grid(row=2, column=1, sticky=tk.EW, pady=3)
        self.kb_combo.bind("<<ComboboxSelected>>", self._on_kb_select)
        ttk.Button(cfg, text="刷新列表", width=8, command=self.start_refresh_datasets).grid(row=2, column=2, padx=6)

        ttk.Label(cfg, text="知识库ID:", font=self.font).grid(row=3, column=0, sticky=tk.W, pady=3)
        ttk.Entry(cfg, textvariable=self.dataset_id, font=self.font).grid(row=3, column=1, sticky=tk.EW, pady=3)
        ttk.Button(cfg, text="列出文档", width=8, command=self.start_list_docs).grid(row=3, column=2, padx=6)

        # 2. 文档
        doc = ttk.LabelFrame(main, text="② 文档（单文件 或 整个文件夹批量）", padding=8)
        doc.pack(fill=tk.X, pady=(0, 8))
        doc.columnconfigure(1, weight=1)
        ttk.Label(doc, text="本地文件:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(doc, textvariable=self.selected_file, font=self.font).grid(row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Button(doc, text="浏览", width=8, command=self.browse_file).grid(row=0, column=2, padx=6)

        ttk.Label(doc, text="文件夹:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(doc, textvariable=self.folder, font=self.font).grid(row=1, column=1, sticky=tk.EW, pady=3)
        ttk.Button(doc, text="选择文件夹", width=10, command=self.browse_folder).grid(row=1, column=2, padx=6)

        ttk.Label(doc, text="文档名:", font=self.font).grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(doc, textvariable=self.doc_name, font=self.font).grid(row=2, column=1, sticky=tk.EW, pady=3)
        batch_opts = ttk.Frame(doc)
        batch_opts.grid(row=2, column=2, sticky=tk.W, padx=6)
        ttk.Checkbutton(batch_opts, text="跳过同名", variable=self.skip_existing).pack(side=tk.LEFT)
        ttk.Checkbutton(batch_opts, text="等索引", variable=self.wait_index).pack(side=tk.LEFT)

        ttk.Label(doc, text="文档ID:", font=self.font).grid(row=3, column=0, sticky=tk.W, pady=3)
        ttk.Entry(doc, textvariable=self.document_id, font=self.font).grid(row=3, column=1, sticky=tk.EW, pady=3)
        ttk.Button(doc, text="查询状态", width=8, command=self.start_check_doc).grid(row=3, column=2, padx=6)

        # 3. 分段设置
        seg = ttk.LabelFrame(main, text="③ 分段设置（服务端按分隔符切父/子分段）", padding=8)
        seg.pack(fill=tk.X, pady=(0, 8))
        for i in range(4):
            seg.columnconfigure(i, weight=1)

        ttk.Label(seg, text="父分段分隔符:", font=self.font).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(seg, textvariable=self.parent_sep, width=12, font=self.font).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(seg, text="父块 max_tokens:", font=self.font).grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(seg, textvariable=self.parent_tokens, width=10, font=self.font).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(seg, text="子分段分隔符:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(seg, textvariable=self.child_sep, width=12, font=self.font).grid(row=1, column=1, sticky=tk.W, pady=(6, 0))
        ttk.Label(seg, text="子块 max_tokens:", font=self.font).grid(row=1, column=2, sticky=tk.W, pady=(6, 0))
        ttk.Entry(seg, textvariable=self.child_tokens, width=10, font=self.font).grid(row=1, column=3, sticky=tk.W, pady=(6, 0))

        ttk.Label(seg, text="每批分段条数:", font=self.font).grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(seg, textvariable=self.batch_size, width=12, font=self.font).grid(row=2, column=1, sticky=tk.W, pady=(6, 0))
        ttk.Checkbutton(seg, text="删除 URL/邮箱", variable=self.remove_urls).grid(row=2, column=2, columnspan=2, sticky=tk.W, pady=(6, 0))

        # 4. 高级（1.20.0 里 embedding 必须与实例上真实存在的 provider 一致，留空则跟随知识库）
        adv = ttk.LabelFrame(main, text="④ 高级（留空 = 不提交，跟随知识库配置，推荐）", padding=8)
        adv.pack(fill=tk.X, pady=(0, 8))
        adv.columnconfigure(1, weight=1)
        ttk.Label(adv, text="embedding 模型:", font=self.font).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(adv, textvariable=self.embedding_model, font=self.font).grid(row=0, column=1, sticky=tk.EW)
        ttk.Label(adv, text="provider:", font=self.font).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(adv, textvariable=self.embedding_provider, width=34, font=self.font).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(adv, text="附加参数 JSON:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(adv, textvariable=self.extra_json, font=self.font).grid(
            row=1, column=1, columnspan=3, sticky=tk.EW, pady=(6, 0))
        ttk.Label(adv, text="如 {\"retrieval_model\": {...}}，一般不用填", foreground="#888").grid(
            row=2, column=1, columnspan=3, sticky=tk.W)

        # 5. 操作按钮
        btns = ttk.Frame(main)
        btns.pack(fill=tk.X, pady=(0, 8))
        self.btn_file = ttk.Button(btns, text="整篇上传（推荐）", width=18, command=self.start_upload_whole)
        self.btn_file.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_empty = ttk.Button(btns, text="建空文档并等索引", width=18, command=self.start_create_empty)
        self.btn_empty.pack(side=tk.LEFT, padx=6)
        self.btn_seg = ttk.Button(btns, text="上传分段", width=14, state=tk.DISABLED, command=self.start_upload_segments)
        self.btn_seg.pack(side=tk.LEFT, padx=6)
        self.btn_clear = ttk.Button(btns, text="清空分段", width=12, command=self.start_clear_segments)
        self.btn_clear.pack(side=tk.LEFT, padx=6)
        self.btn_cancel = ttk.Button(btns, text="取消", width=10, state=tk.DISABLED, command=self.cancel)
        self.btn_cancel.pack(side=tk.LEFT, padx=6)

        # 6. 日志 + 进度
        logf = ttk.LabelFrame(main, text="处理日志", padding=8)
        logf.pack(fill=tk.BOTH, expand=True)
        self.log_text = scrolledtext.ScrolledText(logf, wrap=tk.WORD, font=self.font, height=16)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state=tk.DISABLED)

        self.progress = ttk.Progressbar(main, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(8, 0))
        self.status = tk.StringVar(value="就绪")
        ttk.Label(main, textvariable=self.status, font=self.font).pack(anchor=tk.W, pady=(4, 0))

    # -------------------------------------------------------------- 日志/状态
    def log(self, message: str) -> None:
        self.log_queue.put(f"[{datetime.now():%H:%M:%S}] {message}")

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, line + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._drain_log)

    def _on_main(self, fn: Callable[[], None]) -> None:
        """工作线程里改 UI 一律回到主线程执行，避免 Tk 跨线程崩溃。"""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self.root.after(0, fn)

    def set_progress(self, value: int, text: Optional[str] = None) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, lambda: self.set_progress(value, text))
            return
        self.progress["value"] = max(0, min(100, value))
        if text is not None:
            self.status.set(text)

    def _notify(self, kind: str, title: str, message: str) -> None:
        """messagebox 的线程安全带包装。"""
        self._on_main(lambda: getattr(messagebox, kind)(title, message))

    def _set_busy(self, busy: bool) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, lambda: self._set_busy(busy))
            return
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for b in (self.btn_file, self.btn_empty, self.btn_clear):
            b.configure(state=state)
        self.btn_cancel.configure(state=tk.NORMAL if busy else tk.DISABLED)
        # 分段按钮只在「索引已完成且空闲」时可点（1.20.0 硬性要求）
        self.btn_seg.configure(state=tk.NORMAL if (not busy and self.doc_ready) else tk.DISABLED)

    def _run(self, fn: Callable[[], None], name: str) -> None:
        """把耗时操作丢到工作线程，异常统一进日志。"""
        if self.busy:
            messagebox.showwarning("提示", "当前有任务在执行，请等待或点取消")
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.set_progress(0, name)

        def wrapper() -> None:
            try:
                fn()
            except DifyError as exc:
                self.log(f"[错误] {exc}")
                self._notify("showerror", "错误", str(exc))
            except Exception as exc:  # noqa: BLE001
                self.log(f"[异常] {type(exc).__name__}: {exc}")
                self._notify("showerror", "异常", f"{type(exc).__name__}: {exc}")
            finally:
                self._set_busy(False)
                self.log_queue.put(f"[{datetime.now():%H:%M:%S}] —— {name} 结束 ——")

        threading.Thread(target=wrapper, daemon=True).start()

    # -------------------------------------------------------------- 客户端
    def _client(self, need_dataset: bool = True) -> DifyClient:
        base = self.api_base_url.get().strip()
        key = self.api_key.get().strip()
        ds = self.dataset_id.get().strip()
        if not base:
            raise DifyError("请填写访问地址")
        if not key or key == PLACEHOLDER_KEY:
            raise DifyError("请填写访问密钥")
        if need_dataset and not ds:
            raise DifyError("请填写知识库ID")
        return DifyClient(base, key, ds)

    def _payload(self) -> Dict[str, Any]:
        """组装 1.20.0 的 create-by-* 公共参数。"""
        payload: Dict[str, Any] = {
            "indexing_technique": "high_quality",
            "doc_form": "hierarchical_model",
            "doc_language": "Chinese Simplified",
            "process_rule": {
                "mode": "hierarchical",
                "rules": {
                    "parent_mode": "paragraph",
                    "pre_processing_rules": [
                        {"id": "remove_extra_spaces", "enabled": True},
                        {"id": "remove_urls_emails", "enabled": bool(self.remove_urls.get())},
                    ],
                    "segmentation": {
                        "separator": self._decode_sep(self.parent_sep.get()),
                        "max_tokens": self._int(self.parent_tokens, "父块 max_tokens"),
                    },
                    "subchunk_segmentation": {
                        "separator": self._decode_sep(self.child_sep.get()),
                        "max_tokens": self._int(self.child_tokens, "子块 max_tokens"),
                    },
                },
            },
        }
        # 1.20.0：只有填了才传，否则用知识库自己的 embedding，避免 Provider not exist
        if self.embedding_model.get().strip():
            payload["embedding_model"] = self.embedding_model.get().strip()
        if self.embedding_provider.get().strip():
            payload["embedding_model_provider"] = self.embedding_provider.get().strip()
        extra = self.extra_json.get().strip()
        if extra:
            try:
                payload.update(json.loads(extra))
            except ValueError as exc:
                raise DifyError(f"附加参数 JSON 解析失败：{exc}")
        return payload

    @staticmethod
    def _int(var: tk.StringVar, label: str) -> int:
        try:
            return int(var.get().strip())
        except ValueError:
            raise DifyError(f"{label} 必须是整数")

    @staticmethod
    def _decode_sep(raw: str) -> str:
        """单行输入框打不出真换行，允许写 \\n / \\t / \\r 转义（Dify 的默认父分隔符就是 \\n\\n）。"""
        return raw.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")

    # -------------------------------------------------------------- 动作
    def browse_file(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("文档", "*.md *.txt *.pdf *.docx *.csv *.xlsx *.html"), ("所有文件", "*.*")]
        )
        if not path:
            return
        self.file_path = Path(path)
        self.selected_file.set(path)
        self.folder.set("")            # 单文件模式：清掉文件夹批量清单
        self.batch_files = []
        self.doc_name.set(self.file_path.name)
        if self.file_path.suffix.lower() in {".md", ".markdown", ".txt"}:
            try:
                self.file_text = self.file_path.read_text(encoding="utf-8", errors="replace")
                parent = self._decode_sep(self.parent_sep.get())
                child = self._decode_sep(self.child_sep.get())
                has_parent = bool(parent) and parent in self.file_text
                has_child = bool(child) and child in self.file_text
                self.log(
                    f"读取 {self.file_path.name}：{len(self.file_text)} 字符，"
                    f"父标记 {self.parent_sep.get()!r} {'有' if has_parent else '缺失'}，"
                    f"子标记 {self.child_sep.get()!r} {'有' if has_child else '缺失'}"
                )
                if not has_parent:
                    self.log(
                        "  [提示] 没找到父分隔符：普通 md 建议把父分隔符输入框改成 \\n\\n（空行），"
                        "否则整篇只会切出 1 个父分段"
                    )
            except OSError as exc:
                self.log(f"读取文件失败：{exc}")
        else:
            self.file_text = None
            self.log(f"已选择 {self.file_path.name}（二进制文件，整篇上传原样交给服务端解析）")

    # --- 文件夹批量 ---
    @staticmethod
    def _scan_folder(folder: Path) -> List[Path]:
        """递归扫描受支持扩展名的文件，跳过隐藏文件与 Office 临时文件。"""
        files: List[Path] = []
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if p.name.startswith(("~$", ".")):
                continue
            files.append(p)
        return files

    def browse_folder(self) -> None:
        path = filedialog.askdirectory(title="选择要批量上传的文件夹")
        if not path:
            return
        folder = Path(path)
        files = self._scan_folder(folder)
        self.folder.set(path)
        self.batch_files = files
        self.file_path = None          # 文件夹模式：不再用单文件
        self.file_text = None
        self.selected_file.set("")
        self.doc_name.set("")          # 文档名取各自文件名
        if not files:
            self.log(f"文件夹 {folder} 下没有可上传的文档（支持 {', '.join(SUPPORTED_EXTS)}）")
            self._notify("showwarning", "提示", "该文件夹（含子目录）下没有受支持的文档")
            self.set_progress(0, "没有可上传的文件")
            return
        self.log(f"已选择文件夹：{folder}")
        self.log(f"递归扫描到 {len(files)} 个文件：")
        for f in files:
            try:
                rel = f.relative_to(folder)
            except ValueError:
                rel = f
            self.log(f"  - {rel}  ({f.stat().st_size} bytes)")
        self.set_progress(0, f"待上传 {len(files)} 个文件")

    def _upload_targets(self) -> List[Path]:
        if self.batch_files:
            return list(self.batch_files)
        if self.file_path:
            return [self.file_path]
        return []

    def start_refresh_datasets(self) -> None:
        """用当前地址+密钥拉知识库列表，填充下拉框（看不到列表就手填 ID）。"""
        def job() -> None:
            client = self._client(need_dataset=False)
            items = client.list_datasets()
            if not items:
                self.log("[提示] 该密钥下没有可见的知识库：请检查密钥权限，或手工填知识库ID")
                return
            mapping: Dict[str, Dict[str, Any]] = {}
            labels: List[str] = []
            for ds in items:
                base = f"{ds.get('name')}（{str(ds.get('id'))[:8]}）"
                label, n = base, 2
                while label in mapping:
                    label = f"{base}#{n}"
                    n += 1
                mapping[label] = ds
                labels.append(label)
            self._on_main(lambda: self._apply_dataset_list(labels, mapping))
            self.log(f"共 {len(items)} 个知识库已填入下拉框")
            self.set_progress(100, "知识库列表已刷新")
        self._run(job, "刷新知识库列表")

    def _apply_dataset_list(self, labels: List[str], mapping: Dict[str, Dict[str, Any]]) -> None:
        self._datasets = mapping
        self.kb_combo.configure(values=labels)
        current = self.dataset_id.get().strip()
        for label, ds in mapping.items():
            if ds.get("id") == current:      # 保持已选中的那个
                self.kb_choice.set(label)
                return
        if labels:
            self.kb_choice.set(labels[0])
            self._on_kb_select()

    def _on_kb_select(self, _event: object = None) -> None:
        ds = self._datasets.get(self.kb_choice.get())
        if not ds:
            return
        self.dataset_id.set(ds.get("id") or "")
        self.log(
            f"已选择知识库：{ds.get('name')}  id={ds.get('id')}\n"
            f"    doc_form={ds.get('doc_form')}  "
            f"embedding={ds.get('embedding_model')}({ds.get('embedding_model_provider')})  "
            f"文档数={ds.get('document_count')}"
        )
        if (ds.get("doc_form") or "") == "hierarchical_model" and self.parent_sep.get() == "@!@":
            self.log("   [提示] 若文档未预埋 @!@ 标记，把父分隔符改成 \\n\\n 更合适")

    def start_check(self) -> None:
        def job() -> None:
            client = self._client(need_dataset=False)
            ds_id = self.dataset_id.get().strip()
            if not ds_id:
                items = client.list_datasets()
                for ds in items:
                    self.log(
                        f"知识库 {ds.get('name')}  id={ds.get('id')}  文档={ds.get('document_count')}  "
                        f"doc_form={ds.get('doc_form')}  embedding={ds.get('embedding_model')}"
                        f"({ds.get('embedding_model_provider')})"
                    )
                if items:
                    self.log("可直接用上面的下拉框选知识库，无需手抄 ID")
                return
            info = client.dataset_info()
            self.log(
                f"知识库：{info.get('name')}  doc_form={info.get('doc_form')}  "
                f"embedding={info.get('embedding_model')}({info.get('embedding_model_provider')})  "
                f"文档数={info.get('document_count')}"
            )
            self.set_progress(100, "连接正常")
        self._run(job, "校验连接")

    def start_list_docs(self) -> None:
        def job() -> None:
            client = self._client()
            docs = client.list_documents()
            for d in docs:
                self.log(f"  {d.get('name')}  [{d.get('indexing_status')}]  tokens={d.get('tokens')}  id={d.get('id')}")
            self.log(f"共 {len(docs)} 个文档")
            self.set_progress(100, "文档列表已输出")
        self._run(job, "列出文档")

    def start_check_doc(self) -> None:
        def job() -> None:
            doc_id = self.document_id.get().strip()
            if not doc_id:
                raise DifyError("请先填文档ID")
            client = self._client()
            doc = client.get_document(doc_id)
            status = (doc.get("indexing_status") or "").lower()
            self.log(
                f"文档 {doc.get('name')}  indexing_status={status}  tokens={doc.get('tokens')}  "
                f"segments={doc.get('segment_count')}  error={doc.get('error')}"
            )
            self._mark_ready(status == "completed")
            seg = client.list_segments(doc_id)
            self.log(f"父分段 total={seg.get('total')}  doc_form={seg.get('doc_form')}")
            self.set_progress(100, f"状态 {status}")
        self._run(job, "查询文档状态")

    def _mark_ready(self, ready: bool) -> None:
        def apply() -> None:
            self.doc_ready = ready
            if not self.busy:
                self.btn_seg.configure(state=tk.NORMAL if ready else tk.DISABLED)
            if ready:
                self.log("索引已完成，可以上传分段")
            else:
                self.log("索引未完成：1.20.0 下此时推分段会 404 Document is not completed，已禁用该按钮")
        self._on_main(apply)

    # --- 整篇上传（推荐；文件夹模式即批量）---
    def start_upload_whole(self) -> None:
        targets = self._upload_targets()
        if not targets:
            messagebox.showerror("错误", "请先选择文件或文件夹")
            return
        single = len(targets) == 1
        custom_name = (self.doc_name.get().strip() if single else "") or ""

        def job() -> None:
            client = self._client()
            payload = self._payload()
            total = len(targets)
            existing: set = set()
            if self.skip_existing.get():
                existing = {d.get("name") for d in client.list_documents()}
                self.log(f"库内现有文档 {len(existing)} 个，用于同名跳过判断")

            ok = skipped = failed = 0
            for idx, path in enumerate(targets, 1):
                if self.cancel_event.is_set():
                    self.log("用户取消，停止批量上传")
                    break
                name = custom_name or path.name
                self.set_progress(int(100 * (idx - 1) / total), f"({idx}/{total}) {name}")
                if self.skip_existing.get() and name in existing:
                    self.log(f"[{idx}/{total}] 跳过（库内已有同名）：{name}")
                    skipped += 1
                    continue
                try:
                    self.log(f"[{idx}/{total}] 上传：{path}")
                    resp = client.create_by_file(path, payload)
                    doc_id = (resp.get("document") or {}).get("id")
                    self._on_main(lambda d=doc_id: self.document_id.set(d or ""))
                    self.log(f"[{idx}/{total}] 创建成功 document_id={doc_id}")
                    if self.wait_index.get():
                        final = client.wait_indexed(doc_id, on_status=self._on_index_status,
                                                    cancel=self.cancel_event, timeout=900)
                        status = (final.get("indexing_status") or "").lower()
                        detail = (f"status={status} tokens={final.get('tokens')} "
                                  f"segments={final.get('segment_count')}")
                        if final.get("error"):
                            detail += f" error={final.get('error')}"
                        self.log(f"[{idx}/{total}] 索引结束：{detail}")
                        self._mark_ready(status == "completed")
                        if status != "completed":
                            failed += 1
                            continue
                    ok += 1
                except DifyError as exc:      # 单个文件失败不影响整批
                    failed += 1
                    self.log(f"[{idx}/{total}] 失败：{name} — {exc}")
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.log(f"[{idx}/{total}] 异常：{name} — {type(exc).__name__}: {exc}")

            self.log(f"批量上传结束：成功 {ok}，跳过 {skipped}，失败 {failed}，共 {total}")
            self.set_progress(100, f"成功 {ok} / 跳过 {skipped} / 失败 {failed}")
            self._notify(
                "showinfo" if failed == 0 else "showwarning",
                "完成" if failed == 0 else "部分失败",
                f"成功 {ok}，跳过 {skipped}，失败 {failed}（共 {total}）",
            )

        self._run(job, "整篇上传")

    # --- 建空文档并等索引 ---
    def start_create_empty(self) -> None:
        if self.batch_files:
            messagebox.showinfo("提示", "文件夹模式请直接用「整篇上传」；手工分段只支持单文件")
            return
        if not self.file_path:
            messagebox.showerror("错误", "请先选择文件（用它的文件名建文档）")
            return

        def job() -> None:
            client = self._client()
            name = self.doc_name.get().strip() or self.file_path.name
            self.log(f"创建空文档：{name}（text 为空，随后手工推分段）")
            resp = client.create_by_text(name, "", self._payload())
            doc_id = (resp.get("document") or {}).get("id")
            self._on_main(lambda: self.document_id.set(doc_id or ""))
            self.log(f"创建成功 document_id={doc_id}")
            self._mark_ready(False)
            self.set_progress(30, "等待索引完成（1.20.0 必需）")
            final = client.wait_indexed(doc_id, on_status=self._on_index_status,
                                        cancel=self.cancel_event, timeout=900)
            status = (final.get("indexing_status") or "").lower()
            self._mark_ready(status == "completed")
            self.set_progress(100, f"索引 {status}")
            if status == "completed":
                self._notify("showinfo", "成功",
                             f"空文档已就绪，可以点「上传分段」\n文档ID: {doc_id}")

        self._run(job, "创建空文档")

    def _on_index_status(self, status: str, doc: Dict[str, Any]) -> None:
        self.log(f"  索引状态：{status}" + (f"  error={doc.get('error')}" if doc.get("error") else ""))

    # --- 上传分段（批量）---
    def start_upload_segments(self) -> None:
        doc_id = self.document_id.get().strip()
        if self.batch_files:
            messagebox.showinfo("提示", "文件夹模式请直接用「整篇上传」；手工分段只支持单文件")
            return
        if not doc_id:
            messagebox.showerror("错误", "请先建空文档或填写文档ID")
            return
        if not self.doc_ready:
            messagebox.showerror("错误", "文档索引未完成，1.20.0 下推分段会报 Document is not completed")
            return
        if self.file_text is None:
            messagebox.showerror("错误", "当前文件不是文本/markdown，无法按分隔符切分；请用「整篇上传」")
            return

        def job() -> None:
            client = self._client()
            parent = self._decode_sep(self.parent_sep.get())
            if not parent:
                raise DifyError("父分隔符不能为空")
            chunks = [c.strip() for c in self.file_text.split(parent) if c.strip()]
            if not chunks:
                raise DifyError("按父分隔符切分后没有内容")
            batch = max(1, self._int(self.batch_size, "每批条数"))
            self.log(f"按 {self.parent_sep.get()!r} 切出 {len(chunks)} 个父分段，每批 {batch} 条")
            pos = 1
            ok_batches = 0
            for i in range(0, len(chunks), batch):
                if self.cancel_event.is_set():
                    self.log("用户取消，停止上传")
                    break
                group = chunks[i:i + batch]
                segments = [
                    {"content": text, "answer": "", "position": pos + j}
                    for j, text in enumerate(group)
                ]
                self.log(f"  提交第 {i // batch + 1} 批：{len(segments)} 条（position {pos}~{pos + len(segments) - 1}）")
                client.add_segments(doc_id, segments)
                ok_batches += 1
                pos += len(segments)
                self.set_progress(10 + int(85 * pos / len(chunks)), f"已提交 {pos}/{len(chunks)}")
            total = client.list_segments(doc_id).get("total")
            self.log(f"分段上传结束：成功批次 {ok_batches}，父分段总数 {total}")
            self.set_progress(100, f"父分段总数 {total}")
            if not self.cancel_event.is_set():
                self._notify("showinfo", "完成", f"分段上传完成，当前父分段总数 {total}")

        self._run(job, "上传分段")

    # --- 清空分段 ---
    def start_clear_segments(self) -> None:
        doc_id = self.document_id.get().strip()
        if not doc_id:
            messagebox.showerror("错误", "请先填文档ID")
            return
        if not messagebox.askyesno("确认", f"将删除文档 {doc_id} 下的全部父分段，继续？"):
            return

        def job() -> None:
            client = self._client()
            deleted = 0
            while True:
                if self.cancel_event.is_set():
                    self.log("用户取消")
                    break
                data = (client.list_segments(doc_id, limit=100).get("data") or [])
                if not data:
                    break
                for seg in data:
                    if self.cancel_event.is_set():
                        break
                    client.delete_segment(doc_id, seg["id"])
                    deleted += 1
                    self.set_progress(min(95, deleted), f"已删除 {deleted} 条")
                self.log(f"已删除 {deleted} 条父分段…")
            total = client.list_segments(doc_id).get("total")
            self.log(f"清空结束：删除 {deleted} 条，剩余 {total} 条")
            self.set_progress(100, f"剩余 {total} 条")

        self._run(job, "清空分段")

    def cancel(self) -> None:
        self.cancel_event.set()
        self.log("已请求取消，等待当前请求返回…")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    DifyUploaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
