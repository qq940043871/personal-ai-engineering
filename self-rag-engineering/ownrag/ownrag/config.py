"""全局配置：包内 configs/*.yaml + 环境变量覆盖。原则：配置错误在启动期暴露，不在运行期。

两种部署形态都能解析到配置（这是打包后的关键约束）：
  源码树    ownrag/ownrag/configs/      ← 本文件同目录
  wheel 装  site-packages/ownrag/configs/ ← 同上
外部覆盖：OWNRAG_CONFIG_DIR 指向自定义配置目录（运维改配置不动包）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

# 包内配置目录：与代码同源，源码树 / wheel / 只读容器镜像都成立
PKG_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PKG_ROOT / "configs"


def _load_dotenv() -> None:
    """加载 .env（不覆盖已有环境变量）。python-dotenv 缺失时静默跳过——
    部署环境一律用真实环境变量，.env 只是本地便利，不能让缺少它导致启动失败。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (Path.cwd() / ".env", PKG_ROOT.parent / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def _resolve_config_dir() -> Path:
    """OWNRAG_CONFIG_DIR 显式覆盖 > 包内 configs；路径不存在即启动期报错（配置即代码）。"""
    override = os.environ.get("OWNRAG_CONFIG_DIR")
    path = Path(override).expanduser().resolve() if override else CONFIG_DIR
    if not path.is_dir():
        raise FileNotFoundError(f"配置目录不存在：{path}（OWNRAG_CONFIG_DIR 未指向有效目录）")
    return path


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"缺少配置文件：{path}（启动期校验，配置即代码）")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    data_dir: Path
    config_dir: Path
    ollama_base_url: str
    chat_model: str
    embed_model: str
    embed_version: str
    num_ctx: int
    max_new_tokens: int                   # 生成侧硬上限：无上限 = 单请求可无限占资源
    max_upload_mb: int                    # 上传体积上限（0 = 不限制，仅测试用）
    rerank_base_url: str | None
    mineru_mode: str                      # cli | http
    mineru_base_url: str | None
    mineru_cmd: list[str]
    asr_engine: str                       # faster-whisper | funasr
    asr_model: str
    pipelines: dict                       # 管道 DSL（02 文档 §一）
    apps: dict                            # 应用模板（02 文档 §三）
    prompts_dir: Path

    # ---- 派生路径 ----
    @property
    def db_path(self) -> Path: return self.data_dir / "ownrag.db"

    @property
    def files_dir(self) -> Path: return self.data_dir / "files"

    @property
    def parsed_dir(self) -> Path: return self.data_dir / "parsed"

    @property
    def chroma_dir(self) -> Path: return self.data_dir / "chroma"

    @property
    def known_kbs(self) -> set[str]:
        """知识库白名单：由 apps.yaml 的 knowledge_bases 声明推导。
        未声明的 kb 一律拒收——否则任意字符串都能落成孤立 Chroma collection。"""
        return {kb for app in self.apps.values() for kb in app.get("knowledge_bases", [])}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    env = os.environ.get
    config_dir = _resolve_config_dir()
    models = load_yaml(config_dir / "models.yaml")
    pipelines = load_yaml(config_dir / "pipelines.yaml").get("pipelines", {})
    apps = load_yaml(config_dir / "apps.yaml").get("apps", {})
    defaults = models.get("defaults", {})
    mineru = models.get("mineru", {})
    asr = models.get("asr", {})

    mineru_cmd = env("OWNRAG_MINERU_CMD") or mineru.get("cmd", "mineru")
    if isinstance(mineru_cmd, str):
        mineru_cmd = mineru_cmd.split()
    if not mineru_cmd:
        raise ValueError("MinerU CLI 命令为空：检查 OWNRAG_MINERU_CMD / configs/models.yaml")

    return Settings(
        # 数据目录默认跟随工作目录：装成 wheel 后包目录是只读镜像层，不能往里写
        data_dir=Path(env("OWNRAG_DATA_DIR", str(Path.cwd() / "data"))).resolve(),
        config_dir=config_dir,
        ollama_base_url=env("OLLAMA_BASE_URL", models.get("endpoints", {}).get("ollama", {}).get(
            "base_url", "http://127.0.0.1:11434")),
        chat_model=env("OWNRAG_CHAT_MODEL", defaults.get("chat", "qwen2.5:7b-instruct-q4_K_M")),
        embed_model=env("OWNRAG_EMBED_MODEL", defaults.get("embed", "bge-m3")),
        embed_version=env("OWNRAG_EMBED_VERSION", defaults.get("embed_version", "bge-m3@ollama")),
        num_ctx=int(env("OWNRAG_NUM_CTX", str(defaults.get("num_ctx", 6144)))),
        max_new_tokens=int(env("OWNRAG_MAX_NEW_TOKENS", str(defaults.get("max_new_tokens", 512)))),
        max_upload_mb=int(env("OWNRAG_MAX_UPLOAD_MB", str(defaults.get("max_upload_mb", 200)))),
        rerank_base_url=env("OWNRAG_RERANK_URL") or defaults.get("rerank_base_url") or None,
        mineru_mode=env("MINERU_MODE", mineru.get("mode", "cli")),
        mineru_base_url=env("MINERU_BASE_URL") or mineru.get("base_url") or None,
        mineru_cmd=mineru_cmd,
        asr_engine=env("OWNRAG_ASR_ENGINE", asr.get("engine", "faster-whisper")),
        asr_model=env("OWNRAG_ASR_MODEL", asr.get("model", "medium")),
        pipelines=pipelines,
        apps=apps,
        prompts_dir=config_dir / "prompts",
    )


def reset_settings_cache() -> None:
    """测试用：环境变量变更后重置缓存。"""
    get_settings.cache_clear()
