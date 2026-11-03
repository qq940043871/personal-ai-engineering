# -*- coding: utf-8 -*-
"""第 0 步：PDF / 扫描件 → 结构化 Markdown（MinerU）。

为什么需要这一步：
    本工程 01_/02_ 脚本的输入是「带 # / ## / ### 层级的中文 Markdown」，
    而 PDF 原件（尤其扫描件）得先经 MinerU 转成 md。本脚本把这步固化，
    并做最小必要的结构归一化 —— 因为 01_main_append_title.py 找不到 `# `
    会直接抛错、找不到 `## ` 会静默产出空文件。

链路位置：
    PDF ──00(本脚本)──> md ──02_add_split_to_periods.py──> md(已插 @@)
        ──01_main_append_title.py──> 切片 md(含 @!@) ──> 灌 Dify 知识库

用法：
    python 00_pdf_to_md_mineru.py 结算细则.pdf -o ./mineru_out
    python 00_pdf_to_md_mineru.py 结算细则.pdf -b vlm                 # 扫描件/复杂版式
    python 00_pdf_to_md_mineru.py ./pdfs -o ./mineru_out               # 目录批量
    python 00_pdf_to_md_mineru.py x.pdf --base-url http://127.0.0.1:8888  # 服务化部署

MinerU 接口约定（与 ai-rag-self-engineering/ownrag/ownrag/ingest/pdf_mineru.py 对齐）：
    CLI  : mineru -p <pdf> -o <out_dir>  → 在 out_dir 下 rglob("*.md") 取第一个
    HTTP : POST {base}/file_parse        → {"markdown": str, "pages": int, "assets": dict}

依赖：标准库 + requests（HTTP 模式）；MinerU 本体需自行安装（pip install -U "mineru[core]"）。
"""
import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

_FENCE = re.compile(r"^\s*(```|~~~)")
_H2_RE = re.compile(r"^(\d+)[.、)]\s+\S")
_H3_RE = re.compile(r"^(\d+\.\d+)[.、)]?\s+\S")


# --------------------------------------------------------------------- MinerU 调用
def _via_cli(pdf: Path, out_dir: Path, backend: str, lang: str, cmd_name: str) -> Path:
    """拉起 MinerU CLI，返回产出 md 路径。"""
    if not shutil.which(cmd_name):
        raise RuntimeError(
            f"MinerU CLI 不可用：{cmd_name} 未找到。安装：pip install -U \"mineru[core]\"；"
            "或改用 --base-url 走服务化部署。"
        )
    cmd = [cmd_name, "-p", str(pdf), "-o", str(out_dir)]
    if backend and backend != "auto":
        cmd += ["-b", backend]
    if lang:
        cmd += ["-l", lang]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"MinerU CLI 失败（rc={proc.returncode}）：{proc.stderr[-500:]}")
    mds = sorted(out_dir.rglob("*.md"))
    if not mds:
        raise RuntimeError(f"MinerU CLI 未产出 Markdown：{out_dir}")
    return mds[0]


