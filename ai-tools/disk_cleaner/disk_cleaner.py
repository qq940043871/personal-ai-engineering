#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disk_cleaner — Windows 磁盘空间分析与清理工具。

零第三方依赖，只使用 Python 标准库。
默认采用「先扫描、再确认」的安全策略：
  * clean 不加 --yes 时只展示计划并要求输入 yes 确认
  * 临时文件默认只删除 24 小时前的文件，避免误删正在使用的安装包
  * 不跟随符号链接 / junction，不触碰用户文档、下载、桌面等目录
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import os
import stat
import string
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

IS_WINDOWS = os.name == "nt"
HOME = os.path.expanduser("~")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))

DEFAULT_AGE_HOURS = 24
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


# ---------------------------------------------------------------------------
# 终端输出
# ---------------------------------------------------------------------------

_ANSI_ENABLED = False


def _enable_ansi() -> bool:
    """在 Windows 控制台上启用 ANSI 转义序列。"""
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _init_console() -> None:
    global _ANSI_ENABLED
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _ANSI_ENABLED = sys.stdout.isatty() and _enable_ansi()
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("磁盘清理工具")
        except Exception:
            pass


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI_ENABLED else text


def bold(text: str) -> str:
    return _paint(text, "1")


def dim(text: str) -> str:
    return _paint(text, "2")


def red(text: str) -> str:
    return _paint(text, "31")


def green(text: str) -> str:
    return _paint(text, "32")


def yellow(text: str) -> str:
    return _paint(text, "33")


def cyan(text: str) -> str:
    return _paint(text, "36")


def fmt_size(num: Optional[float]) -> str:
    if num is None:
        return "-"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def fmt_count(num: int) -> str:
    return f"{num:,}"


def _disp_width(text: str) -> int:
    """按终端显示宽度计算字符串长度（中文按 2 列）。"""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad(text: str, width: int, align: str = "left") -> str:
    padding = " " * max(0, width - _disp_width(text))
    return text + padding if align == "left" else padding + text


def _section(title: str) -> None:
    print()
    print(bold(cyan(f"── {title} " + "─" * max(0, 58 - len(title)))))


# ---------------------------------------------------------------------------
# 路径与文件遍历
# ---------------------------------------------------------------------------


def _long(path: str) -> str:
    """为超过 260 字符的路径加上 Windows 长路径前缀。"""
    if not IS_WINDOWS:
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if len(path) < 240:
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def _is_reparse(entry) -> bool:
    try:
        if isinstance(entry, os.DirEntry):
            st = entry.stat(follow_symlinks=False)
        else:
            st = os.stat(_long(entry), follow_symlinks=False)
    except OSError:
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _dedupe(paths: Iterable[Optional[str]]) -> List[str]:
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        path = os.path.normpath(os.path.expandvars(path))
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def walk_tree(root: str, on_error: Optional[Callable[[str, OSError], None]] = None):
    """深度优先遍历 root 下的所有条目。

    生成 (path, is_dir, size, mtime)；不进入符号链接或 junction。
    目录条目的 size/mtime 为 0。
    """
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(_long(current))
        except OSError as exc:
            if on_error:
                on_error(current, exc)
            continue
        with iterator:
            for entry in iterator:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if _is_reparse(entry):
                            continue
                        yield entry.path, True, 0, 0.0
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        yield entry.path, False, st.st_size, st.st_mtime
                except OSError as exc:
                    if on_error:
                        on_error(entry.path, exc)


def dir_size(root: str) -> int:
    total = 0
    for _, is_dir, size, _ in walk_tree(root):
        if not is_dir:
            total += size
    return total


class Progress:
    """在 TTY 上显示单行扫描进度，非 TTY 时保持安静。"""

    def __init__(self, label: str, enabled: Optional[bool] = None):
        self.label = label
        self.enabled = _ANSI_ENABLED if enabled is None else enabled
        self._last = 0.0
        self._width = 0
        self._shown = False

    def update(self, files: int, total_bytes: int) -> None:
        if not self.enabled:
            return
        now = time.time()
        if now - self._last < 0.15:
            return
        self._last = now
        text = f"{self.label}  {fmt_count(files)} 个文件 / {fmt_size(total_bytes)}"
        self._width = max(self._width, len(text))
        sys.stdout.write("\r" + text.ljust(self._width))
        sys.stdout.flush()
        self._shown = True

    def finish(self) -> None:
        if self._shown:
            sys.stdout.write("\r" + " " * self._width + "\r")
            sys.stdout.flush()
            self._shown = False


# ---------------------------------------------------------------------------
# 磁盘信息
# ---------------------------------------------------------------------------


def get_drives() -> List[str]:
    if not IS_WINDOWS:
        return ["/"]
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return ["C:\\"]
    drives = []
    for index in range(26):
        if mask & (1 << index):
            root = f"{string.ascii_uppercase[index]}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
            if drive_type in (2, 3):  # 可移动磁盘 / 固定磁盘
                drives.append(root)
    return drives or ["C:\\"]


def disk_usage(root: str) -> Optional[Tuple[int, int]]:
    """返回 (总字节, 可用字节)。"""
    if IS_WINDOWS:
        total = ctypes.c_ulonglong()
        free = ctypes.c_ulonglong()
        available = ctypes.c_ulonglong()
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(root),
            ctypes.byref(available),
            ctypes.byref(total),
            ctypes.byref(free),
        )
        if not ok:
            return None
        return total.value, available.value
    try:
        usage = os.statvfs(root)
        return usage.f_blocks * usage.f_frsize, usage.f_bavail * usage.f_frsize
    except OSError:
        return None


