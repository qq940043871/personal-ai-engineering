from accounts.manager import AccountManager
from browser.multi_login import MultiLoginManager
import time

# 创建账户管理器
account_manager = AccountManager()

# 清空现有账户
accounts = account_manager.get_accounts()
for account in accounts:
    account_manager.delete_account(account.id)

# 添加测试账户
print("添加测试账户...")
test_accounts = [
    {"name": "测试账户1", "website": "https://www.doubao.com", "username": "test1", "password": "password1"},
    {"name": "测试账户2", "website": "https://www.doubao.com", "username": "test2", "password": "password2"},
    {"name": "测试账户3", "website": "https://www.doubao.com", "username": "test3", "password": "password3"}
]

for i, account_data in enumerate(test_accounts):
    account = account_manager.add_account(
        account_data["name"],
        account_data["website"],
        account_data["username"],
        account_data["password"]
    )
    print(f"添加账户 {i+1}: {account.name}")

# 创建多登录管理器
multi_login_manager = MultiLoginManager()

# 为所有账户打开豆包网站
print("\n为所有账户打开豆包网站...")
account_ids = [account.id for account in account_manager.get_accounts()]
website = "https://www.doubao.com"

# 打开网站
multi_login_manager.open_website_for_accounts(website, account_ids)

print("\n测试完成！请检查是否打开了多个浏览器窗口，每个窗口都是独立的进程。")
print("你可以在每个窗口中登录不同的账户，它们之间不会互相影响。")

# 等待用户操作
input("按Enter键清理临时文件并退出...")

# 清理临时文件
multi_login_manager.cleanup()
print("临时文件已清理")