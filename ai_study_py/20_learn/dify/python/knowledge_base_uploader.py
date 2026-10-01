from asyncio.windows_events import NULL
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import requests
import os
import json
from datetime import datetime
import threading

class KnowledgeBaseUploader:
    def __init__(self, root):
        self.root = root
        self.root.title("知识库文档上传工具")
        self.root.geometry("850x700")
        self.root.resizable(True, True)

        # 设置中文字体
        self.font = ('SimHei', 10)
        self.bold_font = ('SimHei', 10, 'bold')

        # 配置变量
        self.api_base_url = tk.StringVar(value="http://10.17.1.134:30001/")
        self.api_key = tk.StringVar(value="dataset-REPLACE_WITH_YOUR_KEY")
        self.dataset_id = tk.StringVar()
        self.selected_file = tk.StringVar()
        self.segment_delimiter = tk.StringVar(value="@!@")
        self.segment_size = tk.StringVar(value="2000")
        self.child_segment_delimiter = tk.StringVar(value="@@")
        self.child_segment_size = tk.StringVar(value="1000")
        self.empty_document_id = tk.StringVar()  # 文档ID
        self.empty_document_name = None
        self.upload_in_progress = False
        self.file_content = None  # 存储读取的文件内容

        # 创建界面
        self.create_widgets()

    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="API配置", padding="10")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        # 访问地址
        ttk.Label(config_frame, text="访问地址:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.api_base_url, width=50, font=self.font).grid(row=0, column=1, sticky=tk.W, pady=5)

        # 访问密钥
        ttk.Label(config_frame, text="访问密钥:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.api_key, width=50, show="*", font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)

        # 知识库ID
        ttk.Label(config_frame, text="知识库ID:", font=self.font).grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(config_frame, textvariable=self.dataset_id, width=50, font=self.font).grid(row=2, column=1, sticky=tk.W, pady=5)
      
        # 文档信息区域
        doc_info_frame = ttk.LabelFrame(main_frame, text="文档信息", padding="10")
        doc_info_frame.pack(fill=tk.X, pady=(0, 10))

        # 文档选择区域
        ttk.Label(doc_info_frame, text="本地文件:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(doc_info_frame, textvariable=self.selected_file, width=50, font=self.font).grid(row=0, column=1, sticky=tk.W, pady=5)
        ttk.Button(doc_info_frame, text="浏览文件", command=self.browse_file, width=10).grid(row=0, column=2, padx=10, pady=5)

        # 空文档ID
        ttk.Label(doc_info_frame, text="文档ID:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(doc_info_frame, textvariable=self.empty_document_id, width=50, font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Button(doc_info_frame, text="创建", command=self.start_upload_empty_document).grid(row=1, column=2, padx=5, pady=5)

        # 分段设置区域
        segment_frame = ttk.LabelFrame(main_frame, text="分段设置", padding="10")
        segment_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(segment_frame, text="父分段分隔符:", font=self.font).grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(segment_frame, textvariable=self.segment_delimiter, width=20, font=self.font).grid(row=0, column=1, sticky=tk.W, pady=5)
        ttk.Label(segment_frame, text="父分段块大小:", font=self.font).grid(row=0, column=2, sticky=tk.W, pady=5)
        ttk.Entry(segment_frame, textvariable=self.segment_size, width=20, font=self.font).grid(row=0, column=3, sticky=tk.W, pady=5)

        ttk.Label(segment_frame, text="子分段分隔符:", font=self.font).grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(segment_frame, textvariable=self.child_segment_delimiter, width=20, font=self.font).grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(segment_frame, text="子分段块大小", font=self.font).grid(row=1, column=2, sticky=tk.W, pady=5)
        ttk.Entry(segment_frame, textvariable=self.child_segment_size, width=20, font=self.font).grid(row=1, column=3, sticky=tk.W, pady=5)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        # 上传分段按钮
        self.upload_segments_btn = ttk.Button(button_frame, text="上传分段", command=self.start_upload_segments, width=15)
        self.upload_segments_btn.pack(side=tk.LEFT, padx=5)

        # 取消按钮
        self.cancel_btn = ttk.Button(button_frame, text="取消", command=self.cancel_operation, width=10, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=self.font, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # 进度条
        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(10, 0))

    def browse_file(self):
        filename = filedialog.askopenfilename(
            filetypes=[("Markdown文件", "*.md"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
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

    def start_upload_empty_document(self):
        # 验证输入
        if not self.api_base_url.get().strip():
            messagebox.showerror("错误", "请输入访问地址")
            return
        if not self.dataset_id.get().strip():
            messagebox.showerror("错误", "请输入知识库ID")
            return
        if not self.api_key.get().strip():
            messagebox.showerror("错误", "请输入访问密钥")
            return

        # 禁用按钮
        self.cancel_btn.config(state=tk.NORMAL)
        self.upload_in_progress = True
        self.progress['value'] = 0

        # 在新线程中执行上传空文档
        threading.Thread(target=self.upload_empty_document, daemon=True).start()

    def start_upload_segment_document(self):
        # 验证输入
        if not self.api_base_url.get().strip():
            messagebox.showerror("错误", "请输入访问地址")
            return
        if not self.dataset_id.get().strip():
            messagebox.showerror("错误", "请输入知识库ID")
            return
        if not self.api_key.get().strip():
            messagebox.showerror("错误", "请输入访问密钥")
            return
        if not self.selected_file.get().strip() or self.file_content is None:
            messagebox.showerror("错误", "请选择并读取要上传的文件")
            return

        # 禁用按钮
        self.upload_segments_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.upload_in_progress = True
        self.progress['value'] = 0

        # 在新线程中执行上传分段文档
        threading.Thread(target=self.upload_segment_document, daemon=True).start()

    def start_upload_segments(self):
        self.log("开始上传空文档...")
        # 验证输入
        if not self.empty_document_id.get().strip():
            messagebox.showerror("错误", "请先上传文档获取文档ID或手动指定文档ID")
            return
        if not self.file_content:
            messagebox.showerror("错误", "文件内容为空，请重新选择文件")
            return

        # 禁用按钮
        self.upload_segments_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.upload_in_progress = True
        self.progress['value'] = 0

        # 在新线程中执行上传分段
        threading.Thread(target=self.upload_segments, daemon=True).start()

    def cancel_operation(self):
        self.upload_in_progress = False
        self.log("用户取消了操作")
        self.cancel_btn.config(state=tk.DISABLED)

    def upload_empty_document(self):
        try:
            self.log("开始上传空文档...")
            # 创建空文档API调用
            url = f"{self.api_base_url.get().rstrip('/')}/v1/datasets/{self.dataset_id.get()}/document/create-by-text"
            headers = {
                'Authorization': f'Bearer {self.api_key.get()}',
                'Content-Type': 'application/json'
            }
            # 空文档内容设为空字符串
            payload = {
                "name": self.empty_document_name,
                "text": "",
                "indexing_technique": "high_quality",
                "doc_form":"hierarchical_model",
                "doc_language": "Chinese Simplified",
                "embedding_model": "qwen3-embedding-8b-vllm",
                "embedding_model_provider": "langgenius/gpustack/gpustack",
                "process_rule": {
                    "mode": "hierarchical",
                    "rules": {
                        "parent_mode": "paragraph",
                        "pre_processing_rules": [
                            {"id": "remove_extra_spaces", "enabled": True},
                            {"id": "remove_urls_emails", "enabled": True}
                        ],
                        "segmentation": {
                            "separator": self.segment_delimiter.get().strip(),
                            "max_tokens": 2000
                        },
                        "subchunk_segmentation ": {
                            "separator": self.child_segment_delimiter.get().strip(),
                            "max_tokens": 1000
                        }
                    }
                },
                "retrieval_model": {
                    "reranking_enable": True,
                    "reranking_mode": "reranking_model",
                    "reranking_model": {"reranking_provider_name": "langgenius/gpustack/gpustack", "reranking_model_name": "bge-reranker-v2-m3"},
                    "score_threshold": 0,
                    "score_threshold_enabled": False,
                    "search_method": "hybrid_search",
                    "top_k": 8,
                    "weight":{
                        "weight_type": "customized",
                        "keyword_setting": {
                            "keyword_weight": 0.3
                        },
                        "vector_setting": {
                            "vector_weight": 0.7,
                            "embedding_model_name": "qwen3-embedding-8b-vllm",
                            "embedding_provider_name": "langgenius/gpustack/gpustack"
                        }
                    }
                }
            }
            print('payload',payload)
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            self.log(f"创建空文档请求状态码: {response.status_code}")
            self.progress['value'] = 50

            if response.status_code == 200:
                result = response.json()
                if 'document' in result and 'id' in result['document']:
                    document_id = result['document']['id']
                    self.empty_document_id.set(document_id)
                    self.log(f"空文档上传成功，ID: {document_id}")
                    self.progress['value'] = 100
                    messagebox.showinfo("成功", f"空文档上传成功！\n文档ID: {document_id}")
                else:
                    self.log(f"创建空文档响应不包含ID: {result}")
                    messagebox.showerror("错误", "创建空文档响应不包含ID")
            else:
                self.log(f"创建空文档失败: {response.text}")
                messagebox.showerror("错误", f"创建空文档失败: {response.text}")

        except Exception as e:
            self.log(f"上传空文档过程中发生错误: {str(e)}")
            messagebox.showerror("错误", f"上传空文档过程中发生错误: {str(e)}")
        finally:
            self.upload_in_progress = False
            if self.empty_document_id.get().strip():
                self.upload_segments_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)

    def upload_segments(self):
        try:
            self.log("开始处理分段上传...")
            document_id = self.empty_document_id.get()

            # 分割内容为段落
            self.log("正在分割文档内容...")
            delimiter = self.segment_delimiter.get()
            segments = self.file_content.split(delimiter)
            segments = [seg.strip() for seg in segments if seg.strip()]
            self.log(f"成功分割出 {len(segments)} 个段落")
            self.progress['value'] = 10

            if not segments:
                self.log("没有可上传的分段内容")
                messagebox.showwarning("警告", "没有可上传的分段内容")
                return

            if not self.upload_in_progress:
                return

            # 上传分段
            self.log("开始上传分段...")
            success_count = 0
            for i, segment in enumerate(segments):
                if not self.upload_in_progress:
                    break
                self.log(f"上传第 {i+1}/{len(segments)} 个分段...")
                if self.upload_single_segment(document_id, segment, i+1):
                    success_count += 1
                # 更新进度
                progress_value = 10 + int(80 * (i+1) / len(segments))
                self.progress['value'] = min(progress_value, 90)

            if not self.upload_in_progress:
                return

            self.log(f"分段上传完成，成功: {success_count}/{len(segments)}")
            self.progress['value'] = 100

            if success_count == len(segments):
                messagebox.showinfo("成功", "所有分段上传完成！")
            else:
                messagebox.showwarning("部分成功", f"分段上传完成，但部分失败: {success_count}/{len(segments)}")

        except Exception as e:
            self.log(f"处理分段上传时发生错误: {str(e)}")
            messagebox.showerror("错误", f"处理分段上传时发生错误: {str(e)}")
        finally:
            self.upload_in_progress = False
            self.upload_segments_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)

    def upload_single_segment(self, document_id, content, position):
        try:
            url = f"{self.api_base_url.get().rstrip('/')}/v1/datasets/{self.dataset_id.get()}/documents/{document_id}/segments"
            headers = {
                'Authorization': f'Bearer {self.api_key.get()}',
                'Content-Type': 'application/json'
            }
            payload = {
                "segments": [{
                    "content": content,
                    "answer": "",
                    "position": position
                }]
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                self.log(f"分段 {position} 上传成功")
                return True
            else:
                self.log(f"分段 {position} 上传失败，状态码: {response.status_code}, 响应: {response.text}")
                return False
        except Exception as e:
            self.log(f"分段 {position} 上传时发生错误: {str(e)}")
            return False

if __name__ == "__main__":
    root = tk.Tk()
    app = KnowledgeBaseUploader(root)
    root.mainloop()