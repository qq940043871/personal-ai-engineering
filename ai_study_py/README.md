# p000_ai_study_py — AI 学习工程

个人 AI 学习与实践工程：大模型框架学习代码、成型的应用项目、独立小工具和学习资料。

## 目录结构

```
p000_ai_study_py/
├── 10_docs/            # 学习手册与资料
│   ├── quick_guide/    #   各技术栈快速学习手册（Dify、LangChain、Qwen、向量数据库等）
│   ├── ragflow/        #   RAGFlow 部署过程截图记录
│   └── prompts/        #   提示词集合（SQL、DeepSeek、模板引擎）
│
├── 20_learn/           # 框架/主题学习代码
│   ├── pytorch/        #   PyTorch：感知机、手写 autograd、CNN、迁移学习
│   ├── paddle/         #   百度 PaddlePaddle（LeNet、图像分类训练）
│   ├── paddlex/        #   PaddleX：OCR、图像分类、目标检测、表格识别
│   ├── huggingface/    #   HF 生态：GPT2 微调/蒸馏、MinerU、表格检测
│   ├── modelscope/     #   ModelScope：动物识别、OCR、MinerU
│   ├── langchain/      #   LangChain：多智能体、RAG 服务、行业 Agent 示例
│   ├── dify/           #   Dify：工作流笔记 + 知识库上传工具（dify/、python/、ragflow/）
│   ├── ollama_rag/     #   Ollama 本地大模型：多轮对话、RAG、向量库集成
│   ├── ffmpeg_opencv/  #   FFmpeg / OpenCV 视频处理
│   ├── ocr/            #   PaddleOCR 文字识别
│   └── openMNT/        #   ModelScope NLLB 中英翻译模型
│
├── 30_slides/          # HTML 课件
│   ├── llm_base10/     #   大模型基础 1.0
│   └── llm_base20/     #   大模型基础 2.0
│
├── 40_projects/        # 成型的项目
│   ├── doubao/         #   豆包/火山方舟：图片视频生成脚本、抖音视频 Agent（douyin_agent/）、PDF 合同比对工具（pdf_diff/）
│   ├── self_media/     #   自媒体：公众号文章生成 Agent、B站/抖音素材、选题整理
│   ├── time_task/      #   定时视频生成任务（方舟 API 批量生成）
│   └── game/           #   小游戏：贪吃蛇、熊猫射击（PyInstaller 打包）
│
├── 50_tools/           # 独立小工具
│   ├── utils/          #   抖音/B站视频下载、WSET 导入、币种列表、批量重命名、Gitee 批量删除等
│   └── ops/            #   运维脚本：JVM 诊断、目录扫描
│
├── db/                 # [运行数据] Chroma 向量库（04_ollama_rag 脚本使用，勿随意移动）
├── vector_db/          # [运行数据] LangChain RAG 向量库（03_langchain 脚本使用）
└── output/             # [运行数据] 各脚本输出（已被 gitignore）
```

## 约定

- 顶层目录按用途分类，编号留出扩展空间（60+、70+ 可继续加分类）。
- `db/`、`vector_db/`、`output/` 是脚本以相对路径读写的运行数据，保留在根目录；均已 gitignore。
- 下载的视频、模型权重、构建产物（build/dist）、`__pycache__` 均不入库。

## 已知问题

- 部分脚本内写死的绝对路径指向旧目录 `d:\ai_coder\p000_ai_study_py\...`（工程现已位于 `d:\ai_person\p000_ai_study_py`），运行前需按脚本内提示改为当前路径或改为相对路径。

## 历史路径对照（2026-10 整理）

| 原路径 | 新路径 |
|---|---|
| 00_quick_guide | 10_docs/quick_guide |
| 04_ragflow_rag | 10_docs/ragflow |
| 10_提示词 | 10_docs/prompts |
| 01_huggingface / 01_modelscope / 01_llamafactory | 20_learn/huggingface / modelscope /（空，已删） |
| 02_pytorch / 02_paddle / 02_paddlex | 20_learn/pytorch / paddle / paddlex |
| 02_dify / 03_langchain / 04_ollama_rag | 20_learn/dify / langchain / ollama_rag |
| 05_ffmpge_opencv（拼写修正） | 20_learn/ffmpeg_opencv |
| 12_ocr / 12_openMNT | 20_learn/ocr / openMNT |
| 01_llm_base10 / 01_llm_base20 | 30_slides/llm_base10 / llm_base20 |
| 07_doubao | 40_projects/doubao（PDF 比对工具移入 pdf_diff/） |
| 00_self_media / 00_time_task / 08_game | 40_projects/self_media / time_task / game |
| 00_utils / 11运维工具 | 50_tools/utils / ops |
| dir / distilled_model / finetuned_gpt2 / models（均为空） | 已删除 |
