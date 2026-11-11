import os
import requests
import json
from typing import Dict, Any, Optional


class ContractComparison:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ARK_API_KEY")
        if not self.api_key:
            raise ValueError("ARK_API_KEY 未设置，请通过参数传入或设置环境变量")
        
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
    
    def _get_headers(self, content_type: str = "application/json") -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers
    
    def get_file_status(self, file_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/files/{file_id}"
        
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"获取文件状态失败: {e}")
            return None
    
    def wait_for_file_ready(self, file_id: str, max_wait: int = 120, check_interval: int = 5) -> bool:
        print(f"等待文件处理完成: {file_id}")
        
        import time
        waited = 0
        
        while waited < max_wait:
            status_result = self.get_file_status(file_id)
            if status_result:
                status = status_result.get("status")
                print(f"  当前状态: {status} (已等待 {waited}s)")
                
                if status in ["processed", "active"]:
                    print(f"文件 {file_id} 已就绪 (状态: {status})")
                    return True
                elif status == "error":
                    print(f"文件 {file_id} 处理失败")
                    return False
            
            time.sleep(check_interval)
            waited += check_interval
        
        print(f"等待超时 ({max_wait}s)")
        return False
    
    def upload_file(self, file_path: str, purpose: str = "user_data", wait_ready: bool = True) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/files"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        print(f"正在上传文件: {os.path.basename(file_path)}")
        
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f),
                "purpose": (None, purpose)
            }
            
            try:
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files
                )
                response.raise_for_status()
                result = response.json()
                file_id = result.get("id")
                print(f"文件上传成功，file_id: {file_id}")
                
                if wait_ready:
                    if not self.wait_for_file_ready(file_id):
                        print(f"文件 {file_id} 未能成功处理")
                        return None
                
                return result
            except requests.exceptions.RequestException as e:
                print(f"文件上传失败: {e}")
                if hasattr(e.response, 'text'):
                    print(f"错误详情: {e.response.text}")
                return None
    
    def extract_text_from_file(self, file_id: str, model: str = "doubao-seed-2-0-lite-260215") -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/responses"
        
        data = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": file_id
                        },
                        {
                            "type": "input_text",
                            "text": "按段落给出文档中的文字内容，以JSON格式输出，包括段落类型（type）、文字内容（content）信息。"
                        }
                    ]
                }
            ]
        }
        
        print(f"正在提取文本内容，file_id: {file_id}")
        
        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            result = response.json()
            
            usage = result.get("usage", {})
            self.total_prompt_tokens += usage.get("prompt_tokens", 0)
            self.total_completion_tokens += usage.get("completion_tokens", 0)
            
            print(f"文本提取完成，tokens: prompt={usage.get('prompt_tokens', 0)}, completion={usage.get('completion_tokens', 0)}")
            return result
        except requests.exceptions.RequestException as e:
            print(f"文本提取失败: {e}")
            if hasattr(e.response, 'text'):
                print(f"错误详情: {e.response.text}")
            return None
    
    def compare_contracts(self, file_id_a: str, file_id_b: str, model: str = "doubao-seed-2-0-lite-260215") -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/responses"
        
        data = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": file_id_a
                        },
                        {
                            "type": "input_text",
                            "text": "这是合同版本A。"
                        },
                        {
                            "type": "input_file",
                            "file_id": file_id_b
                        },
                        {
                            "type": "input_text",
                            "text": """这是合同版本B。请详细比对这两份合同文档的差异。

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
                        }
                    ]
                }
            ]
        }
        
        print("\n正在调用模型进行合同比对...")
        
        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            result = response.json()
            
            usage = result.get("usage", {})
            self.total_prompt_tokens += usage.get("input_tokens", 0)
            self.total_completion_tokens += usage.get("output_tokens", 0)
            
            print(f"合同比对完成，tokens: input={usage.get('input_tokens', 0)}, output={usage.get('output_tokens', 0)}")
            return result
        except requests.exceptions.RequestException as e:
            print(f"合同比对失败: {e}")
            if hasattr(e.response, 'text'):
                print(f"错误详情: {e.response.text}")
            return None
    
    def parse_response_text(self, response: Dict[str, Any]) -> str:
        try:
            output = response.get("output", [])
            if output:
                for item in output:
                    if item.get("type") == "message":
                        content_list = item.get("content", [])
                        for content_item in content_list:
                            if content_item.get("type") == "output_text":
                                return content_item.get("text", "")
            
            return ""
        except Exception as e:
            print(f"解析响应文本失败: {e}")
            import traceback
            traceback.print_exc()
            return ""
    
    def run_comparison(self, pdf_path_a: str, pdf_path_b: str, model: str = "doubao-seed-2-0-lite-260215") -> Dict[str, Any]:
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        
        print("=" * 60)
        print("合同比对流程开始")
        print("=" * 60)
        
        file_a_result = self.upload_file(pdf_path_a)
        if not file_a_result:
            raise Exception("合同版本A上传失败")
        file_id_a = file_a_result.get("id")
        
        file_b_result = self.upload_file(pdf_path_b)
        if not file_b_result:
            raise Exception("合同版本B上传失败")
        file_id_b = file_b_result.get("id")
        
        print("\n" + "=" * 60)
        print("文件上传完成，开始合同比对")
        print("=" * 60)
        
        comparison_result = self.compare_contracts(file_id_a, file_id_b, model)
        if not comparison_result:
            raise Exception("合同比对失败")
        
        result_text = self.parse_response_text(comparison_result)
        
        total_tokens = self.total_prompt_tokens + self.total_completion_tokens
        
        print("\n" + "=" * 60)
        print("比对结果")
        print("=" * 60)
        print(result_text)
        
        print("\n" + "=" * 60)
        print("Token消耗统计")
        print("=" * 60)
        print(f"输入Token: {self.total_prompt_tokens}")
        print(f"输出Token: {self.total_completion_tokens}")
        print(f"总Token: {total_tokens}")
        
        return {
            "result_text": result_text,
            "file_id_a": file_id_a,
            "file_id_b": file_id_b,
            "usage": {
                "prompt_tokens": self.total_prompt_tokens,
                "completion_tokens": self.total_completion_tokens,
                "total_tokens": total_tokens
            }
        }


def main():
    comparer = ContractComparison(api_key=None)
    
    try:
        pdf_path_a = r"d:\ai_coder\p000_ai_study_py\07_doubao\合同版本A.pdf"
        pdf_path_b = r"d:\ai_coder\p000_ai_study_py\07_doubao\合同版本B.pdf"
        
        result = comparer.run_comparison(pdf_path_a, pdf_path_b)
        
        output_file = "合同差异比对报告.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result["result_text"])
        print(f"\n报告已保存到: {output_file}")
        
        token_output_file = "token消耗统计.json"
        with open(token_output_file, "w", encoding="utf-8") as f:
            json.dump(result["usage"], f, ensure_ascii=False, indent=2)
        print(f"Token统计已保存到: {token_output_file}")
        
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
