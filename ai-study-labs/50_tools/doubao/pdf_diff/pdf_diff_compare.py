import os
from openai import OpenAI

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    print("警告: PyPDF2未安装，将使用简单文本提取方式")
    print("安装命令: pip install PyPDF2")

class PDFDiffComparer:
    def __init__(self, api_key=None):
        """
        初始化PDF比对器
        :param api_key: 火山引擎ARK API Key，若不传则从环境变量ARK_API_KEY获取
        """
        self.api_key = api_key or os.environ.get("ARK_API_KEY")
        if not self.api_key:
            raise ValueError("ARK_API_KEY 未设置，请通过参数传入或设置环境变量")
        
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=self.api_key
        )
    
    def extract_text_from_pdf(self, pdf_path):
        """
        从PDF文件提取文本内容
        :param pdf_path: PDF文件路径
        :return: 提取的文本内容
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"文件不存在: {pdf_path}")
        
        print(f"正在提取PDF文本: {pdf_path}")
        text_content = ""
        
        if PYPDF2_AVAILABLE:
            try:
                with open(pdf_path, "rb") as file:
                    reader = PyPDF2.PdfReader(file)
                    for page_num, page in enumerate(reader.pages):
                        try:
                            page_text = page.extract_text() or ""
                            text_content += f"\n--- 第 {page_num + 1} 页 ---\n"
                            text_content += page_text
                        except Exception as e:
                            print(f"警告: 第 {page_num + 1} 页提取失败: {e}")
            except Exception as e:
                print(f"PyPDF2提取失败，尝试读取原始内容: {e}")
                # 如果PyPDF2失败，尝试二进制读取
                try:
                    with open(pdf_path, "rb") as f:
                        content = f.read()
                        text_content = f"[PDF文件内容（二进制）: 大小 {len(content)} 字节]"
                except:
                    text_content = "[无法提取PDF内容]"
        else:
            # 如果没有PyPDF2，尝试读取为文件
            try:
                with open(pdf_path, "rb") as f:
                    content = f.read()
                    text_content = f"[PDF文件: 大小 {len(content)} 字节]"
            except:
                text_content = "[无法读取PDF文件]"
        
        print(f"文本提取完成，长度: {len(text_content)} 字符")
        return text_content
    
    def compare_pdf_files(self, pdf_path1, pdf_path2, model="doubao-seed-2-0-lite-260215"):
        """
        比对两个PDF文件的差异
        :param pdf_path1: 第一个PDF文件路径
        :param pdf_path2: 第二个PDF文件路径
        :param model: 使用的模型，默认使用doubao-seed-2-0-lite-260215
        :return: 比对结果和token消耗信息
        """
        # 提取两个PDF的文本内容
        text1 = self.extract_text_from_pdf(pdf_path1)
        text2 = self.extract_text_from_pdf(pdf_path2)
        
        # 构建提示词
        prompt = f"""请详细比对以下两份合同文档的差异。

【合同版本A - {os.path.basename(pdf_path1)}】
{text1[:15000]}...

【合同版本B - {os.path.basename(pdf_path2)}】
{text2[:15000]}...

请输出格式如下：

## 合同差异比对报告

### 1. 内容差异
请逐条列出两份合同之间的实质性内容差异，包括：
- 修改的条款内容
- 新增的条款
- 删除的条款
- 数值变更（金额、日期、数量等）

### 2. 文档对比摘要
- 两个版本的核心差异点
- 主要变更的性质（内容/格式/其他）

### 3. 风险提示
请指出可能存在的法律风险或重要变更

请以清晰、结构化的方式呈现差异。"""
        
        # 调用模型进行比对
        print("\n正在调用模型进行差异比对...")
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            stream=True
        )
        
        # 收集响应结果
        result_text = ""
        usage_info = None
        
        print("\n=== 比对结果 ===")
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="")
                result_text += content
        
        # 获取usage信息
        try:
            # 非流式响应获取usage
            if hasattr(response, 'usage') and response.usage:
                usage_info = response.usage
            else:
                # 再次调用非流式以获取准确usage
                print("\n\n正在获取token消耗统计...")
                final_response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    stream=False
                )
                usage_info = final_response.usage
        except Exception as e:
            print(f"警告: 无法获取完整token统计: {e}")
            usage_info = None
        
        if usage_info:
            print("\n\n=== Token消耗统计 ===")
            print(f"输入token数: {usage_info.prompt_tokens}")
            print(f"输出token数: {usage_info.completion_tokens}")
            print(f"总token数: {usage_info.total_tokens}")
        
        return {
            "result": result_text,
            "usage": {
                "prompt_tokens": usage_info.prompt_tokens if usage_info else 0,
                "completion_tokens": usage_info.completion_tokens if usage_info else 0,
                "total_tokens": usage_info.total_tokens if usage_info else 0
            }
        }

def main():
    # 示例用法
    # 请先设置环境变量 ARK_API_KEY，或在下方直接传入api_key参数
    comparer = PDFDiffComparer(api_key=None)  # 使用环境变量
    
    try:
        # 获取当前脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_path1 = os.path.join(script_dir, "合同版本A.pdf")
        pdf_path2 = os.path.join(script_dir, "合同版本B.pdf")
        
        # 替换为您的两个PDF合同文件路径
        result = comparer.compare_pdf_files(
            pdf_path1=pdf_path1,
            pdf_path2=pdf_path2
        )
        
        # 保存结果到文件
        report_path = os.path.join(script_dir, "合同差异比对报告_pdfdiff.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result["result"])
        print(f"\n报告已保存到: {report_path}")
        
        # 打印token消耗详情
        print("\n=== 最终Token消耗 ===")
        print(f"输入Token: {result['usage']['prompt_tokens']}")
        print(f"输出Token: {result['usage']['completion_tokens']}")
        print(f"总计Token: {result['usage']['total_tokens']}")
        
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()