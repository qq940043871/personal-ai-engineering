import requests

# ========== 请修改以下3个参数 ==========
GITEE_TOKEN = ""  # 替换成你刚复制的Token
GITEE_USERNAME = "haswhere"  # 替换成你的Gitee用户名
# 要删除的仓库名列表（留空则删除所有个人仓库；只删部分就填名字，如 ["repo1", "repo2"]）
DELETE_REPO_NAMES = []
# ======================================

headers = {"Authorization": f"Bearer {GITEE_TOKEN}"}

def get_all_repos():
    """获取个人所有仓库"""
    url = "https://gitee.com/api/v5/user/repos?per_page=100"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def delete_repo(repo_full_name):
    """删除单个仓库（格式：用户名/仓库名）"""
    url = f"https://gitee.com/api/v5/repos/{repo_full_name}"
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 204:
        print(f"✅ 删除成功: {repo_full_name}")
    else:
        print(f"❌ 删除失败: {repo_full_name}, 状态码: {resp.status_code}, 错误: {resp.text}")

if __name__ == "__main__":
    repos = get_all_repos()
    print(f"📦 共获取到 {len(repos)} 个个人仓库")

    # 筛选要删除的仓库
    target_repos = []
    if not DELETE_REPO_NAMES:
        # 清空列表=删除所有个人仓库
        target_repos = [repo["full_name"] for repo in repos]
    else:
        # 只删指定名称的仓库
        target_repos = [repo["full_name"] for repo in repos if repo["name"] in DELETE_REPO_NAMES]

    print(f"🔍 即将删除 {len(target_repos)} 个仓库: {[n.split('/')[-1] for n in target_repos]}")
    confirm = input("⚠️ 确认删除？输入 YES 继续，其他取消: ")
    if confirm != "YES":
        print("🚫 已取消批量删除")
        exit()

    # 执行批量删除
    for full_name in target_repos:
        delete_repo(full_name)
    print("\n✅ 批量删除操作完成")