def _via_http(pdf: Path, out_dir: Path, base_url: str, backend: str, lang: str) -> Path:
    """POST 文件到 MinerU 服务，落盘返回 md 路径。"""
    import requests

    url = f"{base_url.rstrip('/')}/file_parse"
    with open(pdf, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (pdf.name, f)},
            data={"backend": backend or "auto", "lang": lang or "ch"},
            timeout=600,
        )
    resp.raise_for_status()
    payload = resp.json()
    md_text = payload.get("markdown", "")
    if not md_text.strip():
        raise RuntimeError(f"MinerU 服务返回空 Markdown：{url}")
    # 资源（图片等）落到同目录，便于人工核对
    assets = payload.get("assets") or {}
    if isinstance(assets, dict) and assets:
        (out_dir / "assets_index.json").write_text(
            __import__("json").dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    md_path = out_dir / f"{pdf.stem}.md"
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


def normalize(md_text: str, title: str = None, dedup_repeat: int = 5) -> str:
    """最小必要的结构修复：保证 1 个 H1、存在 H2/H3，且不动行首编号正文（留给 02_ 插 @@）。

    只做「结构保底」，不重排内容、不改写正文 —— 保证 02_/01_ 脚本能跑通。
    """
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

        # 1) 多个 H1：保留第一个，其余降级为 H2（MinerU 常把每章都识别成 H1）
        if t.startswith("# "):
            if h1_seen:
                out.append("## " + t[2:].strip())
            else:
                h1_seen = True
                out.append(line)
            continue

        # 2) 缺 H2：把顶层编号行（"1. 总则"）提升为 H2
        if not has_h2 and _H2_RE.match(t) and not t.startswith("|"):
            out.append("## " + t)
            continue

        # 3) 缺 H3：把二级编号行（"1.1. 制定目的"）提升为 H3
        if not has_h3 and _H3_RE.match(t) and not t.startswith("|"):
            out.append("### " + t)
            continue

        out.append(line)

    if not has_h1:
        # 全文无 H1：用传入标题（默认文件名）补一行，否则 01_ 直接抛 "未找到一级标题"
        out.insert(0, f"# {title or '未命名文档'}")
        out.insert(1, "")

    return "\n".join(out).strip() + "\n"


def _stats(text: str) -> dict:
    h1, h2, h3, num = _scan_levels(text.splitlines())
    return {"H1": h1, "H2": h2, "H3": h3, "行首编号": num}


# --------------------------------------------------------------------- 主流程
def process_one(pdf: Path, args) -> Path:
    out_dir = Path(args.out) / pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[MinerU] 解析 {pdf.name} → {out_dir}")
    if args.base_url:
        md_path = _via_http(pdf, out_dir, args.base_url, args.backend, args.lang)
    else:
        md_path = _via_cli(pdf, out_dir, args.backend, args.lang, args.mineru)

    raw = md_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise RuntimeError(f"MinerU 产出空 Markdown：{md_path}")
    before = _stats(raw)

    if args.no_normalize:
        final_path = md_path
        after = before
    else:
        fixed = normalize(raw, args.title or pdf.stem, args.dedup_repeat)
        final_path = out_dir / f"{pdf.stem}_norm.md"
        final_path.write_text(fixed, encoding="utf-8")
        after = _stats(fixed)

    print(f"[MinerU] 原始 md: {md_path}")
    print(f"[MinerU] 归一化后: {final_path}")
    print(f"[MinerU] 结构统计 原始 {before} → 输出 {after}")

    if after["H2"] == 0:
        print("[警告] 没有二级标题：01_main_append_title.py 会产出空文件，请人工补 ## 或使用 --no-normalize 后检查。")
    if after["行首编号"] == 0:
        print("[提示] 未发现行首编号（如 3.2.1）：02_add_split_to_periods.py 将插不到 @@ 子分段标记。")
    return final_path


def collect_pdfs(target: Path):
    if target.is_dir():
        return sorted(target.glob("*.pdf"))
    return [target]


def main():
    ap = argparse.ArgumentParser(description="第 0 步：MinerU 把 PDF 解析为结构化 Markdown")
    ap.add_argument("input", help="PDF 文件或含 PDF 的目录")
    ap.add_argument("-o", "--out", default="./mineru_out", help="输出根目录（默认 ./mineru_out）")
    ap.add_argument("-b", "--backend", default="pipeline",
                    choices=["pipeline", "vlm", "auto"],
                    help="pipeline=电子版快 / vlm=扫描件准（默认 pipeline）")
    ap.add_argument("-l", "--lang", default="ch", help="文档语言（默认 ch）")
    ap.add_argument("--mineru", default="mineru", help="MinerU 可执行名或路径（默认 mineru）")
    ap.add_argument("--base-url", default=None,
                    help="走 MinerU 服务化部署，如 http://127.0.0.1:8888（不传则用 CLI）")
    ap.add_argument("--title", default=None, help="全文无 H1 时补的一级标题（默认用文件名）")
    ap.add_argument("--dedup-repeat", type=int, default=5,
                    help="重复出现 >=N 次的短行按页眉/页脚删除，0 关闭（默认 5）")
    ap.add_argument("--no-normalize", action="store_true", help="跳过结构归一化，保留 MinerU 原样输出")
    args = ap.parse_args()

    target = Path(args.input)
    if not target.exists():
        sys.exit(f"输入不存在：{target}")
    pdfs = collect_pdfs(target)
    if not pdfs:
        sys.exit(f"目录下没有 PDF：{target}")

    ok, fail = [], []
    for pdf in pdfs:
        try:
            ok.append(process_one(pdf, args))
        except Exception as e:  # 单份失败不阻断批量
            fail.append((pdf.name, str(e)))
            print(f"[错误] {pdf.name}：{e}", file=sys.stderr)

    print(f"\n完成 {len(ok)} 份，失败 {len(fail)} 份。")
    print("下一步：python 02_add_split_to_periods.py <上面的输出md> 1_1_new_process.md")
    if fail:
        for name, why in fail:
            print(f"  - {name}: {why}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