def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def system_drive() -> str:
    return os.environ.get("SystemDrive", "C:") + os.sep


def _usage_bar(used_ratio: float, width: int = 24) -> str:
    filled = int(round(max(0.0, min(1.0, used_ratio)) * width))
    return "█" * filled + "░" * (width - filled)


def print_drives() -> None:
    _section("磁盘概况")
    for root in get_drives():
        usage = disk_usage(root)
        if not usage:
            continue
        total, available = usage
        used = total - available
        ratio = used / total if total else 0
        percent = ratio * 100
        bar = _usage_bar(ratio)
        if available < 10 * 1024 ** 3:
            bar = red(bar)
            free_text = red(f"{fmt_size(available)} 可用")
        elif available < 20 * 1024 ** 3:
            bar = yellow(bar)
            free_text = yellow(f"{fmt_size(available)} 可用")
        else:
            bar = green(bar)
            free_text = green(f"{fmt_size(available)} 可用")
        print(
            f"  {bold(root)}  {bar}  {free_text} / {fmt_size(total)}"
            f"  {dim(f'(已用 {percent:.1f}%)')}"
        )


# ---------------------------------------------------------------------------
# 清理类别定义
# ---------------------------------------------------------------------------


def _temp_dirs() -> List[str]:
    return _dedupe(
        [
            os.environ.get("TEMP"),
            os.environ.get("TMP"),
            os.path.join(LOCALAPPDATA, "Temp"),
            os.path.join(r"C:\Windows", "Temp"),
        ]
    )


def _browser_cache_dirs() -> List[str]:
    user_data_roots = [
        os.path.join(LOCALAPPDATA, "Google", "Chrome", "User Data"),
        os.path.join(LOCALAPPDATA, "Microsoft", "Edge", "User Data"),
        os.path.join(LOCALAPPDATA, "BraveSoftware", "Brave-Browser", "User Data"),
        os.path.join(LOCALAPPDATA, "Chromium", "User Data"),
        os.path.join(LOCALAPPDATA, "Vivaldi", "User Data"),
        os.path.join(APPDATA, "Opera Software", "Opera Stable"),
    ]
    cache_subdirs = [
        ("Cache",),
        ("Code Cache",),
        ("GPUCache",),
        ("ShaderCache",),
        ("GrShaderCache",),
        ("DawnGraphiteCache",),
        ("DawnWebGPUCache",),
        ("Service Worker", "CacheStorage"),
        ("Service Worker", "ScriptCache"),
    ]
    found: List[str] = []
    for root in user_data_roots:
        if not os.path.isdir(root):
            continue
        try:
            names = os.listdir(root)
        except OSError:
            continue
        if os.path.basename(root) == "Opera Stable":
            profiles = [root]
        else:
            profiles = [
                os.path.join(root, name)
                for name in names
                if name == "Default"
                or name.startswith("Profile ")
                or name in ("Guest Profile", "System Profile")
            ]
        for profile in profiles:
            for parts in cache_subdirs:
                candidate = os.path.join(profile, *parts)
                if os.path.isdir(candidate):
                    found.append(candidate)

    firefox_profiles = os.path.join(LOCALAPPDATA, "Mozilla", "Firefox", "Profiles")
    if os.path.isdir(firefox_profiles):
        try:
            for name in os.listdir(firefox_profiles):
                cache = os.path.join(firefox_profiles, name, "cache2")
                if os.path.isdir(cache):
                    found.append(cache)
        except OSError:
            pass
    return _dedupe(found)


def _thumbnail_patterns() -> List[str]:
    explorer = os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "Explorer")
    return [
        os.path.join(explorer, "thumbcache_*.db"),
        os.path.join(explorer, "iconcache_*.db"),
    ]


def _windows_dirs() -> List[str]:
    return _dedupe(
        [
            os.path.join(r"C:\Windows", "SoftwareDistribution", "Download"),
            os.path.join(r"C:\Windows", "Temp"),
            os.path.join(r"C:\Windows", "Logs", "CBS"),
            os.path.join(r"C:\Windows", "LiveKernelReports"),
            os.path.join(r"C:\ProgramData", "Microsoft", "Windows", "WER", "ReportQueue"),
            os.path.join(r"C:\ProgramData", "Microsoft", "Windows", "WER", "ReportArchive"),
            os.path.join(r"C:\ProgramData", "Microsoft", "Windows", "WER", "Temp"),
            os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "WER"),
            os.path.join(
                r"C:\Windows",
                "ServiceProfiles",
                "NetworkService",
                "AppData",
                "Local",
                "Microsoft",
                "Windows",
                "DeliveryOptimization",
                "Cache",
            ),
        ]
    )


def _pkg_cache_dirs() -> List[str]:
    return _dedupe(
        [
            os.path.join(LOCALAPPDATA, "pip", "Cache"),
            os.path.join(LOCALAPPDATA, "npm-cache"),
            os.path.join(APPDATA, "npm-cache"),
            os.path.join(LOCALAPPDATA, "Yarn", "Cache"),
            os.path.join(LOCALAPPDATA, "Yarn", "Berry", "cache"),
            os.path.join(LOCALAPPDATA, "pnpm", "store"),
            os.path.join(LOCALAPPDATA, "pnpm-cache"),
            os.path.join(LOCALAPPDATA, "uv", "cache"),
            os.path.join(LOCALAPPDATA, "bun", "install", "cache"),
        ]
    )


