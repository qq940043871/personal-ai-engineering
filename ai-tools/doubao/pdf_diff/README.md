# PDF合同差异比对工具

基于火山引擎豆包大模型的PDF合同文件差异比对工具，能够提取两个PDF文档的文本内容，使用AI进行智能比对，并生成结构化的差异报告。

## 功能特性

- PDF文本提取（支持PyPDF2）
- AI智能比对文档差异
- 生成结构化Markdown报告
- 显示token消耗统计
- 流式输出实时查看结果

## 安装依赖

```bash
pip install -r requirements.txt
```

或者单独安装：

```bash
pip install openai PyPDF2
```

## 配置API Key

### 方式一：环境变量

```bash
# Windows
set ARK_API_KEY=your_api_key_here

# Linux/Mac
export ARK_API_KEY=your_api_key_here
```

### 方式二：代码中直接传入

```python
comparer = PDFDiffComparer(api_key="your_api_key_here")
```

## 获取API Key

1. 登录[火山引擎控制台](https://console.volcengine.com/ark)
2. 进入"API Key管理"
3. 创建新密钥并复制

## 使用方法

### 基本使用

```python
from pdf_diff_compare import PDFDiffComparer

# 初始化比对器
comparer = PDFDiffComparer()

# 比对两个PDF文件
result = comparer.compare_pdf_files(
    pdf_path1="合同版本A.pdf",
    pdf_path2="合同版本B.pdf",
    model="doubao-seed-2-0-lite-260215"
)

# 结果包含
# - result: 差异报告文本
# - usage: token消耗统计
```

### 命令行使用

修改代码中的文件路径，然后运行：

```bash
python pdf_diff_compare.py
```

## 输出说明

### 生成的报告结构

```markdown
## 合同差异比对报告

### 1. 内容差异
- 修改的条款内容
- 新增的条款
- 删除的条款
- 数值变更（金额、日期、数量等）

### 2. 文档对比摘要
- 两个版本的核心差异点
- 主要变更的性质

### 3. 风险提示
- 可能存在的法律风险或重要变更
```

### Token消耗统计

- `prompt_tokens`: 输入token数量
- `completion_tokens`: 输出token数量
- `total_tokens`: 总消耗token数量

## 支持的模型

- doubao-seed-2-0-lite-260215（推荐）
- doubao-seed-1-6-251015
- doubao-seed-2-0-pro-260215
- 其他火山引擎豆包系列模型

## 注意事项

1. 确保PDF文件内容是可提取的文本格式
2. 对于扫描版PDF，可能需要先进行OCR处理
3. 超长文档会自动截断（当前限制15000字符）
4. Token消耗与文档长度成正比

## 故障排除

### PyPDF2未安装

如果看到警告信息，安装PyPDF2：

```bash
pip install PyPDF2
```

### API Key错误

检查环境变量或代码中传入的API Key是否正确。

### 模型调用失败

确认模型已在火山引擎控制台开通服务。