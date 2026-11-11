# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## What this repo is

A personal AI-engineering learning workspace: a monorepo aggregating several independent
subprojects side by side. There is no single build, package manifest, or test suite at the
root — each subproject is self-contained and is developed/run on its own.

The root README and the tree below list the same eight subproject directories (2026-11: the retired single-file portal was removed and `ai-tools/` added).

## Layout

```
personal-ai-engineering/
├── ai-agent-harness/ # Multi-agent runtime framework (Python) — the main code project
├── ai-study-labs/    # AI study主工程: framework learning code + prompt collections (numbered dirs)
├── ai-study-note/    # Static course site + LLM interview question bank (HTML/JS)
├── ai-rag-ollama/    # Local Ollama chat + RAG experiments (Flask + Chroma)
├── ai-rag-dify/      # Dify / RAGFlow knowledge-base tooling + notes (relocated from ai-study-labs)
├── ai-rag-self-engineering/  # Self-built RAG engineering (ownrag): design docs 00-06 + FastAPI skeleton
├── ai-tools/         # Standalone tools/scripts (moved from ai-study-labs/50_tools in 2026-11)
├── ai-tutorial-video/ # Tutorial-video pipeline: HTML scene → Playwright frames → ffmpeg MP4 + edge-tts
├── README.md
├── CODEBUDDY.md
└── .gitignore
```

## ai-agent-harness (read its own docs first)

This is the only substantial Python project. It is a from-scratch reimplementation following
the course《从 0 开始构建 Agent Harness》. Before working here, read:

- `ai-agent-harness/AGENTS.md` — agent behavior rules defined **for this subproject** (identity
  "OpenClaw", workflow, forbidden actions). These apply inside `ai-agent-harness/`.
- `ai-agent-harness/docs/ARCHITECTURE.md` — module architecture (Main Loop, Provider, Tools, Session,
  Middleware, Tracer, Context Compactor) and data flow.
- `ai-agent-harness/docs/USAGE.md`, `QUICKSTART.md` — setup/run detail.

Core architecture (see `ai-agent-harness/harness/`):
- `main_loop.py` drives the Think → Act → Observe loop; emits events via `on()`/`off()`.
- `provider/` is a strategy+factory abstraction over LLM APIs (`claude.py`, `openai_compat.py`;
  doubao/qwen/deepseek/spark/volcengine_plan go through OpenAI-compatible providers).
- `tools/` uses decorator + registry registration (`registry.tool(...)`), auto-infers JSON
  Schema, supports parallel dispatch. Plugin tools live in `tools/plugins/`.
- `session/`, `context_compactor.py`, `memory_manager.py`, `middleware.py`, `tracer.py`,
  `cost_tracker.py`, `system_reminders.py`, `subagent.py`, `multi_agent.py` are the surrounding
  subsystems. `docs/chapter01/`–`docs/chapter06/` are the course notes that map to each module.

### Commands (run from `ai-agent-harness/`)

```bash
# Setup
setup_env.bat                                   # Windows one-shot (or see setup_env.sh)
conda create -n agent-harness python=3.11 -y && conda activate agent-harness
pip install -r requirements.txt

# Config: config.yaml is gitignored — create it from the example and add keys
cp config/config.yaml.example config/config.yaml

# Run the three modes
python main.py "帮我分析项目结构"   # CLI, single task
python main.py                      # CLI, interactive
python web.py                       # Web UI (FastAPI + WebSocket) → http://localhost:8000
python gui.py                       # PyQt6 desktop app
```

Tests here are **standalone scripts, not pytest** (no pytest config in the repo). Run directly:

```bash
python tests/test_multi_agent.py    # multi-agent flow simulation (uses a MockProvider, no API key)
python tests/test_volcengine.py     # Volcengine/豆包 provider check (needs a real key)
```

## ai-study-labs

Top-level dirs are numbered by purpose (slots reserved for 60+/70+):

| Dir | Contents |
|---|---|
| `10_prompts/` | prompt collections (SQL, DeepSeek, template prompts) |
| `20_learn/` | framework learning: pytorch, paddle, paddlex, huggingface, modelscope, langchain, ocr, ffmpeg_opencv, openMNT |

No unified entrypoint — scripts are run individually. `ai-study-labs/README.md` contains a
historical path-mapping table (2026-10 reorg). dify/RAGFlow content was moved out in the same
reorg to the top-level `ai-rag-dify/`; the former `30_slides/` HTML course decks moved to
`ai-study-note/slides/` (2026-11), `quick_guide/` moved to `ai-study-note/quick_guide/`
(2026-11), and the former `40_projects/` was folded into `50_tools/`. **In 2026-11 `50_tools/`
itself moved out to the top-level `ai-tools/`** — see that section below; `ai-study-labs` now
only holds `10_prompts/` and `20_learn/`.

## ai-study-note (static site, no build step)

```bash
cd ai-study-note
./start.bat              # or: npx http-server -p 3001
python -m http.server 3001
# open http://localhost:3001
```

Entry `index.html`; Markdown viewer is `md-viewer.html?file=<relative-path>`; question bank
under `exam/`. `slides/` holds the paginated HTML course decks (`llm_base10/`, `llm_base20/`,
each with `index.html` carousel + `slide/00N.html`). `quick_guide/` holds the per-tech
"快速学习手册" Markdown handbooks (Dify, LangChain, Qwen, vector DBs, Canal, …).

## ai-rag-ollama