def _conda_pkg_dirs() -> List[str]:
    candidates = [
        os.path.join(HOME, "anaconda3", "pkgs"),
        os.path.join(HOME, "miniconda3", "pkgs"),
        os.path.join(HOME, "Anaconda3", "pkgs"),
        os.path.join(LOCALAPPDATA, "anaconda3", "pkgs"),
        os.path.join(LOCALAPPDATA, "miniconda3", "pkgs"),
    ]
    return _dedupe([path for path in candidates if os.path.isdir(path)])


def _dev_cache_dirs() -> List[str]:
    cache_root = os.path.join(HOME, ".cache")
    names = ("puppeteer", "codex-runtimes", "selenium", "chroma", "whisper", "torch", "playwright")
    paths = [os.path.join(cache_root, name) for name in names]
    paths.append(os.path.join(LOCALAPPDATA, "ms-playwright"))
    return _dedupe(paths)


def _model_cache_dirs() -> List[str]:
    cache_root = os.path.join(HOME, ".cache")
    return _dedupe(
        [os.path.join(cache_root, name) for name in ("huggingface", "modelscope")]
    )


def _maven_repo() -> List[str]:
    return _dedupe([os.path.join(HOME, ".m2", "repository")])


def _recycle_size() -> int:
    total = 0
    for root in get_drives():
        bin_root = os.path.join(root, "$Recycle.Bin")
        if not os.path.isdir(bin_root):
            continue
        try:
            total += dir_size(bin_root)
        except Exception:
            continue
    return total


def _clean_recycle(dry_run: bool, stats: "CleanStats") -> None:
    stats.deleted_bytes = _recycle_size()
    stats.deleted_files = 0
    if dry_run or stats.deleted_bytes == 0:
        return
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Clear-RecycleBin -Force -ErrorAction SilentlyContinue",
            ],
            capture_output=True,
            timeout=180,
        )
        if result.returncode == 0:
            stats.deleted_files = 1  # 具体文件数由系统清理
        else:
            stats.deleted_bytes = 0
            stats.failed += 1
    except Exception:
        stats.deleted_bytes = 0
        stats.failed += 1


@dataclass
class Category:
    key: str
    title: str
    desc: str
    targets: Callable[[], List[str]]
    default: bool = True
    age_hours: int = 0
    kind: str = "contents"  # contents | files | command
    admin: bool = False
    warning: str = ""

    @property
    def age_filtered(self) -> bool:
        return self.age_hours > 0


CATEGORIES: List[Category] = [
    Category(
        key="temp",
        title="临时文件",
        desc="用户/系统临时文件（默认只删 24 小时前的）",
        targets=_temp_dirs,
        age_hours=DEFAULT_AGE_HOURS,
    ),
    Category(
        key="browser",
        title="浏览器缓存",
        desc="Chrome/Edge/Firefox 等缓存（不含书签、密码、历史）",
        targets=_browser_cache_dirs,
    ),
    Category(
        key="thumbnails",
        title="缩略图缓存",
        desc="资源管理器缩略图/图标缓存（占用时可能删不掉）",
        targets=_thumbnail_patterns,
        kind="files",
    ),
    Category(
        key="windows",
        title="Windows 系统垃圾",
        desc="更新下载缓存、错误报告、CBS 日志",
        targets=_windows_dirs,
        age_hours=DEFAULT_AGE_HOURS,
        admin=True,
    ),
    Category(
        key="pkg",
        title="开发包缓存",
        desc="pip/npm/yarn/pnpm/uv 下载缓存（可自动重新下载）",
        targets=_pkg_cache_dirs,
    ),
    Category(
        key="devcache",
        title="开发工具缓存",
        desc="puppeteer/playwright 浏览器、Whisper/Torch 模型等",
        targets=_dev_cache_dirs,
        default=False,
        warning="删除后下次使用需重新下载，可能较慢",
    ),
    Category(
        key="models",
        title="AI 模型缓存",
        desc="HuggingFace / ModelScope 已下载模型",
        targets=_model_cache_dirs,
        default=False,
        warning="删除后需重新下载模型，离线环境慎用",
    ),
    Category(
        key="conda",
        title="conda 包缓存",
        desc="anaconda/miniconda 的 pkgs 包缓存",
        targets=_conda_pkg_dirs,
        default=False,
        warning="已安装环境不受影响，但新建环境需重新下载",
    ),
    Category(
        key="maven",
        title="Maven 本地仓库",
        desc="~/.m2/repository 依赖仓库",
        targets=_maven_repo,
        default=False,
        warning="私有/离线依赖可能无法重新下载，请谨慎",
    ),
    Category(
        key="recycle",
        title="回收站",
        desc="清空所有磁盘的回收站（不可恢复）",
        targets=lambda: [],
        default=False,
        kind="command",
        warning="不可恢复，请确认没有待还原的文件",
    ),
]

CATEGORY_MAP: Dict[str, Category] = {category.key: category for category in CATEGORIES}


# ---------------------------------------------------------------------------
# 测量与清理
# ---------------------------------------------------------------------------


@dataclass
class SizeInfo:
    total_bytes: int = 0
    total_files: int = 0
    deletable_bytes: int = 0
    deletable_files: int = 0


