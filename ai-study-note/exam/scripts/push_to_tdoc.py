import sys, json, time

SKILL_DIR = r"C:/Users/qq940/.workbuddy/plugins/cache/workbuddy-builtin/tencent-docs-plugin/5.5.3-wb.37748631.g104760a2.h1a8f7c37fe76/skills/tencent-docs"
sys.path.insert(0, SKILL_DIR)
import tencentdocs as td

MD_PATH = r"D:/ai_show/hello_ai_llm/大模型面试复习-专项深度版-2026-09-10.md"
FOLDER_ID = "IOOrrAxOOtxO"  # 大模型面试 文件夹
TITLE = "大模型面试复习-专项深度版（2026-09-10）"


def get_sc(res):
    return (res.get("result") or {}).get("structuredContent") or {}


with open(MD_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# 1) 创建智能文档（markdown 格式），带 429 重试
res, err = None, "not_started"
for attempt in range(1, 6):
    res, err = td.call_tool(
        "tencent-docs",
        "create_smartcanvas_by_mdx",
        {"title": TITLE, "mdx": content, "content_format": "markdown"},
    )
    if not err:
        break
    print(f"CREATE attempt {attempt} failed: {err}; sleep 15s and retry")
    time.sleep(15)
if err:
    print("CREATE_ERROR:", err)
    sys.exit(1)
sc = get_sc(res)
print("CREATE_SC:", json.dumps(sc, ensure_ascii=False)[:400])
file_id = sc.get("file_id")
doc_url = sc.get("url")
print("FILE_ID:", file_id)
print("URL:", doc_url)

if not file_id:
    print("NO_FILE_ID, abort")
    sys.exit(2)

# 2) 移入文件夹
mres, merr = td.call_tool(
    "tencent-docs",
    "manage.move_file",
    {"file_id": file_id, "target_folder_id": FOLDER_ID},
)
print("MOVE_SC:", json.dumps(get_sc(mres), ensure_ascii=False) if mres else merr)

print("FINAL_DOC_URL:", doc_url)
print("FINAL_FILE_ID:", file_id)
