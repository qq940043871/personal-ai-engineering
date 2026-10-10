import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import requests
import os
import json
import uuid
from datetime import datetime
import threading
import tempfile

class RagflowDocumentUploader:
    def __init__(self, root):
        self.root = root
        self.root.title("Ragflow知识库")
        self.root.geometry("850x700")
        self.root.resizable(True, True)

        # 设置中文字体
        self.font = ('SimHei', 10)
        self.bold_font = ('SimHei', 10, 'bold')

        # 配置变量
        self.api_base_url = tk.StringVar(value="http://10.17.1.134:30002")
        self.api_key = tk.StringVar(value="ragflow-I4YWJhNmU0NjA2MzExZjA5NDQ0NmI3NG")
        self.dataset_id = tk.StringVar()
        self.document_id = tk.StringVar()
        self.selected_file = tk.StringVar()
        self.empty_document_name  = tk.StringVar()
        self.chunk_delimiter = tk.StringVar(value="@@")
        self.upload_in_progress = False
        self.file_content = None

        # 创建界面
        self.create_widgets()

    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # API配置区域
        config_frame = ttk.LabelFrame(main_frame, text="API配置", padding="10")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(config_frame, text="API地址:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.api_base_url, width=50, font=self.font).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(config_frame, text="访问密钥:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.api_key, width=50, show="*", font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(config_frame, text="知识库ID:", font=self.font).grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.dataset_id, width=50, font=self.font).grid(row=2, column=1, sticky=tk.W, pady=5)

        # 知识库配置区域
        dataset_frame = ttk.LabelFrame(main_frame, text="知识库配置", padding="10")
        dataset_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(dataset_frame, text="本地文件:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(dataset_frame, textvariable=self.selected_file, width=50, font=self.font).grid(row=0, column=1, sticky=tk.W, pady=5)
        ttk.Button(dataset_frame, text="浏览", command=self.browse_file, width=8).grid(row=0, column=2, padx=5, pady=5)
       
        ttk.Label(dataset_frame, text="文档ID:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(dataset_frame, textvariable=self.document_id, width=50, font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Button(dataset_frame, text="创建", command=self.upload_empty_file, width=8).grid(row=1, column=2, padx=5, pady=5)

        # 文件和分段配置区域
        file_frame = ttk.LabelFrame(main_frame, text="分段配置", padding="10")
        file_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(file_frame, text="分段分隔符:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(file_frame, textvariable=self.chunk_delimiter, width=20, font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))
        self.upload_chunks_btn = ttk.Button(button_frame, text="上传分段", command=self.start_upload_chunks, width=15)
        self.upload_chunks_btn.pack(side=tk.LEFT, padx=5)

        self.cancel_btn = ttk.Button(button_frame, text="取消", command=self.cancel_operation, width=10, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=self.font, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # 进度条
        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(10, 0))

    def browse_file(self):
        filename = filedialog.askopenfilename(
            filetypes=[("Markdown文件", "*.md"), ("所有文件", "*.*")]
        )
        if filename:
            self.selected_file.set(filename)
            # 提取文件名
            self.empty_document_name = os.path.basename(filename);
            print('filename',self.empty_document_name)
            # 读取文件内容并缓存
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.file_content = f.read()
                self.log(f"已选择并读取文件: {filename} (大小: {len(self.file_content)} 字符)")
            except Exception as e:
                self.log(f"读取文件失败: {str(e)}")
                messagebox.showerror("错误", f"读取文件失败: {str(e)}")

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def upload_empty_file(self):
        # 验证输入
        if not self.validate_api_config():
            return

        self.log("开始上传空文件...")
        self.upload_in_progress = True
        self.cancel_btn.config(state=tk.NORMAL)
        self.progress['value'] = 0

        threading.Thread(target=self._upload_empty_file_thread, daemon=True).start()

    def _upload_empty_file_thread(self):
        try:
            # 创建临时空文件
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as temp_file:
                temp_file_name = temp_file.name
                # 文件保持为空

            url = f"{self.api_base_url.get().rstrip('/')}/api/v1/datasets/{self.dataset_id.get()}/documents"
            headers = {
                'Authorization': f'Bearer {self.api_key.get()}'
            }

            # 读取临时空文件并上传
            with open(temp_file_name, 'rb') as f:
                files = {'file': (f'{self.empty_document_name}', f, 'text/plain')}
                response = requests.post(url, headers=headers, files=files, timeout=30)

            # 删除临时文件
            os.unlink(temp_file_name)

            self.log(f"上传空文件请求状态码: {response.status_code}")
            self.progress['value'] = 100

            if response.status_code == 200:
                result = response.json()
                if 'data' in result :
                    # 获取id值（假设data列表中至少有一个元素）
                    document_id = result["data"][0]["id"]
                    self.document_id.set(document_id)
                    self.log(f"空文档上传成功，ID: {document_id}")
                else:
                    self.log(f"上传失败: {result.get('message', '未知错误')}")
                    messagebox.showerror("错误", f"上传失败: {result.get('message', '未知错误')}")
            else:
                self.log(f"请求失败: {response.text}")
                messagebox.showerror("错误", f"请求失败: {response.text}")

        except Exception as e:
            self.log(f"上传空文件时发生错误: {str(e)}")
            messagebox.showerror("错误", f"上传空文件时发生错误: {str(e)}")
        finally:
            self.upload_in_progress = False
            self.cancel_btn.config(state=tk.DISABLED)

    def start_upload_chunks(self):
        if not self.validate_api_config() or not self.document_id.get().strip():
            return
        if not self.selected_file.get().strip() or self.file_content is None:
            messagebox.showerror("错误", "请选择并加载分段文件")
            return

        self.log("开始准备上传分段...")
        self.upload_in_progress = True
        self.upload_chunks_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.progress['value'] = 0

        threading.Thread(target=self._upload_chunks_thread, daemon=True).start()

    def _upload_chunks_thread(self):
        try:
            # 分割文件内容
            delimiter = self.chunk_delimiter.get()
            chunks = self.file_content.split(delimiter)
            chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
            total_chunks = len(chunks)

            if total_chunks == 0:
                self.log("未找到可上传的分段内容")
                messagebox.showwarning("警告", "未找到可上传的分段内容")
                return

            self.log(f"成功分割出 {total_chunks} 个分段")
            success_count = 0

            # 上传每个分段
            for i, chunk in enumerate(chunks):
                if not self.upload_in_progress:
                    break

                self.log(f"正在上传第 {i+1}/{total_chunks} 个分段...")
                if self._upload_single_chunk(chunk, i+1):
                    success_count += 1

                # 更新进度
                progress = int(100 * (i+1) / total_chunks)
                self.progress['value'] = progress

            if self.upload_in_progress:
                self.progress['value'] = 100
                self.log(f"分段上传完成，成功: {success_count}/{total_chunks}")
                if success_count == total_chunks:
                    messagebox.showinfo("成功", "所有分段上传完成！")
                else:
                    messagebox.showwarning("部分成功", f"分段上传完成，{success_count}/{total_chunks} 成功")

        except Exception as e:
            self.log(f"分段上传失败: {str(e)}")
            messagebox.showerror("错误", f"分段上传失败: {str(e)}")
        finally:
            self.upload_in_progress = False
            self.upload_chunks_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)

    def _upload_single_chunk(self, content, position):
        try:
            url = f"{self.api_base_url.get().rstrip('/')}/api/v1/datasets/{self.dataset_id.get()}/documents/{self.document_id.get()}/chunks"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key.get()}'
            }
            payload = {
                "content": content,
                "important_keywords": []
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    self.log(f"分段 {position} 上传成功")
                    return True
                else:
                    self.log(f"分段 {position} 上传失败: {result.get('message', '未知错误')}")
            else:
                self.log(f"分段 {position} 请求失败: {response.text}")
            return False
        except Exception as e:
            self.log(f"分段 {position} 发生错误: {str(e)}")
            return False

    def validate_api_config(self):
        if not self.api_base_url.get().strip():
            messagebox.showerror("错误", "请输入API地址")
            return False
        if not self.api_key.get().strip():
            messagebox.showerror("错误", "请输入访问密钥")
            return False
        if not self.dataset_id.get().strip():
            messagebox.showerror("错误", "请输入知识库ID")
            return False
        return True

    def cancel_operation(self):
        self.upload_in_progress = False
        self.log("操作已取消")

if __name__ == "__main__":
    root = tk.Tk()
    app = RagflowDocumentUploader(root)
    root.mainloop()