from .automator import BrowserAutomator
from .embedded_browser import EmbeddedBrowserManager
from accounts.manager import AccountManager
import threading
import time
import os
import tempfile
from utils.error_handling import handle_exception, safe_execute
from PyQt5.QtWidgets import QApplication

class MultiLoginManager:
    def __init__(self):
        self.account_manager = AccountManager()
        self.processes = []
        self.profile_dirs = []
        self.embedded_browser_manager = EmbeddedBrowserManager()
        self.app = None
    
    def _create_profile_dir(self, account_name):
        """为每个账户创建独立的浏览器配置文件目录"""
        temp_dir = tempfile.gettempdir()
        profile_dir = os.path.join(temp_dir, f"browser_profile_{account_name}_{int(time.time())}")
        os.makedirs(profile_dir, exist_ok=True)
        self.profile_dirs.append(profile_dir)
        return profile_dir
    
    @handle_exception
    def login_single_account(self, account_id):
        account = self.account_manager.get_account(account_id)
        if not account:
            print(f"账户ID {account_id} 不存在")
            return False
        
        # 创建独立的配置文件目录
        profile_dir = self._create_profile_dir(account.name)
        
        automator = BrowserAutomator()
        try:
            automator.start(profile_dir=profile_dir)
            result = automator.login_account(account)
            print(f"账户 {account.name} 登录{'成功' if result else '失败'}")
            # 不关闭浏览器，让用户保持登录状态
            # automator.stop()
            return result
        except Exception as e:
            print(f"登录账户 {account.name} 失败: {e}")
            automator.stop()
            return False
    
    @handle_exception
    def login_all_accounts(self):
        accounts = self.account_manager.get_accounts()
        if not accounts:
            print("没有账户需要登录")
            return
        
        threads = []
        
        for account in accounts:
            thread = threading.Thread(
                target=self.login_single_account,
                args=(account.id,)
            )
            threads.append(thread)
            thread.start()
            time.sleep(2)  # 增加延迟，避免同时打开多个浏览器导致系统压力过大
        
        for thread in threads:
            thread.join()
        
        print("所有账户登录完成")
    
    @handle_exception
    def login_selected_accounts(self, account_ids):
        if not account_ids:
            print("没有选中的账户需要登录")
            return
        
        threads = []
        
        for account_id in account_ids:
            thread = threading.Thread(
                target=self.login_single_account,
                args=(account_id,)
            )
            threads.append(thread)
            thread.start()
            time.sleep(2)
        
        for thread in threads:
            thread.join()
        
        print("选中的账户登录完成")
    
    @handle_exception
    def open_website_for_accounts(self, website, account_ids):
        """为指定账户打开同一个网站，每个账户在独立进程中"""
        if not account_ids:
            print("没有选中的账户")
            return
        
        threads = []
        
        for account_id in account_ids:
            thread = threading.Thread(
                target=self._open_website_for_account,
                args=(website, account_id)
            )
            threads.append(thread)
            thread.start()
            time.sleep(2)
        
        for thread in threads:
            thread.join()
        
        print(f"为选中账户打开网站 {website} 完成")
    
    @handle_exception
    def _open_website_for_account(self, website, account_id):
        """为单个账户打开网站"""
        account = self.account_manager.get_account(account_id)
        if not account:
            print(f"账户ID {account_id} 不存在")
            return False
        
        # 创建独立的配置文件目录
        profile_dir = self._create_profile_dir(account.name)
        
        automator = BrowserAutomator()
        try:
            automator.start(profile_dir=profile_dir)
            # 打开指定网站
            automator.open_website(website)
            print(f"为账户 {account.name} 打开网站 {website} 成功")
            # 不关闭浏览器，让用户保持登录状态
            # automator.stop()
            return True
        except Exception as e:
            print(f"为账户 {account.name} 打开网站失败: {e}")
            automator.stop()
            return False
    
    def _init_app(self):
        """初始化QApplication"""
        if not QApplication.instance():
            self.app = QApplication([])
        else:
            self.app = QApplication.instance()
    
    @handle_exception
    def open_website_with_embedded_browser(self, website, account_ids):
        """使用内嵌浏览器为指定账户打开同一个网站，每个账户在独立窗口中"""
        if not account_ids:
            print("没有选中的账户")
            return
        
        # 初始化QApplication
        self._init_app()
        
        # 直接在主线程中创建浏览器窗口
        for account_id in account_ids:
            self._open_website_with_embedded_browser(website, account_id)
            time.sleep(1)
        
        print(f"为选中账户打开网站 {website} 完成")
    
    @handle_exception
    def _open_website_with_embedded_browser(self, website, account_id):
        """为单个账户使用内嵌浏览器打开网站"""
        account = self.account_manager.get_account(account_id)
        if not account:
            print(f"账户ID {account_id} 不存在")
            return False
        
        try:
            # 创建内嵌浏览器窗口
            browser = self.embedded_browser_manager.create_browser(account.name, website)
            browser.show()
            print(f"为账户 {account.name} 打开网站 {website} 成功")
            return True
        except Exception as e:
            print(f"为账户 {account.name} 打开网站失败: {e}")
            return False
    
    def cleanup(self):
        """清理临时配置文件目录"""
        for profile_dir in self.profile_dirs:
            try:
                import shutil
                shutil.rmtree(profile_dir)
            except Exception as e:
                print(f"清理配置文件目录失败: {e}")
        self.profile_dirs.clear()
        
        # 关闭所有内嵌浏览器
        self.embedded_browser_manager.close_all_browsers()