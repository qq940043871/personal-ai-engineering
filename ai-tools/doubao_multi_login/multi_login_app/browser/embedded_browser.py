from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QApplication
from PyQt5.QtCore import QUrl, Qt
import sys
import os

# 设置环境变量，避免某些系统上的文本服务问题
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

class EmbeddedBrowser(QMainWindow):
    def __init__(self, account_name, website):
        super().__init__()
        self.setWindowTitle(f"{account_name} - {website}")
        self.setGeometry(100, 100, 1024, 768)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 创建WebEngineView
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
        
        # 加载网站
        self.load_website(website)
    
    def load_website(self, website):
        """加载指定的网站"""
        url = QUrl(website)
        self.web_view.load(url)
    
    def get_web_view(self):
        """获取WebEngineView实例"""
        return self.web_view
    
    def login(self, username, password):
        """执行登录操作"""
        # 这里可以根据具体网站的登录表单结构，通过JavaScript执行登录
        # 例如：
        # login_script = f"""
        # document.querySelector('input[name="username"]').value = '{username}';
        # document.querySelector('input[name="password"]').value = '{password}';
        # document.querySelector('form').submit();
        # """
        # self.web_view.page().runJavaScript(login_script)
        pass

class EmbeddedBrowserManager:
    def __init__(self):
        self.browsers = []
    
    def create_browser(self, account_name, website):
        """创建一个新的内嵌浏览器窗口"""
        browser = EmbeddedBrowser(account_name, website)
        self.browsers.append(browser)
        return browser
    
    def close_all_browsers(self):
        """关闭所有浏览器窗口"""
        for browser in self.browsers:
            browser.close()
        self.browsers.clear()