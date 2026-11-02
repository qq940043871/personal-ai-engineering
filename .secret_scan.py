import subprocess, re, os, sys

root = os.path.dirname(os.path.abspath(__file__))

def run(args):
    return subprocess.run(["git"] + args, capture_output=True, text=True, cwd=root).stdout

files = set()
files.update(run(["ls-files", "--cached"]).splitlines())
files.update(run(["ls-files", "--others", "--exclude-standard"]).splitlines())
files.update(run(["ls-files", "--modified"]).splitlines())
files.update(run(["ls-files", "--deleted"]).splitlines())

pat = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|api[_-]?key\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}"
    r"|Bearer\s+[A-Za-z0-9_\-\.]{20,}|AKIA[0-9A-Z]{16})"
)
exclude = re.compile(
    r"REPLACE_WITH|your[_-]?key|your[_-]?api|placeholder|example|xxxxxx|<.*>|\.\.\.|TODO|CHANGE_ME|YOUR[_-]",
    re.I,
)

hits = []
scanned = 0
for f in sorted(files):
    p = os.path.join(root, f)
    if not os.path.exists(p):
        continue
    if os.path.getsize(p) > 5_000_000:
        continue
    if not f.lower().endswith((".py", ".md", ".json", ".yaml", ".yml", ".txt",
                               ".js", ".ts", ".sh", ".bat", ".env", ".cfg",
                               ".ini", ".toml", ".html")):
        continue
    scanned += 1
    try:
        data = open(p, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    for m in pat.finditer(data):
        val = m.group(0)
        if exclude.search(val):
            continue
        start = max(0, m.start() - 40)
        ctx = data[start:m.end() + 10]
        if exclude.search(ctx):
            continue
        hits.append((f, val[:40], ctx.strip()[-60:]))

print("扫描文本文件数: %d" % scanned)
print("疑似真实密钥命中: %d" % len(hits))
for f, val, ctx in hits[:50]:
    print("  [疑似] %s -> %s | ...%s..." % (f, val, ctx))