@dataclass
class CleanStats:
    deleted_bytes: int = 0
    deleted_files: int = 0
    removed_dirs: int = 0
    skipped_files: int = 0
    failed: int = 0


def _cutoff(age_hours: int) -> Optional[float]:
    if age_hours <= 0:
        return None
    return time.time() - age_hours * 3600


def measure_paths(
    paths: Sequence[str],
    kind: str = "contents",
    age_hours: int = 0,
) -> SizeInfo:
    cutoff = _cutoff(age_hours)
    info = SizeInfo()
    for path in paths:
        if kind == "files":
            matched = glob.glob(path)
            for file_path in matched:
                try:
                    st = os.stat(_long(file_path), follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    info.total_bytes += st.st_size
                    info.total_files += 1
                    if cutoff is None or st.st_mtime < cutoff:
                        info.deletable_bytes += st.st_size
                        info.deletable_files += 1
                except OSError:
                    continue
            continue

        if not os.path.isdir(path):
            continue
        progress = Progress(f"扫描 {path}")
        for _, is_dir, size, mtime in walk_tree(path):
            if is_dir:
                continue
            info.total_bytes += size
            info.total_files += 1
            if cutoff is None or mtime < cutoff:
                info.deletable_bytes += size
                info.deletable_files += 1
            if info.total_files % 2048 == 0:
                progress.update(info.total_files, info.total_bytes)
        progress.finish()
    return info


def measure_category(category: Category, age_override: Optional[int] = None) -> SizeInfo:
    if category.kind == "command":
        size = _recycle_size()
        return SizeInfo(total_bytes=size, total_files=0, deletable_bytes=size, deletable_files=0)
    age_hours = category.age_hours
    if age_override is not None and age_hours > 0:
        age_hours = age_override
    return measure_paths(category.targets(), category.kind, age_hours)


def _remove_file(path: str) -> None:
    try:
        os.remove(_long(path))
    except PermissionError:
        os.chmod(_long(path), stat.S_IWRITE)
        os.remove(_long(path))


def _clean_tree(
    root: str,
    cutoff: Optional[float],
    dry_run: bool,
    stats: CleanStats,
    is_root: bool = True,
) -> None:
    try:
        entries = list(os.scandir(_long(root)))
    except OSError:
        stats.failed += 1
        return

    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                if _is_reparse(entry):
                    stats.skipped_files += 1
                    continue
                _clean_tree(entry.path, cutoff, dry_run, stats, is_root=False)
            elif entry.is_file(follow_symlinks=False):
                st = entry.stat(follow_symlinks=False)
                if cutoff is not None and st.st_mtime >= cutoff:
                    stats.skipped_files += 1
                    continue
                if dry_run:
                    stats.deleted_bytes += st.st_size
                    stats.deleted_files += 1
                else:
                    _remove_file(entry.path)
                    stats.deleted_bytes += st.st_size
                    stats.deleted_files += 1
        except OSError:
            stats.failed += 1

    if not is_root and not dry_run:
        try:
            os.rmdir(_long(root))
            stats.removed_dirs += 1
        except OSError:
            pass


def clean_category(
    category: Category,
    age_override: Optional[int],
    dry_run: bool,
) -> CleanStats:
    stats = CleanStats()
    if category.kind == "command":
        _clean_recycle(dry_run, stats)
        return stats

    age_hours = category.age_hours
    if age_override is not None and age_hours > 0:
        age_hours = age_override
    cutoff = _cutoff(age_hours)

    for target in category.targets():
        if category.kind == "files":
            for file_path in glob.glob(target):
                try:
                    st = os.stat(_long(file_path), follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    if cutoff is not None and st.st_mtime >= cutoff:
                        stats.skipped_files += 1
                        continue
                    if dry_run:
                        stats.deleted_bytes += st.st_size
                        stats.deleted_files += 1
                    else:
                        _remove_file(file_path)
                        stats.deleted_bytes += st.st_size
                        stats.deleted_files += 1
                except OSError:
                    stats.failed += 1
        else:
            if not os.path.isdir(target):
                continue
            _clean_tree(target, cutoff, dry_run, stats)
    return stats


# ---------------------------------------------------------------------------
# 目录 / 大文件分析
# ---------------------------------------------------------------------------


def aggregate_tree(root: str) -> Tuple[Dict[Tuple[str, ...], int], set]:
    """一次性遍历，返回各级相对路径的累计大小与目录集合。"""
    totals: Dict[Tuple[str, ...], int] = {}
    directories = set()
    progress = Progress(f"分析 {root}")
    file_count = 0
    total_bytes = 0
    for path, is_dir, size, _ in walk_tree(root):
        if is_dir:
            rel = os.path.relpath(path, root)
            parts = tuple(rel.split(os.sep))
            directories.add(parts)
            continue
        rel = os.path.relpath(path, root)
        parts = tuple(rel.split(os.sep))
        for index in range(1, len(parts) + 1):
            key = parts[:index]
            totals[key] = totals.get(key, 0) + size
        total_bytes += size
        file_count += 1
        if file_count % 2048 == 0:
            progress.update(file_count, total_bytes)
    progress.finish()
    return totals, directories


def _print_tree(
    root: str,
    totals: Dict[Tuple[str, ...], int],
    directories: set,
    depth: int,
    top: int,
    include_files: bool,
    parent: Tuple[str, ...] = (),
    level: int = 1,
) -> None:
    children = [
        key
        for key in totals
        if len(key) == len(parent) + 1 and key[:-1] == parent
    ]
    children.sort(key=lambda key: totals[key], reverse=True)
    shown = 0
    for key in children:
        is_dir = key in directories
        if not is_dir and not include_files and level > 1:
            continue
        if shown >= top:
            remaining = len(children) - shown
            if remaining > 0:
                print("  " * level + dim(f"… 其余 {remaining} 项省略"))
            break
        name = key[-1]
        suffix = os.sep if is_dir else ""
        size_cell = _pad(fmt_size(totals[key]), 12, "right")
        indent = "  " * level
        if totals[key] >= 10 * 1024 ** 3:
            size_cell = yellow(size_cell)
        print(f"{indent}{size_cell}  {name}{suffix}")
        if is_dir and level < depth:
            _print_tree(root, totals, directories, depth, top, include_files, key, level + 1)
        shown += 1


def cmd_du(args: argparse.Namespace) -> int:
    root = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(root):
        print(red(f"目录不存在: {root}"))
        return 1
    totals, directories = aggregate_tree(root)
    total = sum(size for key, size in totals.items() if len(key) == 1)
    _section(f"目录占用  {root}")
    print(f"  总计: {bold(fmt_size(total))}")
    print()
    _print_tree(root, totals, directories, max(1, args.depth), max(1, args.top), args.files)
    return 0


def cmd_large(args: argparse.Namespace) -> int:
    root = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(root):
        print(red(f"目录不存在: {root}"))
        return 1
    min_bytes = max(0, args.min_mb) * 1024 * 1024
    cutoff = None
    if args.older_than > 0:
        cutoff = time.time() - args.older_than * 86400

    results: List[Tuple[int, float, str]] = []
    progress = Progress(f"扫描 {root}")
    scanned = 0
    for path, is_dir, size, mtime in walk_tree(root):
        if is_dir:
            continue
        scanned += 1
        if size >= min_bytes and (cutoff is None or mtime < cutoff):
            results.append((size, mtime, path))
        if scanned % 4096 == 0:
            progress.update(scanned, 0)
    progress.finish()

    results.sort(key=lambda item: item[0], reverse=True)
    _section(f"大文件  {root}  (≥ {args.min_mb} MB)")
    if not results:
        print("  没有符合条件的文件。")
        return 0
    total = sum(item[0] for item in results)
    now = time.time()
    print(f"  共 {len(results)} 个文件，合计 {bold(fmt_size(total))}")
    print()
    for size, mtime, path in results[: max(1, args.top)]:
        age_days = int((now - mtime) / 86400)
        try:
            shown = os.path.relpath(path, root)
        except ValueError:
            shown = path
        print(f"  {fmt_size(size):>10}  {age_days:>4} 天前  {shown}")
    if len(results) > args.top:
        print(dim(f"  … 其余 {len(results) - args.top} 个文件省略，可调大 --top"))
    return 0


# ---------------------------------------------------------------------------
# 应用目录盘点
# ---------------------------------------------------------------------------


APP_ROOTS = [
    ("UserPrograms", os.path.join(LOCALAPPDATA, "Programs")),
    ("ProgramFiles", os.environ.get("ProgramFiles", r"C:\Program Files")),
    ("ProgramFilesX86", os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ("ProgramData", r"C:\ProgramData"),
    ("LocalAppData", LOCALAPPDATA),
    ("RoamingAppData", APPDATA),
]

# 系统目录/缓存目录不作为“应用”展示，避免干扰判断
APP_SKIP = {
    "UserPrograms": set(),
    "ProgramFiles": {"windowsapps", "common files", "modifiablewindowsapps", "windowspowershell"},
    "ProgramFilesX86": {"windowsapps", "common files", "modifiablewindowsapps"},
    "ProgramData": {"microsoft", "packages", "usoshared"},
    "LocalAppData": {
        "microsoft",
        "packages",
        "temp",
        "programs",
        "pip",
        "npm-cache",
        "yarn",
        "pnpm",
        "uv",
        "ms-playwright",
        "crashdumps",
        "d3dscache",
        "connecteddevicesplatform",
        "comms",
        "elevateddiagnostics",
        "placeholdertilelogofolder",
        "publishers",
        "virtualstore",
        "winboplugins",
        "windowsapps",
        "wsl",
    },
    "RoamingAppData": {"microsoft"},
}

USER_PROFILE_SKIP = {
    "appdata",
    "documents",
    "downloads",
    "desktop",
    "pictures",
    "music",
    "videos",
    "onedrive",
    "contacts",
    "favorites",
    "links",
    "saved games",
    "searches",
    "3d objects",
    "ntuser.dat",
}


@dataclass
class AppInfo:
    label: str
    name: str
    path: str
    bytes: int = 0
    files: int = 0
    binaries: int = 0
    last_mtime: float = 0.0


def _list_child_dirs(root: str):
    try:
        iterator = os.scandir(_long(root))
    except OSError:
        return
    with iterator:
        for entry in iterator:
            try:
                if entry.is_dir(follow_symlinks=False) and not _is_reparse(entry):
                    yield entry
            except OSError:
                continue


def _iter_app_dirs():
    for label, root in APP_ROOTS:
        if not root or not os.path.isdir(root):
            continue
        skip = APP_SKIP.get(label, set())
        for entry in _list_child_dirs(root):
            if entry.name.lower() in skip:
                continue
            yield label, entry.name, entry.path

    for entry in _list_child_dirs(HOME):
        if entry.name.lower() in USER_PROFILE_SKIP:
            continue
        yield "UserProfile", entry.name, entry.path


def _measure_app(label: str, name: str, path: str) -> AppInfo:
    info = AppInfo(label=label, name=name, path=path)
    try:
        info.last_mtime = os.stat(_long(path), follow_symlinks=False).st_mtime
    except OSError:
        pass
    for file_path, is_dir, size, mtime in walk_tree(path):
        if is_dir:
            continue
        info.bytes += size
        info.files += 1
        if mtime > info.last_mtime:
            info.last_mtime = mtime
        lowered = file_path.lower()
        if lowered.endswith((".exe", ".msi", ".dll")):
            info.binaries += 1
    return info


def cmd_apps(args: argparse.Namespace) -> int:
    now = time.time()
    stale_seconds = max(1, args.stale_days) * 86400
    min_bytes = max(0, args.min_mb) * 1024 * 1024

    results: List[AppInfo] = []
    progress = Progress("扫描应用目录")
    total_files = 0
    total_bytes = 0
    for label, name, path in _iter_app_dirs():
        info = _measure_app(label, name, path)
        total_files += info.files
        total_bytes += info.bytes
        progress.update(total_files, total_bytes)
        if info.bytes >= min_bytes:
            results.append(info)
    progress.finish()

    results.sort(key=lambda item: item.bytes, reverse=True)

    _section(f"应用目录盘点（≥ {args.min_mb} MB，按大小排序）")
    print(dim("  位置缩写:"))
    for label, root in APP_ROOTS:
        if root:
            print(dim(f"    {label} = {root}"))
    print(dim(f"    UserProfile = {HOME}"))
    print()
    header = (
        "  "
        + _pad("大小", 10, "right")
        + "  "
        + _pad("最近活动", 10)
        + "  "
        + "位置"
    )
    print(bold(header))
    print(dim("  " + "-" * 88))

    for info in results[: max(1, args.top)]:
        age_days = int((now - info.last_mtime) / 86400) if info.last_mtime else -1
        if age_days < 0:
            age_text = "未知"
        elif age_days == 0:
            age_text = "今天"
        else:
            age_text = f"{age_days} 天前"
        if age_days >= 365:
            age_text = red(_pad(age_text, 10))
        elif age_days * 86400 >= stale_seconds:
            age_text = yellow(_pad(age_text, 10))
        else:
            age_text = _pad(age_text, 10)

        flags = []
        if info.last_mtime and now - info.last_mtime >= stale_seconds:
            flags.append("闲置")
        if info.bytes == 0:
            flags.append("空目录")
        elif info.bytes < 10 * 1024 * 1024 and info.binaries == 0:
            flags.append("可能残留")
        flag_text = "  " + yellow("[" + " / ".join(flags) + "]") if flags else ""

        size_cell = _pad(fmt_size(info.bytes), 10, "right")
        if info.bytes >= 1024 ** 3:
            size_cell = yellow(size_cell)
        location = f"{info.label}\\{info.name}"
        print(f"  {size_cell}  {age_text}  {location}{flag_text}")

    if len(results) > args.top:
        print(dim(f"  … 其余 {len(results) - args.top} 个目录省略，可调大 --top"))

    print()
    print(f"  共扫描 {fmt_count(len(results))} 个目录，合计 {bold(fmt_size(total_bytes))}")
    print(
        dim(
            "  说明: “最近活动”取目录内最新文件修改时间，后台自动更新可能让闲置应用显得较新；\n"
            "        卸载请优先使用系统“应用和功能”或应用自带卸载器，直接删目录可能残留服务/注册表项。"
        )
    )
    return 0


# ---------------------------------------------------------------------------
# scan / clean 命令
# ---------------------------------------------------------------------------


def _select_categories(names: Sequence[str], all_flag: bool) -> List[Category]:
    if all_flag:
        return list(CATEGORIES)
    if not names:
        return [category for category in CATEGORIES if category.default]
    selected = []
    for name in names:
        key = name.strip().lower()
        if key == "all":
            return list(CATEGORIES)
        if key not in CATEGORY_MAP:
            raise SystemExit(
                f"未知类别: {name}\n可用类别: {', '.join(CATEGORY_MAP)}"
            )
        selected.append(CATEGORY_MAP[key])
    return selected


def _scan_categories(
    categories: Sequence[Category],
    age_override: Optional[int],
) -> List[Tuple[Category, SizeInfo]]:
    rows = []
    for category in categories:
        info = measure_category(category, age_override)
        rows.append((category, info))
    return rows


def _run_scan(
    deep: bool = False,
    path: str = HOME,
    top: int = 15,
    min_mb: int = 200,
    min_age_hours: Optional[int] = None,
) -> List[Tuple[Category, SizeInfo]]:
    print_drives()

    rows = _scan_categories(CATEGORIES, min_age_hours)
    rows.sort(key=lambda row: row[1].deletable_bytes, reverse=True)

    _section("可清理项")
    header = (
        "  "
        + _pad("#", 3)
        + _pad("类别", 16)
        + _pad("可清理", 10, "right")
        + _pad("总计", 10, "right")
        + "  说明"
    )
    print(bold(header))
    print(dim("  " + "-" * 76))
    default_total = 0
    for index, (category, info) in enumerate(rows, start=1):
        note = category.desc
        if category.warning:
            note += f" — {category.warning}"
        if category.admin and not is_admin():
            note += "（部分需管理员）"
        if category.age_filtered:
            hours = (
                min_age_hours
                if min_age_hours is not None
                else category.age_hours
            )
            note += " [全部]" if hours <= 0 else f" [{hours}h+]"
        size_cell = _pad(fmt_size(info.deletable_bytes), 10, "right")
        if info.deletable_bytes >= 1024 ** 3:
            size_cell = yellow(size_cell)
        print(
            "  "
            + _pad(str(index), 3)
            + _pad(category.title, 16)
            + size_cell
            + _pad(fmt_size(info.total_bytes), 10, "right")
            + "  "
            + dim(note)
        )
        if category.default:
            default_total += info.deletable_bytes

    print()
    print(f"  默认清理项合计: {bold(green(fmt_size(default_total)))}")
    if not is_admin():
        print(dim("  提示: 当前不是管理员，Windows 系统目录中的部分文件会被跳过。"))

    windows_old = r"C:\Windows.old"
    if os.path.isdir(windows_old):
        print(
            yellow(
                f"  发现 {windows_old}（{fmt_size(dir_size(windows_old))}），"
                "建议用系统「磁盘清理」删除。"
            )
        )

    if deep:
        root = os.path.abspath(os.path.expanduser(path or HOME))
        _section(f"目录占用 TOP {top}  {root}")
        totals, directories = aggregate_tree(root)
        _print_tree(root, totals, directories, 1, top, include_files=False)
        print()
        print(dim(f"  查看更深层级: python disk_cleaner.py du \"{root}\" --depth 2"))
        large_args = argparse.Namespace(
            path=root, min_mb=min_mb, top=top, older_than=0
        )
        cmd_large(large_args)

    _section("下一步")
    print("  预览默认清理:  python disk_cleaner.py clean --dry-run")
    print("  执行默认清理:  python disk_cleaner.py clean --yes")
    print("  指定类别:      python disk_cleaner.py clean temp pkg --yes")
    print("  查看全部类别:  python disk_cleaner.py clean --all --dry-run")
    return rows


def cmd_scan(args: argparse.Namespace) -> int:
    _run_scan(
        deep=args.deep,
        path=args.path,
        top=args.top,
        min_mb=args.min_mb,
        min_age_hours=args.min_age_hours,
    )
    return 0


def _print_plan(rows: Sequence[Tuple[Category, SizeInfo]], dry_run: bool) -> int:
    _section("清理计划" + ("（预览，不会删除）" if dry_run else ""))
    total = 0
    for category, info in rows:
        size = info.deletable_bytes
        total += size
        note = f"  {dim(category.warning)}" if category.warning else ""
        print(
            "  "
            + _pad(category.title, 16)
            + _pad(fmt_size(size), 10, "right")
            + "  "
            + category.desc
            + note
        )
    print()
    print(f"  合计: {bold(green(fmt_size(total)))}")
    return total


def cmd_clean(args: argparse.Namespace) -> int:
    try:
        categories = _select_categories(args.categories, args.all)
    except SystemExit as exc:
        print(red(str(exc)))
        return 1

    age_override = args.min_age_hours
    rows: List[Tuple[Category, SizeInfo]] = []
    print(bold("正在统计可清理内容…"))
    for category in categories:
        info = measure_category(category, age_override)
        rows.append((category, info))

    rows = [row for row in rows if row[1].deletable_bytes > 0 or row[0].kind == "command"]
    if not rows:
        print(green("没有可清理的内容。"))
        return 0

    total = _print_plan(rows, args.dry_run)
    if args.dry_run:
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print(red("非交互环境请加 --yes 确认执行。"))
            return 1
        print()
        answer = input(f"确认删除以上内容并释放约 {fmt_size(total)}？输入 yes 继续: ").strip()
        if answer.lower() not in ("yes", "y"):
            print("已取消。")
            return 0

    free_before = None
    usage = disk_usage(system_drive())
    if usage:
        free_before = usage[1]

    total_stats = CleanStats()
    print()
    for category, info in rows:
        print(bold(f"清理 {category.title} …"))
        stats = clean_category(category, age_override, dry_run=False)
        total_stats.deleted_bytes += stats.deleted_bytes
        total_stats.deleted_files += stats.deleted_files
        total_stats.removed_dirs += stats.removed_dirs
        total_stats.skipped_files += stats.skipped_files
        total_stats.failed += stats.failed

        parts = [f"删除 {green(fmt_size(stats.deleted_bytes))}"]
        if stats.deleted_files:
            parts.append(f"{fmt_count(stats.deleted_files)} 个文件")
        if stats.skipped_files:
            parts.append(dim(f"跳过 {fmt_count(stats.skipped_files)} 个（锁定/未到期/链接）"))
        if stats.failed:
            parts.append(yellow(f"失败 {fmt_count(stats.failed)} 个（可能被占用或权限不足）"))
        print("  " + "，".join(parts))

    _section("清理结果")
    print(f"  删除数据: {bold(green(fmt_size(total_stats.deleted_bytes)))}（按文件逻辑大小）")
    if total_stats.deleted_files:
        print(f"  删除文件: {fmt_count(total_stats.deleted_files)}")
    if total_stats.removed_dirs:
        print(f"  删除目录: {fmt_count(total_stats.removed_dirs)}")
    if total_stats.failed:
        print(yellow(f"  失败条目: {fmt_count(total_stats.failed)}（关闭相关程序或管理员重试）"))

    usage_after = disk_usage(system_drive())
    if free_before is not None and usage_after:
        delta = usage_after[1] - free_before
        print(f"  系统盘可用空间: {fmt_size(free_before)} → {bold(fmt_size(usage_after[1]))}"
              f"  ({green('+' + fmt_size(delta)) if delta > 0 else dim(fmt_size(delta))})")
    return 0


# ---------------------------------------------------------------------------
# 交互模式
# ---------------------------------------------------------------------------


def cmd_interactive() -> int:
    rows = _run_scan()
    print()
    if not sys.stdin.isatty():
        return 0
    raw = input("输入要清理的编号（逗号分隔，回车退出）: ").strip()
    if not raw:
        return 0
    ordered = sorted(rows, key=lambda row: row[1].deletable_bytes, reverse=True)
    chosen: List[Category] = []
    for token in raw.replace("，", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit() or not (1 <= int(token) <= len(ordered)):
            print(red(f"无效编号: {token}"))
            return 1
        chosen.append(ordered[int(token) - 1][0])

    plan_rows = [(category, measure_category(category, None)) for category in chosen]
    _print_plan(plan_rows, dry_run=False)
    answer = input("确认清理？输入 yes 继续: ").strip().lower()
    if answer not in ("yes", "y"):
        print("已取消。")
        return 0

    total_stats = CleanStats()
    for category, _ in plan_rows:
        print(bold(f"清理 {category.title} …"))
        stats = clean_category(category, None, dry_run=False)
        total_stats.deleted_bytes += stats.deleted_bytes
        total_stats.deleted_files += stats.deleted_files
        total_stats.failed += stats.failed
        print(f"  释放 {green(fmt_size(stats.deleted_bytes))}")
    print()
    print(f"共释放 {bold(green(fmt_size(total_stats.deleted_bytes)))}")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="disk_cleaner.py",
        description="Windows 磁盘空间分析与安全清理工具（零第三方依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python disk_cleaner.py                       # 交互模式\n"
            "  python disk_cleaner.py scan --deep           # 扫描 + 目录/大文件分析\n"
            "  python disk_cleaner.py clean --dry-run       # 预览默认清理项\n"
            "  python disk_cleaner.py clean --yes           # 执行默认清理\n"
            "  python disk_cleaner.py clean pkg temp --yes  # 只清理指定类别\n"
            "  python disk_cleaner.py du C:\\Users --depth 2\n"
            "  python disk_cleaner.py large D:\\ --min-mb 500 --older-than 90\n"
            "  python disk_cleaner.py apps --min-mb 50 --stale-days 90\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="扫描磁盘与可清理项")
    scan_parser.add_argument("--deep", action="store_true", help="同时分析大目录和大文件")
    scan_parser.add_argument("--path", default=HOME, help="深度分析的目录（默认用户目录）")
    scan_parser.add_argument("--top", type=int, default=15, help="显示前 N 项（默认 15）")
    scan_parser.add_argument("--min-mb", type=int, default=200, help="大文件阈值 MB（默认 200）")
    scan_parser.add_argument("--min-age-hours", type=int, default=None, help="临时文件保留时长")
    scan_parser.set_defaults(func=cmd_scan)

    clean_parser = sub.add_parser("clean", help="清理指定类别")
    clean_parser.add_argument("categories", nargs="*", help="类别名，留空使用默认类别")
    clean_parser.add_argument("--all", action="store_true", help="包含全部类别（含回收站、Maven 等）")
    clean_parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    clean_parser.add_argument("--dry-run", "-n", action="store_true", help="只预览不删除")
    clean_parser.add_argument(
        "--min-age-hours",
        type=int,
        default=None,
        help="覆盖临时文件的保留时长（0 表示全部删除）",
    )
    clean_parser.set_defaults(func=cmd_clean)

    du_parser = sub.add_parser("du", help="查看目录占用")
    du_parser.add_argument("path", nargs="?", default=HOME, help="目标目录")
    du_parser.add_argument("--depth", type=int, default=1, help="展开层级（默认 1）")
    du_parser.add_argument("--top", type=int, default=15, help="每层显示前 N 项")
    du_parser.add_argument("--files", action="store_true", help="同时显示文件")
    du_parser.set_defaults(func=cmd_du)

    large_parser = sub.add_parser("large", help="查找大文件")
    large_parser.add_argument("path", nargs="?", default=HOME, help="目标目录")
    large_parser.add_argument("--min-mb", type=int, default=100, help="最小文件大小 MB")
    large_parser.add_argument("--top", type=int, default=30, help="显示前 N 个")
    large_parser.add_argument("--older-than", type=int, default=0, help="只看 N 天前的文件")
    large_parser.set_defaults(func=cmd_large)

    apps_parser = sub.add_parser("apps", help="盘点应用目录大小与最近活动")
    apps_parser.add_argument("--min-mb", type=int, default=10, help="最小目录大小 MB")
    apps_parser.add_argument("--stale-days", type=int, default=90, help="超过 N 天未改动标记为闲置")
    apps_parser.add_argument("--top", type=int, default=40, help="显示前 N 项")
    apps_parser.set_defaults(func=cmd_apps)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _init_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return cmd_interactive()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        raise SystemExit(130)
    except BrokenPipeError:
        raise SystemExit(0)
