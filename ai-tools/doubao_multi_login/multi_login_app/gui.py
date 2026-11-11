import sys
import os
import tempfile
import time
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTableWidget, QTableWidgetItem, QPushButton, QLineEdit, QLabel, 
    QDialog, QFormLayout, QMessageBox, QInputDialog, QTabWidget, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtWebEngineWidgets import QWebEngineProfile
from accounts.manager import AccountManager
from browser.multi_login import MultiLoginManager
from browser.embedded_browser import EmbeddedBrowser

class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加账户")
        self.setGeometry(200, 200, 400, 250)
        
        layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.website_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        
        layout.addRow("账户名称:", self.name_input)
        layout.addRow("网站地址:", self.website_input)
        layout.addRow("用户名:", self.username_input)
        layout.addRow("密码:", self.password_input)
        
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addRow(button_layout)
        
        self.setLayout(layout)
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
    
    def get_account_data(self):
        return {
            "name": self.name_input.text(),
            "website": self.website_input.text(),
            "username": self.username_input.text(),
            "password": self.password_input.text()
        }

class EditAccountDialog(QDialog):
    def __init__(self, account, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑账户")
        self.setGeometry(200, 200, 400, 250)
        
        layout = QFormLayout()
        
        self.name_input = QLineEdit(account.name)
        self.website_input = QLineEdit(account.website)
        self.username_input = QLineEdit(account.username)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        
        layout.addRow("账户名称:", self.name_input)
        layout.addRow("网站地址:", self.website_input)
        layout.addRow("用户名:", self.username_input)
        layout.addRow("密码 (留空保持不变):", self.password_input)
        
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addRow(button_layout)
        
        self.setLayout(layout)
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
    
    def get_account_data(self):
        return {
            "name": self.name_input.text(),
            "website": self.website_input.text(),
            "username": self.username_input.text(),
            "password": self.password_input.text()
        }

class SessionWidget(QWidget):
    def __init__(self, session_name, website, parent=None):
        super().__init__(parent)
        self.session_name = session_name
        self.website = website
        
        layout = QVBoxLayout(self)
        
        # 地址栏和标签页控制
        top_layout = QHBoxLayout()
        
        # 网站地址栏
        self.address_bar = QLineEdit()
        self.address_bar.setText(website)
        self.address_bar.returnPressed.connect(self.load_url)
        top_layout.addWidget(self.address_bar)
        
        # 新建标签页按钮
        self.new_tab_button = QPushButton("+ 新标签")
        self.new_tab_button.clicked.connect(self.new_tab)
        top_layout.addWidget(self.new_tab_button)
        
        layout.addLayout(top_layout)
        
        # 标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        layout.addWidget(self.tab_widget)
        
        # 添加第一个标签页
        self.new_tab(website)
    
    def new_tab(self, url=None):
        """新建标签页"""
        if not url:
            url = "https://www.doubao.com"
        
        # 创建新的标签页内容
        tab_content = QWidget()
        tab_layout = QVBoxLayout(tab_content)
        
        # 创建独立的QWebEngineProfile
        profile_name = f"{self.session_name}_tab_{self.tab_widget.count()}"
        profile = QWebEngineProfile(profile_name, self)
        
        # 创建浏览器控件
        web_view = QWebEngineView()
        web_view.setPage(QWebEnginePage(profile, web_view))
        
        # 启用JavaScript
        settings = web_view.settings()
        settings.setAttribute(settings.JavascriptEnabled, True)
        
        web_view.load(QUrl(url))
        
        # 连接信号
        web_view.urlChanged.connect(lambda qurl, view=web_view: self.update_address_bar(qurl, view))
        
        tab_layout.addWidget(web_view)
        
        # 添加标签页
        tab_index = self.tab_widget.addTab(tab_content, "新标签")
        self.tab_widget.setCurrentIndex(tab_index)
        
        # 存储标签页信息
        self.tab_widget.tabBar().setTabData(tab_index, {"web_view": web_view, "profile": profile})
    
    def close_tab(self, index):
        """关闭标签页"""
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)
    
    def on_tab_changed(self, index):
        """标签页切换时更新地址栏"""
        if index >= 0:
            tab_data = self.tab_widget.tabBar().tabData(index)
            if tab_data and "web_view" in tab_data:
                web_view = tab_data["web_view"]
                url = web_view.url().toString()
                self.address_bar.setText(url)
    
    def load_url(self):
        """加载URL"""
        url = self.address_bar.text()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            tab_data = self.tab_widget.tabBar().tabData(current_index)
            if tab_data and "web_view" in tab_data:
                web_view = tab_data["web_view"]
                web_view.load(QUrl(url))
    
    def update_address_bar(self, qurl, web_view):
        """更新地址栏"""
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            tab_data = self.tab_widget.tabBar().tabData(current_index)
            if tab_data and "web_view" in tab_data and tab_data["web_view"] == web_view:
                self.address_bar.setText(qurl.toString())
                # 更新标签页标题
                title = web_view.title()
                if title:
                    self.tab_widget.setTabText(current_index, title[:20] + "..." if len(title) > 20 else title)
    
    def get_web_view(self):
        """获取当前标签页的web_view"""
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            tab_data = self.tab_widget.tabBar().tabData(current_index)
            if tab_data and "web_view" in tab_data:
                return tab_data["web_view"]
        return None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("多账户登录管理")
        self.setGeometry(100, 100, 1200, 800)
        
        self.account_manager = AccountManager()
        self.multi_login_manager = MultiLoginManager()
        self.sessions = []  # 存储会话信息
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局 - 左右布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧会话管理面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # 会话列表
        self.session_list = QListWidget()
        self.session_list.setMaximumWidth(150)
        self.session_list.itemClicked.connect(self.switch_session)
        left_layout.addWidget(self.session_list)
        
        # 会话管理按钮
        session_buttons = QHBoxLayout()
        self.add_session_button = QPushButton("+ 新建会话")
        self.delete_session_button = QPushButton("- 删除会话")
        session_buttons.addWidget(self.add_session_button)
        session_buttons.addWidget(self.delete_session_button)
        left_layout.addLayout(session_buttons)
        
        # 网站输入
        self.website_input = QLineEdit()
        self.website_input.setPlaceholderText("输入网站地址")
        left_layout.addWidget(self.website_input)
        
        # 账户管理按钮
        account_buttons = QHBoxLayout()
        self.add_account_button = QPushButton("管理账户")
        account_buttons.addWidget(self.add_account_button)
        left_layout.addLayout(account_buttons)
        
        # 右侧浏览器区域
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        # 初始提示
        self.initial_label = QLabel("请从左侧选择或新建会话")
        self.initial_label.setAlignment(Qt.AlignCenter)
        self.right_layout.addWidget(self.initial_label)
        
        # 添加到主布局
        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.right_panel, 1)  # 右侧占据主要空间
        
        # 连接信号
        self.add_session_button.clicked.connect(self.add_session)
        self.delete_session_button.clicked.connect(self.delete_session)
        self.add_account_button.clicked.connect(self.open_account_management)
        
        # 加载账户列表
        self.load_accounts()
        
        # 初始化会话列表
        self.update_session_list()
    
    def load_accounts(self):
        # 加载账户列表，用于账户管理
        self.accounts = self.account_manager.get_accounts()
    
    def update_session_list(self):
        """更新会话列表"""
        self.session_list.clear()
        for i, session in enumerate(self.sessions):
            item = QListWidgetItem(f"会话 {i+1}: {session['name']}")
            item.setData(Qt.UserRole, i)
            self.session_list.addItem(item)
    
    def add_session(self):
        """新建会话"""
        website = self.website_input.text().strip()
        if not website:
            website = "https://www.doubao.com"  # 默认网站
        else:
            if not website.startswith("http://") and not website.startswith("https://"):
                website = "https://" + website
        
        session_name = f"会话 {len(self.sessions) + 1}"
        session = {
            "name": session_name,
            "website": website,
            "widget": None
        }
        self.sessions.append(session)
        self.update_session_list()
        
        # 自动切换到新会话
        if self.sessions:
            self.session_list.setCurrentRow(len(self.sessions) - 1)
            self.switch_session(self.session_list.currentItem())
    
    def delete_session(self):
        """删除会话"""
        current_item = self.session_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请选择要删除的会话")
            return
        
        session_index = current_item.data(Qt.UserRole)
        
        # 确认删除
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除会话 {self.sessions[session_index]['name']} 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 移除会话
            self.sessions.pop(session_index)
            self.update_session_list()
            
            # 清空右侧面板
            self.clear_right_panel()
            
            # 如果还有会话，切换到第一个
            if self.sessions:
                self.session_list.setCurrentRow(0)
                self.switch_session(self.session_list.currentItem())
    
    def switch_session(self, item):
        """切换会话"""
        if not item:
            return
        
        session_index = item.data(Qt.UserRole)
        session = self.sessions[session_index]
        
        # 清空右侧面板
        self.clear_right_panel()
        
        # 重新创建SessionWidget，确保使用新的对象
        session['widget'] = SessionWidget(session['name'], session['website'])
        
        # 添加到右侧面板
        self.right_layout.addWidget(session['widget'])
    
    def clear_right_panel(self):
        """清空右侧面板"""
        # 移除所有子控件
        while self.right_layout.count() > 0:
            widget = self.right_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        
        # 如果没有会话，显示初始提示
        if not self.sessions:
            self.initial_label = QLabel("请从左侧选择或新建会话")
            self.initial_label.setAlignment(Qt.AlignCenter)
            self.right_layout.addWidget(self.initial_label)
    
    def open_account_management(self):
        """打开账户管理窗口"""
        # 这里可以打开一个新窗口来管理账户
        # 简化实现，使用现有的账户管理方法
        dialog = QDialog(self)
        dialog.setWindowTitle("账户管理")
        dialog.setGeometry(200, 200, 600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 账户列表
        account_table = QTableWidget()
        account_table.setColumnCount(4)
        account_table.setHorizontalHeaderLabels(["ID", "账户名称", "网站地址", "用户名"])
        
        accounts = self.account_manager.get_accounts()
        account_table.setRowCount(len(accounts))
        
        for i, account in enumerate(accounts):
            account_table.setItem(i, 0, QTableWidgetItem(str(account.id)))
            account_table.setItem(i, 1, QTableWidgetItem(account.name))
            account_table.setItem(i, 2, QTableWidgetItem(account.website))
            account_table.setItem(i, 3, QTableWidgetItem(account.username))
        
        layout.addWidget(account_table)
        
        # 按钮
        button_layout = QHBoxLayout()
        add_btn = QPushButton("添加账户")
        edit_btn = QPushButton("编辑账户")
        delete_btn = QPushButton("删除账户")
        close_btn = QPushButton("关闭")
        
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # 连接信号
        add_btn.clicked.connect(lambda: self.add_account(dialog))
        edit_btn.clicked.connect(lambda: self.edit_account_dialog(dialog, account_table))
        delete_btn.clicked.connect(lambda: self.delete_account_dialog(dialog, account_table))
        close_btn.clicked.connect(dialog.close)
        
        dialog.exec_()
    
    def add_account(self, parent=None):
        dialog = AddAccountDialog(parent or self)
        if dialog.exec_():
            account_data = dialog.get_account_data()
            try:
                self.account_manager.add_account(
                    account_data["name"],
                    account_data["website"],
                    account_data["username"],
                    account_data["password"]
                )
                QMessageBox.information(self, "成功", "账户添加成功！")
                self.load_accounts()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"添加账户失败: {str(e)}")
    
    def edit_account_dialog(self, parent, account_table):
        selected_rows = account_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请选择要编辑的账户")
            return
        
        row = selected_rows[0].row()
        account_id = int(account_table.item(row, 0).text())
        account = self.account_manager.get_account(account_id)
        
        if not account:
            QMessageBox.warning(self, "错误", "账户不存在")
            return
        
        dialog = EditAccountDialog(account, parent)
        if dialog.exec_():
            account_data = dialog.get_account_data()
            try:
                kwargs = {
                    "name": account_data["name"],
                    "website": account_data["website"],
                    "username": account_data["username"]
                }
                if account_data["password"]:
                    kwargs["password"] = account_data["password"]
                
                self.account_manager.update_account(account_id, **kwargs)
                QMessageBox.information(self, "成功", "账户更新成功！")
                # 重新加载账户列表
                accounts = self.account_manager.get_accounts()
                account_table.setRowCount(len(accounts))
                for i, acc in enumerate(accounts):
                    account_table.setItem(i, 0, QTableWidgetItem(str(acc.id)))
                    account_table.setItem(i, 1, QTableWidgetItem(acc.name))
                    account_table.setItem(i, 2, QTableWidgetItem(acc.website))
                    account_table.setItem(i, 3, QTableWidgetItem(acc.username))
            except Exception as e:
                QMessageBox.warning(self, "错误", f"更新账户失败: {str(e)}")
    
    def delete_account_dialog(self, parent, account_table):
        selected_rows = account_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请选择要删除的账户")
            return
        
        row = selected_rows[0].row()
        account_id = int(account_table.item(row, 0).text())
        account_name = account_table.item(row, 1).text()
        
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除账户 {account_name} 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                success = self.account_manager.delete_account(account_id)
                if success:
                    QMessageBox.information(self, "成功", "账户删除成功！")
                    # 重新加载账户列表
                    accounts = self.account_manager.get_accounts()
                    account_table.setRowCount(len(accounts))
                    for i, acc in enumerate(accounts):
                        account_table.setItem(i, 0, QTableWidgetItem(str(acc.id)))
                        account_table.setItem(i, 1, QTableWidgetItem(acc.name))
                        account_table.setItem(i, 2, QTableWidgetItem(acc.website))
                        account_table.setItem(i, 3, QTableWidgetItem(acc.username))
                else:
                    QMessageBox.warning(self, "错误", "删除账户失败")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除账户失败: {str(e)}")
    
    def edit_account(self):
        # 保留原方法，确保兼容性
        pass
    
    def delete_account(self):
        # 保留原方法，确保兼容性
        pass
    
    def login_selected_account(self):
        # 保留原方法，确保兼容性
        pass
    
    def login_all_accounts(self):
        # 保留原方法，确保兼容性
        pass
    
    def open_website_for_selected_accounts(self):
        # 保留原方法，确保兼容性
        pass
    
    def open_embedded_browser_for_selected_accounts(self):
        # 保留原方法，确保兼容性
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())