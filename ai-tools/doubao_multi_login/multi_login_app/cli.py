import sys
import os
from accounts.manager import AccountManager
from browser.multi_login import MultiLoginManager

def print_menu():
    print("\n多账户登录管理工具")
    print("1. 添加账户")
    print("2. 查看账户列表")
    print("3. 编辑账户")
    print("4. 删除账户")
    print("5. 登录单个账户")
    print("6. 登录所有账户")
    print("0. 退出")

def add_account(account_manager):
    name = input("请输入账户名称: ")
    website = input("请输入网站地址: ")
    username = input("请输入用户名: ")
    password = input("请输入密码: ")
    
    account = account_manager.add_account(name, website, username, password)
    if account:
        print(f"账户添加成功: {account.name}")
    else:
        print("账户添加失败")

def list_accounts(account_manager):
    accounts = account_manager.get_accounts()
    if not accounts:
        print("暂无账户")
        return
    
    print("\n账户列表:")
    for account in accounts:
        print(f"ID: {account.id}, 名称: {account.name}, 网站: {account.website}, 用户名: {account.username}")

def edit_account(account_manager):
    account_id = int(input("请输入要编辑的账户ID: "))
    account = account_manager.get_account(account_id)
    if not account:
        print("账户不存在")
        return
    
    name = input(f"请输入新的账户名称 (当前: {account.name}): ") or account.name
    website = input(f"请输入新的网站地址 (当前: {account.website}): ") or account.website
    username = input(f"请输入新的用户名 (当前: {account.username}): ") or account.username
    password = input("请输入新的密码 (留空保持不变): ")
    
    kwargs = {"name": name, "website": website, "username": username}
    if password:
        kwargs["password"] = password
    
    updated_account = account_manager.update_account(account_id, **kwargs)
    if updated_account:
        print("账户更新成功")
    else:
        print("账户更新失败")

def delete_account(account_manager):
    account_id = int(input("请输入要删除的账户ID: "))
    success = account_manager.delete_account(account_id)
    if success:
        print("账户删除成功")
    else:
        print("账户删除失败")

def login_single_account(multi_login_manager):
    account_id = int(input("请输入要登录的账户ID: "))
    multi_login_manager.login_single_account(account_id)

def login_all_accounts(multi_login_manager):
    multi_login_manager.login_all_accounts()

def main():
    account_manager = AccountManager()
    multi_login_manager = MultiLoginManager()
    
    while True:
        print_menu()
        choice = input("请选择操作: ")
        
        if choice == "1":
            add_account(account_manager)
        elif choice == "2":
            list_accounts(account_manager)
        elif choice == "3":
            edit_account(account_manager)
        elif choice == "4":
            delete_account(account_manager)
        elif choice == "5":
            login_single_account(multi_login_manager)
        elif choice == "6":
            login_all_accounts(multi_login_manager)
        elif choice == "0":
            print("退出程序")
            break
        else:
            print("无效选择，请重新输入")

if __name__ == "__main__":
    main()