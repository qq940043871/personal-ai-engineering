# ai-study-labs — AI 学习工程

个人 AI 学习与实践工程：大模型框架学习代码、独立小工具与项目、学习资料。

## 目录结构

```
ai-study-labs/
├── 10_docs/            # 学习资料
│   └── prompts/        #   提示词集合（SQL、DeepSeek、模板引擎）
│
├── 20_learn/           # 框架/主题学习代码
│   ├── pytorch/        #   PyTorch：感知机、手写 autograd、CNN、迁移学习
│   ├── paddle/         #   百度 PaddlePaddle（LeNet、图像分类训练）
│   ├── paddlex/        #   PaddleX：OCR、图像分类、目标检测、表格识别
│   ├── huggingface/    #   HF 生态：GPT2 预训练/微调/全参训练/知识蒸馏
│   ├── modelscope/     #   ModelScope：动物识别、OCR、MinerU
│   ├── langchain/      #   LangChain：多智能体、RAG 服务、行业 Agent 示例
│   ├── ffmpeg_opencv/  #   FFmpeg / OpenCV 视频处理
│   ├── ocr/            #   PaddleOCR 文字识别
│   └── openMNT/        #   ModelScope NLLB 中英翻译模型
│
└── 50_tools/           # 独立小工具与项目
    ├── doubao/         #   豆包/火山方舟：图片视频生成脚本、抖音视频 Agent（douyin_agent/）、PDF 合同比对工具（pdf_diff/）
    ├── time_task/      #   定时视频生成任务（方舟 API 批量生成）
    ├── utils/          #   抖音/B站视频下载（01_/02_，产物就地存放不入库）、WSET 导入、币种列表、批量重命名、Gitee 批量删除等
    └── ops/            #   运维脚本：JVM 诊断、目录扫描
```

> 本地大模型相关实验（Ollama 多轮对话、搜索引擎、RAG）已迁出为工作区独立子项目 [ai-rag-ollama](../ai-rag-ollama/)。
> Dify / RAGFlow 知识库工具与笔记已迁出为 [ai-rag-dify](../ai-rag-dify/)（2026-10）。
> HTML 课件（大模型基础 1.0 / 2.0）已迁出为 [ai-study-note/slides](../ai-study-note/slides/)（2026-11）。
> 各技术栈快速学习手册（原 `10_docs/quick_guide/`）已迁出为 [ai-study-note/quick_guide](../ai-study-note/quick_guide/)（2026-11）。

## 约定

- 顶层目录按用途分类，编号留出扩展空间（60+、70+ 可继续加分类）。
- **代码与笔记入库，产物不入库**：`build/`、`dist/`、`temp_images/`、`video/`、模型权重（`pytorch/models/`）、数据集（`pytorch/data/`）、向量库与脚本输出目录均已被 `.gitignore` 覆盖；合同类 PDF（`pdf_diff/*.pdf`）与 `ops/` 下的诊断输出不入库。
- **运行产物不提交**：`ops/jvm_diag_*/`（jstack、top 等采集结果）、`pdf_diff/` 下的比对报告与 token 统计只留在本地。
- 子目录内布局：源码在根，笔记收进 `notes/`，打包用 `.spec` / `pipinstaller.bat` 随时可重建。

## 已知问题

- 部分脚本内写死的绝对路径指向旧目录（`d:\ai_coder\p000_ai_study_py\...` 等），运行前需按脚本内提示改为当前路径或改为相对路径。

## 历史路径对照（2026-10 整理）

| 原路径 | 新路径 |
|---|---|
| 00_quick_guide | 10_docs/quick_guide（2026-11 迁出 → ai-study-note/quick_guide/） |
| 04_ragflow_rag | 10_docs/ragflow |
| 10_提示词 | 10_docs/prompts |
| 01_huggingface / 01_modelscope / 01_llamafactory | 20_learn/huggingface / modelscope /（空，已删） |
| 02_pytorch / 02_paddle / 02_paddlex | 20_learn/pytorch / paddle / paddlex |
| 02_dify / 03_langchain | 20_learn/dify（2026-10 再迁出 → ai-rag-dify/）/ langchain |
| 04_ollama_rag | ai-rag-ollama（迁出为工作区独立子项目） |
| 05_ffmpge_opencv（拼写修正） | 20_learn/ffmpeg_opencv |
| 12_ocr / 12_openMNT | 20_learn/ocr / openMNT |
| 01_llm_base10 / 01_llm_base20 | 30_slides/llm_base10 / llm_base20（2026-11 迁出 → ai-study-note/slides/） |
| 07_doubao | 50_tools/doubao（PDF 比对工具移入 pdf_diff/；2026-11 由 40_projects/ 迁入） |
| 00_self_media / 00_time_task / 08_game | self_media、game 已删除；time_task → 50_tools/time_task（2026-11 由 40_projects/ 迁入） |
| 00_utils / 11运维工具 | 50_tools/utils / ops |
| dir / distilled_model / finetuned_gpt2 / models（均为空） | 已删除 |

### 2026-10-03 去重与归档

| 原路径 | 现状 |
|---|---|
| 20_learn/ollama_rag/ | 与 ai-rag-ollama 重复，已删除（`03_ollama_rag.ipynb` 移入 ai-rag-ollama/） |
| 20_learn/dify/ 根下 8 个笔记 md + demo.png | 收进 `20_learn/dify/notes/` |
| 20_learn/dify/process_segments.py | 移入 `20_learn/dify/python/`（与其他 dify API 脚本同处） |
| 20_learn/dify/1.md（空）、self_media 下空 txt | 已删除 |
| 40_projects/game/promot提示词（拼写错误） | `40_projects/game/prompts` |
| 50_tools/utils/04_获取币种列表 | `50_tools/utils/04_currency_list` |
| 各处 build/、dist/、temp_images/（可再生产物） | 已删除，需要时用 `.spec` / `pipinstaller.bat` 重新打包 |
