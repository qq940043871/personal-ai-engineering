# -*- coding: utf-8 -*-
"""绕过 browser_cookie3，直接读 Edge/Chrome 的 cookie 并尝试解密。

browser_cookie3 在老版本 Chrome/Edge 上够用，但遇到 App-Bound Encryption（ABE）
就会抛 RequiresAdminError。这里自己走一遍，碰运气试几种已知的解密路线。

路线（按可行性排序）：
  R1. 用 Local State 里的 encrypted_key + DPAPI 解主密钥，再用 AES-GCM 解 v10 cookie
  R2. 若 cookie 仍是 v10 且密文能用主密钥解开 → 成功
  R3. 若 browser_cookie3 能读（低版本浏览器）→ 直接用它
  R4. 全部失败 → 明确告诉用户走手动 cookie
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt(blob: bytes) -> bytes:
    """调用 Windows DPAPI CryptUnprotectData 解密。"""
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob),
                                               ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                      0, ctypes.byref(blob_out)):
        raise OSError(f"CryptUnprotectData 失败, GetLastError={kernel32.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def profile_dir(browser: str) -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    if browser == "edge":
        return os.path.join(local, "Microsoft", "Edge", "User Data")
    if browser == "chrome":
        return os.path.join(local, "Google", "Chrome", "User Data")
    if browser == "brave":
        return os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")
    return ""


def list_profiles(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        cand = os.path.join(root, name)
        if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "Network", "Cookies")):
            out.append(name)
    return out


def read_key_from_localstate(root: str) -> bytes:
    ls = os.path.join(root, "Local State")
    with open(ls, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    enc = data.get("os_crypt", {}).get("encrypted_key")
    if not enc:
        raise RuntimeError("Local State 里没有 os_crypt.encrypted_key")
    raw = base64.b64decode(enc)
    if raw[:5] == b"DPAPI":
        raw = raw[5:]
    return dpapi_decrypt(raw)


def try_decrypt_v10(cipher: bytes, key: bytes) -> str | None:
    """v10 = b'v10' + 12B nonce + 密文 + 16B tag。"""
    if len(cipher) < 15 or cipher[:3] != b"v10":
        return None
    nonce, payload = cipher[3:15], cipher[15:]
    if len(payload) < 16:
        return None
    body, tag = payload[:-16], payload[-16:]
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    try:
        return AESGCM(key).decrypt(nonce, body + tag, None).decode("utf-8", "replace")
    except Exception:
        return None


def _copy_locked(src: str, dst: str) -> bool:
    """复制被占用的文件。

    优先用 Windows 卷影备份 API（FILE_FLAG_BACKUP_SEMANTICS + 共享读），
    这是备份软件的标准做法，能在浏览器运行时安全读取 SQLite。
    """
    # 路线 1：普通复制
    try:
        shutil.copy2(src, dst)
        return True
    except Exception:
        pass

    # 路线 2：CreateFileW 带共享标志，以备份语义打开
    try:
        GENERIC_READ = 0x80000000
        FILE_SHARE_ALL = 0x00000007  # READ | WRITE | DELETE
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(
            src, GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS, None)
        if handle == -1 or handle is None or handle == 0xFFFFFFFFFFFFFFFF:
            return False
        try:
            buf = ctypes.create_string_buffer(1024 * 1024)
            read = wintypes.DWORD(0)
            with open(dst, "wb") as out:
                while True:
                    ok = kernel32.ReadFile(handle, buf, len(buf),
                                           ctypes.byref(read), None)
                    if not ok or read.value == 0:
                        break
                    out.write(buf.raw[:read.value])
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def dump_cookies(browser: str, profile: str = "Default"):
    root = profile_dir(browser)
    print(f"\n{'='*64}\n[{browser}] {root}")
    if not os.path.isdir(root):
        print("  该浏览器未安装（User Data 目录不存在）")
        return {}

    try:
        key = read_key_from_localstate(root)
        print(f"  主密钥解密: OK（{len(key)} 字节）")
    except Exception as exc:
        print(f"  主密钥解密失败: {type(exc).__name__}: {exc}")
        key = None

    ck = os.path.join(root, profile, "Network", "Cookies")
    if not os.path.exists(ck):
        print(f"  profile {profile} 下没有 Cookies 文件")
        return {}

    # 浏览器通常正跑着，会锁住 Cookies 文件。
    # 用备份 API 或共享读方式绕过锁，最差退回普通复制。
    tmp = os.path.join(tempfile.mkdtemp(), "Cookies")
    if not _copy_locked(ck, tmp):
        print(f"  无法复制 Cookies 文件（被占用且无权限绕过）")
        return {}
    con = sqlite3.connect(tmp)
    rows = con.execute(
        "SELECT host_key,name,encrypted_value,value FROM cookies WHERE host_key LIKE '%weread%'"
    ).fetchall()
    con.close()
    print(f"  weread 相关 cookie 记录: {len(rows)} 条")

    out = {}
    for host, name, encval, plain in rows:
        if plain:
            out[name] = plain
            continue
        if not encval:
            continue
        got = try_decrypt_v10(encval, key) if key else None
        if got is None:
            # 老格式：整串 DPAPI
            try:
                got = dpapi_decrypt(encval).decode("utf-8", "replace")
            except Exception:
                got = None
        if got:
            out[name] = got
    print(f"  成功解出: {len(out)} 条 -> {list(out)[:12]}")
    return out


def main() -> int:
    print("Python:", sys.version.split()[0])
    print("管理员:", bool(ctypes.windll.shell32.IsUserAnAdmin()))
    local = os.environ.get("LOCALAPPDATA", "")
    if os.path.isdir(local):
        print(f"用户数据目录: {local}")
        for b in ("edge", "chrome", "brave"):
            r = profile_dir(b)
            if os.path.isdir(r):
                print(f"  {b}: 已安装, profiles={list_profiles(r)}")

    found = {}
    for b in ("edge", "chrome", "brave"):
        for prof in (list_profiles(profile_dir(b)) or ["Default"]):
            got = dump_cookies(b, prof)
            if got.get("wr_skey"):
                found[b] = got
                break
        if found:
            break

    print(f"\n{'='*64}")
    if "wr_skey" in (list(found.values())[0] if found else {}):
        cookies = list(found.values())[0]
        line = "; ".join(f"{k}={v}" for k, v in cookies.items())
        print("成功！把下面这行填到 config.yaml 的 source.weread.cookie（cookie_from 改为 manual）：\n")
        print(line)
        return 0
    print("没能自动解出 wr_skey。请改走手动 cookie（F12 复制）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