Flask-based local Ollama experiments (`01_ollama*.py`, `02_search_engine.py`,
`03_ollama_rag.py` + notebook). Requires a local Ollama install with models pulled
(e.g. `qwen2.5:0.5b`, `nomic-embed-text`). Pipeline deps: flask, flask-cors, requests,
chromadb, langchain — install per-script.

## ai-tools

Standalone tools and small projects: moved here from `ai-study-labs/50_tools/` in 2026-11, plus
several newer self-contained projects. No unified entrypoint — run each script from its own dir.

- Numbered scripts: `01_dydown/` (Douyin), `02_bibidown/` (Bilibili), `03_import_wset/`,
  `04_currency_list/`, and `10_*`-`43_*` (mock data, map plots, folder scans, batch renames, JVM diag)
- Self-contained projects: `doubao/` (Ark image/video, PDF diff), `time_task/`, `opengauss/`,
  `disk_cleaner/`, `doubao_multi_login/`, `meeting_minutes/`, `personal-wechat-jobs/`,
  `opencode-go-proxy/`
- `meeting_minutes/` and `personal-wechat-jobs/` ship their own `requirements.txt` / `setup.py`;
  12 standalone `test_*.py` scripts live in this subtree
- Runtime artifacts are gitignored: downloaded `video/`, `*.db`, recordings `*.wav`,
  `jvm_diag_*/` dumps, `cookie_*.txt`, and `dy-*.yaml` (login cookies — only the
  `dy-config.example.yaml` placeholder is committed)
- Many scripts contain stale absolute paths from older workspaces; fix them before running

## ai-tutorial-video

Tutorial-video generation pipeline: storyboard JSON → edge-tts narration → Playwright frame
capture → ffmpeg MP4. `src/` holds the modules (`build_video.py` is the orchestrator entry,
`extract_course.py` is a separate entry that drafts a storyboard from course HTML; `encode.py`,
`render.py`, `storyboard.py`, `tts.py` are libraries), `scripts/merge_series.py` concatenates
finished series, and `templates/scene.html` + `storyboards/*.json` are data. Modules are imported
as `from src import ...` (implicit namespace package — there is no `__init__.py` yet), so entry
scripts must be run from the subproject root:

```bash
cd ai-tutorial-video
python src/build_video.py --storyboard storyboards/llm_base10.json   # → output/llm_base10.mp4
```

## ai-rag-dify

Tooling and notes for Dify / RAGFlow knowledge bases: `01-minerU-block/` (uploader scripts +
`knowledge.spec`), `02-ocr/`, `03-dify-uploader/` (`api/` notes), and `04-ragflow-uploader/`
(`httpapi.md`). The uploaders are Tkinter GUIs with
hard-coded API base URLs — update host/key before running.

## ai-rag-self-engineering

Self-built RAG engineering ("ownrag") — what a fully self-developed RAG stack looks like without
Dify. Relocated 2026-11-02 from `personal-investment-notes/02-AI智能体/04-自研RAG工程/`.

- Docs `00-总览与口径.md` … `06-全链路梳理与视频RAG对照.md` — read `00` first: it states the positioning
  (personal project line alongside `ai-agent-harness`, **not** the company platform stack) and the
  "all metrics are `【设计】`/`【待实测】`" rule.
- Code: `ownrag/` (Python 3.10+ / FastAPI, `pip install -e .` inside it, `python -m pytest` for
  contract tests — no external services needed).
- **Cross-repo references** into the notes vault must use `../personal-investment-notes/...`
  (relative to this directory); do not copy those docs back here.

## Repo conventions (important)

- **Large artifacts are gitignored, not committed**: model weights (`*.pth/.pt/.onnx/
  *.safetensors/*.gguf/*.npz`), datasets (`ai-study-labs/20_learn/pytorch/data/`), run data
  (`output/`, `sessions/`, `logs/`, `ai-tools/**/jvm_diag_*/` diagnostic dumps), generated
  `pdf_diff` reports (`合同差异比对报告*.md`, `token消耗统计.json`) and API dumps, build outputs
  (`build/`, `dist/`, `*.exe`), downloaded video, contract PDFs (`pdf_diff/*.pdf`), and tool state
  (`.workbuddy/`, `.codebuddy/`, `.zcode/`). Don't `git add -f` these.
- **Secrets are masked in-repo**: real API keys are replaced with placeholders like
  `sk-REPLACE_WITH_YOUR_KEY` / `dataset-REPLACE_WITH_YOUR_KEY`. `config.yaml`, `.env`,
  `cookies.txt`, and `secrets_backup.txt` are gitignored. Never commit real keys.
- **`ai-tools/` credentials & artifacts**: `dy-*.yaml` (login cookies), `*.db`, `*.wav`
  recordings, `cookie_*.txt` and the proxy model entry file are all gitignored; only
  `dy-config.example.yaml` is kept as a placeholder. The old `ai-study-labs/50_tools/...`
  ignore rules were replaced when that tree moved out.
- **Historical absolute paths**: learning scripts contain stale paths (e.g.
  `d:\ai_coder\p000_ai_study_py\...`, `D:\workspace\...`). Fix to relative/current paths before
  running.
- **Subdir file layout** in ai-study-labs: source at dir root, notes in `notes/`, packaging
  rebuildable from `.spec` / `pipinstaller.bat`.

## Environment notes

Windows (win32) workspace; `.bat` launchers assume Windows. In this shell use forward-slash
paths (Git Bash). Prefer the dedicated Read/Edit/Write tools over shell `cat`/`sed`/`echo`.
