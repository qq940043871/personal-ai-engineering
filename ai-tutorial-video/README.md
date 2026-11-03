# ai-tutorial-video

AI 学习教程 → 视频生成管线：「HTML 场景动画 → 无头浏览器逐帧抓帧 → ffmpeg 合成 MP4」，支持 edge-tts 中文旁白。把仓库里 `ai-study-note/courses/`、`ai-study-note/slides/` 的教程内容变成连贯的学习视频。

## 一条命令出片

```bash
cd ai-tutorial-video
pip install -r requirements.txt
python -m playwright install chromium      # 首次；失败可自动回退系统 Edge/Chrome
python src/build_video.py --storyboard storyboards/llm_base10.json
# → output/llm_base10.mp4（1080p，含旁白）
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--dry-run` | 只打印分幕计划与时长，不渲染 |
| `--only s05,s06` | 只（重）渲染指定幕，其余用缓存片段 |
| `--force` | 忽略幕级缓存全部重渲染 |
| `--no-tts` | 跳过旁白（纯字幕动画） |
| `--fps 30` | 覆盖帧率（默认取剧本 meta.fps） |
| `--keep-frames` | 保留中间帧（调试用） |

## 管线流程

```
storyboards/*.json ──▶ tts.py(逐幕旁白MP3+测时长) ──▶ render.py(Playwright 逐帧截图)
                                                            │
       output/<id>.mp4 ◀── merge/concat ◀── encode.py(逐幕 ffmpeg 编码) ◀┘
```

- **剧本驱动**：`storyboards/*.json` 每幕一个对象，`type` 支持 `title / section / bullets / diagram / compare / code / quote / summary / end`，字段含文案、旁白、章节信息。
- **确定性动画**：`templates/scene.html` 所有动效由 `window.__render(t)` 按传入时间驱动，无随机数、无墙钟，逐帧可复现。
- **时长对齐**：幕时长 = max(剧本最短可读时长, 旁白时长 + 0.7s)；edge-tts 不可用时自动降级无声并警告。
- **幕级缓存**：每幕独立渲染编码为 `output/<id>/scenes/sNN.mp4`，重跑只补缺失幕，最后 concat 无重编码拼片。

## 从课程页生成新剧本

```bash
python src/extract_course.py ../ai-study-note/courses/llm/transformer.html \
    --out storyboards/transformer.json --id transformer
# 草稿（draft:true）建议人工润色旁白与要点后再 build
```

## 系列合并

```bash
python scripts/merge_series.py --inputs output/llm_base10.mp4 output/llm_base20.mp4 --out output/llm_base合集.mp4
```

## 目录结构

```
├── storyboards/          # 剧本 JSON（每部视频一份）
├── templates/scene.html  # 1920×1080 场景模板（暗色科技风，9 种幕类型）
├── src/                  # build_video 编排 / render 抓帧 / encode 编码 / tts 旁白 / extract_course 提取
├── scripts/merge_series.py
└── output/               # 帧缓存与成片（不入库）
```

> 渲染速度参考：1080p@24fps 约 8 帧/秒，8 分钟成片约 25 分钟渲染。
