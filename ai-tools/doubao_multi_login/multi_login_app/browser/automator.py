from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
from utils.error_handling import handle_exception, safe_execute

class BrowserAutomator:
    def __init__(self):
        self.browser = None
    
    @handle_exception
    def start(self, profile_dir=None):
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        # 禁用GPU加速，减少资源占用
        options.add_argument("--disable-gpu")
        # 禁用沙盒模式，提高兼容性
        options.add_argument("--no-sandbox")
        # 禁用共享内存
        options.add_argument("--disable-dev-shm-usage")
        
        # 如果指定了配置文件目录，使用不同的配置文件
        if profile_dir:
            options.add_argument(f"--user-data-dir={profile_dir}")
        
        self.browser = webdriver.Chrome(options=options)
        return self.browser
    
    @handle_exception
    def stop(self):
        if self.browser:
            self.browser.quit()
    
    @handle_exception
    def open_website(self, website):
        try:
            if not self.browser:
                print("浏览器未初始化")
                return False
            self.browser.get(website)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"打开网站失败: {e}")
            return False
    
    @handle_exception
    def login_doubao(self, username, password):
        try:
            if not self.browser:
                print("浏览器未初始化")
                return False
            # 点击登录按钮
            try:
                login_button = WebDriverWait(self.browser, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[text()='登录']"))
                )
                login_button.click()
                time.sleep(2)
            except Exception as e:
                print(f"找不到登录按钮: {e}")
            
            # 输入用户名和密码
            try:
                username_input = WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
                )
                username_input.send_keys(username)
            except Exception as e:
                print(f"找不到用户名输入框: {e}")
            
            try:
                password_input = WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
                )
                password_input.send_keys(password)
            except Exception as e:
                print(f"找不到密码输入框: {e}")
            
            # 点击登录按钮
            try:
                submit_button = WebDriverWait(self.browser, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
                )
                submit_button.click()
            except Exception as e:
                print(f"找不到提交按钮: {e}")
            
            time.sleep(5)
            return True
        except Exception as e:
            print(f"登录豆包失败: {e}")
            return False
    
    @handle_exception
    def login_generic(self, username, password):
        try:
            if not self.browser:
                print("浏览器未初始化")
                return False
            # 尝试查找用户名和密码输入框
            try:
                username_input = WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[name='username'], input[id*='user']"))
                )
                username_input.send_keys(username)
            except Exception as e:
                print(f"找不到用户名输入框: {e}")
            
            try:
                password_input = WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'], input[name='password'], input[id*='pass']"))
                )
                password_input.send_keys(password)
            except Exception as e:
                print(f"找不到密码输入框: {e}")
            
            # 尝试查找登录按钮
            try:
                submit_button = WebDriverWait(self.browser, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"))
                )
                submit_button.click()
            except Exception as e:
                try:
                    submit_button = WebDriverWait(self.browser, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '登录') or contains(text(), 'Login')]"))
                    )
                    submit_button.click()
                except Exception as e2:
                    print(f"找不到登录按钮: {e2}")
            
            time.sleep(5)
            return True
        except Exception as e:
            print(f"登录失败: {e}")
            return False
    
    @handle_exception
    def login_account(self, account):
        website = account.website
        username = account.username
        password = account.password
        
        # 先打开网站
        self.open_website(website)
        
        if "doubao" in website.lower():
            return self.login_doubao(username, password)
        else:
            return self.login_generic(username, password)