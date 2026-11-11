# PPT / PPTX 演示文稿格式标准与解析完整指南

> 本文档与《PDF 格式标准与解析指南》配套，覆盖 PowerPoint 的开放标准背景、两代容器结构（二进制 vs OPC/ZIP 包）、幻灯片对象树、五种形状的判定方法、文本/图片/表格/图表/SmartArt 的提取方式、阅读顺序还原，以及实际解析策略与常见坑位。

---

## 一、PPT 是开放标准吗？

| 扩展名 | 格式名 | 本质 | 标准状态 |
|---|---|---|---|
| `.ppt` | PowerPoint 97-2003 Binary | **OLE2 复合文档**，二进制记录流 | 微软公开 **[MS-PPT]**，属"公开的私有格式" |
| `.pps` | 幻灯片放映 | 同 `.ppt` | 同上 |
| `.pptx` | PresentationML | **OOXML（ZIP + XML）** | **ECMA-376 / ISO/IEC 29500**，开放国际标准 |
| `.ppsx` | 放映（新版） | 同 `.pptx` | 同上 |
| `.pptm` | 带宏 | 同 `.pptx` + `vbaProject.bin` | 同上 |

| 时间 | 事件 |
|---|---|
| 1990s–2003 | 私有二进制格式（MS-PPT），靠逆向工程才能读 |
| 2006 | OOXML / ECMA-376 发布，`.pptx` 随 PowerPoint 2007 出现 |
| 2008 | 成为 **ISO/IEC 29500** |
| 2012 起 | `[MS-PPT]`、`[MS-ODRAW]` 等二进制规范公开 |

需要区分的一点：

1. **`.pptx` 的 schema 最"扁平"**：三大 OOXML 格式（Word / Excel / PPT）里，PresentationML 的**元素数量最少**，但**布局自由度最高** —— 文字不在好用的段落流里，而是散落在带坐标的"形状"里。
2. **`.ppt` 二进制规范里大量绘图结构是共用的**（`MS-ODRAW` 的 `OfficeArt` 记录），所以老 `.ppt` 的图形解析门槛比 `.doc` 还高。

因此做 PPT 解析，`.pptx` 可以纯基于公开规范开发；`.ppt` 建议一律先转换。

---

## 二、两代容器结构

### 1. `.pptx`：OPC 包（本质是 ZIP）

改后缀为 `.zip` 即可解开：

```text
a.pptx (ZIP)
├─ [Content_Types].xml
├─ _rels/.rels
├─ docProps/core.xml, app.xml      # 标题、作者、幻灯片数、字数
└─ ppt/
     ├─ presentation.xml           # ★ 幻灯片顺序、页面尺寸、母版列表
     ├─ _rels/presentation.xml.rels
     ├─ presProps.xml              # 放映设置
     ├─ viewProps.xml
     ├─ slides/
     │    ├─ slide1.xml            # ★ 每页的内容
     │    ├─ slide2.xml
     │    └─ _rels/slide1.xml.rels # rId → 图片/图表/备注
     ├─ slideLayouts/slideLayout1.xml  # 版式（占位符定义）
     ├─ slideMasters/slideMaster1.xml  # 母版（主题、页脚占位符）
     ├─ notesSlides/notesSlide1.xml    # ★ 备注页（讲稿）
     ├─ handoutMasters/
     ├─ theme/theme1.xml           # 配色与字体方案
     ├─ media/image1.png           # 图片、音视频
     ├─ charts/chart1.xml          # 图表数据
     ├─ diagrams/data1.xml         # ★ SmartArt 文本与层级
     ├─ embeddings/…xlsx           # 图表背后的嵌入表格
     ├─ commentAuthors.xml, comments/comment1.xml
     ├─ tags/                      # 自定义标签
     └─ tableStyles.xml
```

### 2. 三个最容易搞错的地方

| 现象 | 原因 |
|---|---|
| 幻灯片顺序与 `slide1.xml` 文件名不一致 | 顺序由 `presentation.xml` 的 `p:sldIdLst` 决定，文件名是创建顺序 |
| 母版/版式里的文字重复出现在每页 | 页脚、页码、日期来自母版占位符，不是页面内容 |
| 图表的数字在 `<c:numCache>` 里，不在单元格 | 图表是独立缓存，可能与源表格不一致 |

### 3. `.ppt`：二进制记录流

```text
a.ppt (OLE2 / CFB)
├─ PowerPoint Document      # 主记录流：Document 容器 → SlideListWithText → Slide
├─ Current User
├─ Pictures                  # 图片流
└─ SummaryInformation
```

记录结构：

```text
记录 = [2 字节 ver+instance][2 字节 type][4 字节 len][数据]

DocumentContainer
 ├─ SlideListWithText (SlidePersistAtom)   # ★ 幻灯片顺序
 ├─ Slide (SlideAtom + OfficeArt 绘图记录)
 │    ├─ PPT_PPDrawing → OfficeArtDgContainer → SpContainer
 │    │      ├─ OPT (文本属性：字体、字号、颜色)
 │    │      └─ TextCharsAtom / TextBytesAtom   # 文字（UTF-16 / 单字节）
 │    └─ SlideShowSlideInfoAtom
 └─ Notes
```

难点：

- 文字在 `TextCharsAtom`（UTF-16LE）或 `TextBytesAtom`（ANSI）里，**样式通过 `OPT` 属性 + `StyleTextPropAtom` 的 run 边界描述**，"哪段字是什么字号"需要按字符偏移对齐；
- 图形是 `OfficeArt` 记录，与 Word 的 VML 体系不同；
- `SlideListWithText` 可能只存"文本清单"而非完整页，需要交叉 `SlidePersistAtom`。

**实践结论：`.ppt` 一律先转 `.pptx`。**

```bash
soffice --headless --convert-to pptx --outdir out/ a.ppt
```

| 转换方案 | 优点 | 缺点 |
|---|---|---|
| LibreOffice `soffice` | 保真度较好、批量、跨平台 | SmartArt/复杂动画可能变形 |
| PowerPoint COM | 保真度最高 | 仅 Windows + 必装 Office，不能并发 |
| Aspose.Slides | 商业库，质量高 | 收费 |

---

## 三、幻灯片在对象树中的表示

### 1. 工作簿级：`presentation.xml`

```xml
<p:presentation>
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>   <!-- 母版 -->
  </p:sldMasterIdLst>
  <p:sldIdLst>                                      <!-- ★ 幻灯片顺序 -->
    <p:sldId id="256" r:id="rId2"/>                 <!-- → slides/slide1.xml -->
    <p:sldId id="257" r:id="rId3"/>
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>             <!-- 16:9，单位 EMU -->
  <p:notesSz cx="6858000" cy="9144000"/>            <!-- 备注页尺寸 -->
</p:presentation>
```

`p:sldSz` 决定画布尺寸：

| 比例 | cx × cy（EMU） | 英寸 |
|---|---|---|
| 4:3 | 9144000 × 6858000 | 10 × 7.5 |
| 16:9 | 12192000 × 6858000 | 13.33 × 7.5 |
| A4 竖版 | 7560310 × 10692130 | 8.27 × 11.69 |

### 2. 页面级：`slides/slideN.xml`

```text
p:sld
├─ p:cSld
│    └─ p:spTree                     # ★ 形状树（所有内容都在这里）
│         ├─ p:nvGrpSpPr             # 树的 id/name
│         ├─ p:grpSpPr               # 树的坐标变换
│         ├─ p:sp                    # 形状 / 占位符 / 文本框
│         ├─ p:pic                   # 图片
│         ├─ p:graphicFrame          # 表格 / 图表 / SmartArt
│         ├─ p:grpSp                 # 组合
│         └─ p:cxnSp                 # 连接线
├─ p:clrMapOvr                       # 配色覆盖
├─ p:transition                      # 切换效果
└─ p:timing                          # 动画时间轴
```

关键点：

- **`p:spTree` 只有一个**，但可以嵌套 `p:grpSp`；
- `p:spTree` 的子元素顺序**就是 Z 序**（后画的盖前面的），**不是阅读顺序**；
- 每页的 `r:id` 指向 `slides/_rels/slideN.xml.rels`，再定位图片/图表/备注；
- 隐藏页在 `p:sld @show="0"`。

### 3. 形状的通用骨架

所有形状都遵循"三段式"：

```xml
<p:sp>
  <p:nvSpPr>                          <!-- ① 非可视属性 -->
    <p:cNvPr id="2" name="标题 1" descr="替代文字"/>
    <p:cNvSpPr/>
    <p:nvPr><p:ph type="title"/></p:nvPr>   <!-- 占位符类型 -->
  </p:nvSpPr>
  <p:spPr>                            <!-- ② 几何与样式 -->
    <a:xfrm><a:off x="838200" y="365125"/><a:ext cx="10515600" cy="1325563"/></a:xfrm>
    <a:prstGeom prst="rect"/>
  </p:spPr>
  <p:txBody>                          <!-- ③ 文本（sp 才有） -->
    <a:bodyPr/><a:lstStyle/>
    <a:p><a:r><a:t>标题文字</a:t></a:r></a:p>
  </p:txBody>
</p:sp>
```

坐标单位是 **EMU（English Metric Unit）**：

| 换算 | 值 |
|---|---|
| 1 英寸 | 914400 EMU |
| 1 厘米 | 360000 EMU |
| 1 磅 | 12700 EMU |
| 1 EMU | 1/914400 英寸 |

---

## 四、五种形状类型与判定方法

`p:spTree` 下只有五种元素，判型非常直接：

| 元素 | 类型 | 内部关键元素 | 是否含文本 |
|---|---|---|---|
| `p:sp` | 形状 / 占位符 / 文本框 | `p:txBody` | **是**（`a:t`） |
| `p:pic` | 图片 | `p:blipFill/a:blip @r:embed` | 否（有 `descr` 替代文字） |
| `p:graphicFrame` | 表格 / 图表 / SmartArt / OLE | `a:graphicData @uri` | 部分（表格有） |
| `p:grpSp` | 组合 | 子 `spTree` | 递归 |
| `p:cxnSp` | 连接线 / 箭头 | 无 `txBody` | 否 |

### 1. 判定 `p:sp` 是不是"占位符"

```xml
<p:nvPr>
  <p:ph type="title"  idx="0"/>      <!-- 有 p:ph 就是占位符 -->
</p:nvPr>
```

常见 `p:ph @type`：

| type | 含义 |
|---|---|
| `title` / `ctrTitle` | 标题 / 居中大标题（封面） |
| `subTitle` | 副标题 |
| `body` | 正文内容区 |
| `dt` | 日期 |
| `ftr` | 页脚 |
| `sldNum` | 幻灯片编号 |
| `pic` / `clipArt` | 图片占位符 |
| `tbl` / `chart` / `dgm` / `media` | 表格/图表/结构图/媒体占位符 |
| `hdr` | 页眉 |

未声明 `p:ph` 的 `p:sp` 就是**自由文本框/形状**（用户手绘的方框），这类形状的文字最容易被误判。

### 2. 判定 `p:graphicFrame` 装的是什么

看 `a:graphicData @uri`：

| uri 结尾 | 内容 |
|---|---|
| `/table` | 表格（`a:tbl`） |
| `/chart` | 图表（`c:chart @r:id` → `ppt/charts/chartN.xml`） |
| `/diagram` | SmartArt（`dgm:relIds` → `ppt/diagrams/dataN.xml`） |
| `/ole` | 嵌入 OLE 对象 |

### 3. 用 python-pptx 快速分类

```python
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

def scan(path):
    prs = Presentation(path)
    for i, slide in enumerate(prs.slides, 1):
        print(f"--- 第 {i} 页 ---")
        for sh in slide.shapes:
            kind = sh.shape_type
            label = {
                MSO_SHAPE_TYPE.AUTO_SHAPE: "shape",
                MSO_SHAPE_TYPE.TEXT_BOX: "textbox",
                MSO_SHAPE_TYPE.PICTURE: "picture",
                MSO_SHAPE_TYPE.TABLE: "table",
                MSO_SHAPE_TYPE.CHART: "chart",
                MSO_SHAPE_TYPE.GROUP: "group",
                MSO_SHAPE_TYPE.PLACEHOLDER: "placeholder",
            }.get(kind, str(kind))
            text = sh.text_frame.text if sh.has_text_frame else ""
            print(f"  [{label}] name={sh.name!r} text={text[:40]!r}")
```

注意 `python-pptx` **不会把 SmartArt 暴露为 shape**（它在 `graphicFrame` 里但不是 table/chart），需要手动解 `dgm:data1.xml`。

---

## 五、文本怎么存

### 1. 段落与 run

```xml
<p:txBody>
  <a:bodyPr wrap="square" anchor="ctr">
    <a:normAutofit fontScale="92500" lnSpcReduction="20000"/>  <!-- 自动缩小 -->
  </a:bodyPr>
  <a:lstStyle/>
  <a:p>
    <a:pPr lvl="0" algn="l" marL="342900" indent="-342900">
      <a:buChar char="•"/>                 <!-- 项目符号 -->
    </a:pPr>
    <a:r>
      <a:rPr lang="zh-CN" sz="1800" b="1">  <!-- 18pt 加粗 -->
        <a:solidFill><a:srgbClr val="C00000"/></a:solidFill>
        <a:latin typeface="Arial"/><a:ea typeface="微软雅黑"/>
      </a:rPr>
      <a:t>合格率</a:t>
    </a:r>
    <a:r><a:rPr sz="1800"/><a:t> 98.6%</a:t></a:r>
    <a:br/>                                <!-- 软换行 -->
  </a:p>
</p:txBody>
```

| 层级 | 元素 | 说明 |
|---|---|---|
| 文本框属性 | `a:bodyPr` | 换行方式、垂直锚点、内边距、分栏（`a:numCol`）、竖排（`vert="eaVert"`） |
| 自动缩放 | `a:normAutofit` / `a:spAutoFit` / `a:noAutofit` | `fontScale` 是**实际渲染字号**，与 `sz` 不同 |
| 段落 | `a:p` | 一个段落 |
| 段落属性 | `a:pPr` | `lvl`（0–8 层级）、`algn`、`marL`/`indent`（EMU）、`buChar`/`buAutoNum`/`buNone` |
| run | `a:r` | 同样式文字片段 |
| 字符属性 | `a:rPr` | `sz`（**百分之一磅**，`1800`=18pt）、`b`、`i`、`u`、`solidFill`、`latin`/`ea`/`cs` |
| 文字 | `a:t` | **唯一承载字符的元素** |
| 换行 | `a:br` | 段内硬换行 |
| 域 | `a:fld` | 页码（`slidenum`）、日期时间 |
| 制表 | `a:tab` | 制表位 |

### 2. `lvl` 不是列表，是缩进级别

`a:pPr @lvl="0..8"` 表示大纲层级，配合 `a:buChar`/`a:buAutoNum` 形成"看起来是列表"的效果。**没有 `numId`，没有全局编号表**，所以：

- 数字序号（1. 2. 3.）通常是 `buAutoNum type="arabicPeriod"`，**序号由渲染器按同级段落顺序生成**；
- 要还原"1. 2. 3."，必须自己按 `lvl` 分组累计；
- `buNone` 表示无符号，`buChar char="▪"` 是自定义符号。

### 3. 文本继承链

和 Word 一样有层层覆盖，但这里更容易出错，因为**占位符的文本属性定义在 layout / master 上**：

```text
theme1.xml / a:fontScheme        # 主题字体（majorFont/minorFont）
      ↓
slideMaster1.xml / p:txStyles    # 母版文本样式（titleStyle/bodyStyle/otherStyle，按 lvl）
      ↓
slideLayoutN.xml                 # 版式对占位符的覆盖
      ↓
slide 内 p:sp/a:lstStyle         # 形状级覆盖
      ↓
a:p/a:pPr + a:r/a:rPr            # 段落/run 级直接格式（最优先）
```

实用结论：

- 只读 `slideN.xml` 会**丢掉大部分视觉字号与字体**（很多 run 根本没有 `sz`）；
- 要判断"这是标题"，看 `p:ph @type="title"|"ctrTitle"` 比看字号可靠得多；
- 同一份 PPT 的"标题字号"可能来自母版，抽取时不必强求还原视觉值。

### 4. 自动缩放会骗人

```xml
<a:bodyPr><a:normAutofit fontScale="80000"/></a:bodyPr>
```

`fontScale="80000"` 表示**渲染时缩小到 80%**，而 `a:rPr @sz="2400"` 写的是 24pt。所以：

- 你看到的字号 = `sz × fontScale%`；
- 文本溢出的页面，字号会被压小，抽取时应记住"这页文字很多"。

---

## 六、图片、表格、图表、SmartArt

这四类是非文本载体，各自的提取方式完全不同。

### 1. 图片

```xml
<p:pic>
  <p:nvPicPr>
    <p:cNvPr id="5" name="图片 4" descr="2024年销售额趋势图"/>   <!-- 替代文字 -->
  </p:nvPicPr>
  <p:blipFill>
    <a:blip r:embed="rId3"/>                                       <!-- → media/image3.png -->
    <a:srcRect l="10000" t="0" r="10000" b="0"/>                   <!-- 裁剪 10% -->
  </p:blipFill>
  <p:spPr><a:xfrm>…</a:xfrm></p:spPr>
</p:pic>
```

| 要点 | 说明 |
|---|---|
| 图片文件 | 在 `ppt/media/`，靠 `r:embed` 的 `rId` → `.rels` 定位 |
| 替代文字 | `p:cNvPr @descr`，是最省事的图片描述来源 |
| 裁剪 | `a:srcRect` 四边百分比（1/1000 %），提取原图时不需处理 |
| 填充为图片的形状 | `p:sp` 的 `p:spPr/a:blipFill`，**不是 `p:pic`**，容易漏 |
| 背景图 | 在 `p:cSld/p:bg/p:bgPr/a:blipFill`，很容易漏 |

无 `descr` 的图片只能走 OCR / 视觉模型。

### 2. 表格

```xml
<a:tbl>
  <a:tblGrid><a:gridCol w="2032000"/><a:gridCol w="2032000"/></a:tblGrid>
  <a:tr h="370840">
    <a:tc gridSpan="2"><a:txBody><a:p><a:r><a:t>合计</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>
    <a:tc hMerge="1"><a:txBody><a:p/></a:txBody></a:tc>   <!-- 被合并的空格 -->
  </a:tr>
  <a:tr h="370840">
    <a:tc rowSpan="2"><a:txBody><a:p><a:r><a:t>华东</a:t></a:r></a:p></a:txBody></a:tc>
    <a:tc vMerge="1"><a:txBody><a:p/></a:txBody></a:tc>
  </a:tr>
</a:tbl>
```

| 合并方式 | 属性 | 表现 |
|---|---|---|
| 横向 | 首格 `gridSpan="N"`，后续 N-1 格 `hMerge="1"` | 占 N 列 |
| 纵向 | 首格 `rowSpan="N"`，后续 N-1 格 `vMerge="1"` | 占 N 行 |
| 无边框 | 只是 `a:tcPr/lnL` 等线条属性 | 视觉上像文本，实际是表格 |

注意 **PPT 的表格没有单元格样式表**，字体/填充都在 `a:tcPr` 与 `a:rPr` 里；表格首行通常被设为表头（视觉加粗），但没有 `tblHeader` 这种语义标记。

### 3. 图表

```xml
<p:graphicFrame>
  <a:graphic><a:graphicData uri=".../chart">
    <c:chart r:id="rId2"/>                    <!-- → ppt/charts/chart2.xml -->
  </a:graphicData></a:graphic>
</p:graphicFrame>
```

`chartN.xml` 的结构：

```text
c:chartSpace
└─ c:chart
     └─ c:plotArea
          └─ c:barChart / c:lineChart / c:pieChart …
               └─ c:ser                     # 一个数据系列
                    ├─ c:tx/c:strRef/c:strCache   # 系列名
                    ├─ c:cat/c:strRef|c:numRef
                    │    └─ c:strCache/c:pt/c:v   # ★ 分类标签缓存
                    └─ c:val/c:numRef
                         └─ c:numCache/c:pt/c:v   # ★ 数值缓存
```

要点：

- **数据全在 `<c:numCache>` / `<c:strCache>` 里**，不需要去解析嵌入的 xlsx；
- 如果缓存为空（生成器省略了），只能去 `ppt/embeddings/*.xlsx` 里读源表；
- 图表标题、坐标轴标题也是文本，值得抽；
- 图表可能与页面上的表格数字对不上（手工改过数据）。

### 4. SmartArt（结构图）

SmartArt 是 PPT 里最容易被漏掉的内容，因为 `python-pptx` 完全看不到它。

```xml
<p:graphicFrame>
  <a:graphicData uri=".../diagram">
    <dgm:relIds r:dm="rId5" r:lo="rId6" r:qs="rId7" r:cs="rId8"/>
  </a:graphicData>
</p:graphicFrame>
```

四个部件：

| 部件 | 文件 | 作用 |
|---|---|---|
| `r:dm` | `ppt/diagrams/data1.xml` | **★ 数据模型：文本与层级** |
| `r:lo` | `ppt/diagrams/layout1.xml` | 布局算法定义 |
| `r:qs` | `ppt/diagrams/quickStyle1.xml` | 快速样式 |
| `r:cs` | `ppt/diagrams/colors1.xml` | 配色 |

层级还原（关键）：

```xml
<dgm:dataModel>
  <dgm:ptLst>
    <dgm:pt modelId="1" type="doc">…</dgm:pt>
    <dgm:pt modelId="2"><dgm:t><a:p><a:r><a:t>总目标</a:t></a:r></a:p></dgm:t></dgm:pt>
    <dgm:pt modelId="3" type="parTrans">…</dgm:pt>   <!-- 父子连接点，无文本 -->
    <dgm:pt modelId="4"><dgm:t>…子项…</dgm:t></dgm:pt>
  </dgm:ptLst>
  <dgm:cxnLst>
    <dgm:cxn type="parOf" srcId="3" destId="2" srcOrd="0" destOrd="0"/>
    <dgm:cxn type="parOf" srcId="3" destId="4" srcOrd="1" destOrd="0"/>
  </dgm:cxnLst>
</dgm:dataModel>
```

规则：

1. `dgm:pt` 里 `dgm:t` 非空的是**内容节点**，`type="parTrans"/"sibTrans"` 是**虚拟连接点**（无文本）；
2. 用 `dgm:cxn type="parOf"` 的 `srcId → destId` 拼父子关系，`srcOrd` 是同级顺序；
3. 根节点是 `type="doc"`；
4. 按层级缩进输出，才能还原"目标 → 三条支撑 → 各自两条措施"的结构。

---

## 七、备注页、母版版式与隐藏页

### 1. 备注页（演讲者备注）

```text
ppt/notesSlides/notesSlide1.xml
└─ p:cSld/p:spTree
     └─ p:sp（p:ph type="body"）→ p:txBody  # ★ 讲稿正文
     └─ p:sp（p:ph type="sldImg"）           # 幻灯片缩略图占位
     └─ p:sp（p:ph type="sldNum"）
```

`python-pptx` 一行拿到：

```python
notes = slide.notes_slide.notes_text_frame.text
```

备注里常有真正的讲解内容（数据口径、结论、口径说明），**RAG 场景建议纳入，但要标记为"备注"**，避免和页面正文混在一起。

### 2. 母版与版式

| 文件 | 内容 | 抽取策略 |
|---|---|---|
| `slideMasters/slideMasterN.xml` | 主题引用、占位符定义、页脚/页码/日期 | 只取"公司 Logo 文字/固定标语"这类常量 |
| `slideLayouts/slideLayoutN.xml` | 版式的占位符布局与提示文本（"单击此处添加标题"） | **不要抽取**，那是提示语不是内容 |
| `theme/themeN.xml` | `a:clrScheme` 配色、`a:fontScheme` 主题字体 | 判断品牌色/字体，不参与正文 |

**常见误抽**：把 `Slide Layout` 或 `Slide Master` 里的 `ftr`（页脚）、`sldNum`（页码）、`dt`（日期）当成正文，导致每页都出现"XX 公司 | 2024"。

### 3. 隐藏页与放映设置

| 标记 | 位置 | 含义 |
|---|---|---|
| `p:sld @show="0"` | `slideN.xml` 根元素 | 放映时跳过（草稿页、附录页） |
| `p:sldId @id` | `presentation.xml` | 内部 ID，不连续 |
| `p:transition` | slide | 切换动画，解析忽略 |
| `p:timing` | slide | 动画序列，解析忽略 |

---

## 八、阅读顺序与坐标

PPT 没有"流"，**阅读顺序必须自己算**。

### 1. 坐标来源

```xml
<a:xfrm>
  <a:off x="838200" y="365125"/>     <!-- 左上角 -->
  <a:ext cx="10515600" cy="1325563"/> <!-- 宽高 -->
</a:xfrm>
```

`a:rot` 是旋转（1/60000 度），`a:flipH/flipV` 是翻转。

### 2. 组合形状的坐标换算

`p:grpSp` 有两套坐标：

```xml
<p:grpSpPr>
  <a:xfrm>
    <a:off x="1000000" y="1000000"/><a:ext cx="4000000" cy="2000000"/>  <!-- 组在页面上的位置 -->
    <a:chOff x="0" y="0"/><a:chExt cx="4000000" cy="2000000"/>          <!-- 子坐标系的定义范围 -->
  </a:xfrm>
</p:grpSpPr>
```

子形状的绝对坐标：

```text
abs_x = group_off_x + (child_off_x - chOff_x) × (group_ext_cx / chExt_cx)
abs_y = group_off_y + (child_off_y - chOff_y) × (group_ext_cy / chExt_cy)
```

组合可以多层嵌套，必须**逐层累乘**。`python-pptx` 返回的 `shape.left/top` 对组合内子形状是**相对组合坐标系**的值，不换算就会全挤在左上角。

### 3. 排序策略

推荐的两级排序：

1. **先按视觉块聚类**：标题区（顶部）、正文区、图表区、页脚区；
2. **块内按 `top` 升序，`top` 相近（差值 < 行高/2）按 `left` 升序**。

```python
def reading_order(shapes, tol_ratio=0.5):
    items = [(s.top, s.left, s) for s in shapes if s.has_text_frame and s.text_frame.text.strip()]
    items.sort(key=lambda t: (t[0], t[1]))
    rows, cur, cur_top = [], [], None
    for top, left, s in items:
        if cur_top is None or abs(top - cur_top) <= tol_ratio * s.height:
            cur.append((left, s)); cur_top = top if cur_top is None else cur_top
        else:
            rows.append([s for _, s in sorted(cur, key=lambda x: x[0])])
            cur, cur_top = [(left, s)], top
    if cur:
        rows.append([s for _, s in sorted(cur, key=lambda x: x[0])])
    return [s for row in rows for s in row]
```

注意：

- 双栏排版需要先按 `left` 切列，再列内按 `top` 排；
- 装饰性大背景图/色块要过滤（面积占满整页且无文本）；
- 标题占位符（`ph type="title"|"ctrTitle"`）应**强制置顶**，不要依赖坐标。

---

## 九、实际解析策略与常见坑

### 推荐解析路径

1. `.ppt` 先 `soffice --convert-to pptx`；`.pptx` 直接解 ZIP；
2. **读 `presentation.xml` 的 `p:sldIdLst`** 得到真实页序，用 `.rels` 映射到 `slides/slideN.xml`；
3. 每页遍历 `p:spTree`，**递归下钻 `p:grpSp`**，按元素类型分派；
4. `p:sp`：取 `p:ph @type` 判标题/正文，按 `a:p` → `a:r` → `a:t` 顺序拼接，记录 `lvl` 还原层级；
5. `p:pic`：取 `@descr` 替代文字，否则记为"图片（无描述）"，需要时抽 `media/` 走 OCR；
6. `p:graphicFrame`：按 `a:graphicData @uri` 分派到表格/图表/SmartArt；
7. SmartArt 解 `dgm:data1.xml`，用 `dgm:cxn` 拼层级；
8. 读 `notesSlides/`，作为"备注"附加到对应页；
9. **按坐标重排**文本块，识别标题与正文的阅读顺序；
10. 过滤：隐藏页（`show="0"`）、页脚/页码/日期占位符、装饰性空形状。

### 六个容易踩的坑

1. **页序错乱**：按 `slide1.xml`、`slide2.xml` 文件名排序，遇到删除/移动过页面的文件就全乱。必须以 `p:sldIdLst` 为准。
2. **SmartArt 整体消失**：`python-pptx` 不暴露 `dgm:`，几十页的组织架构图/流程图会一个字都抽不到。
3. **组合内坐标错**：不换算 `chOff/chExt`，子形状的坐标是全相对的，重排后顺序完全错。
4. **母版页脚混入正文**：`ftr`/`sldNum`/`dt` 占位符每页都有，抽取后每页重复"公司名 + 页码"。
5. **自动缩放导致字号失真**：`normAutofit @fontScale` 不参与 `a:rPr @sz`，靠字号判断标题会误判。
6. **图表数据与表格不一致**：图表缓存是快照，页面上另有一个表格数字，两者可能不同，不要假设等价。

### 其他次要但要留意的点

| 现象 | 原因 | 处理 |
|---|---|---|
| 文字被拆成很多 `a:r` | 格式切换、拼写检查 | 按 `a:p` 合并 run |
| 文本框竖排 | `a:bodyPr @vert="eaVert"` | 标记竖排，按列读 |
| 多栏文本 | `a:bodyPr/a:numCol` | 按 XML 顺序读，注明分栏 |
| 文字溢出框外 | `a:spAutoFit` 未生效 | 视觉与 XML 不符，属正常 |
| 图片裁剪后只剩中间 | `a:srcRect` | 提取原图不受影响 |
| 形状填充是图片 | `p:spPr/a:blipFill` 而非 `p:pic` | 单独判断 |
| 背景图片 | `p:cSld/p:bg` | 单独判断，通常是模板 |
| 文字是艺术字 | `a:prstTxWarp` 变形 | 文本仍可抽，形状难还原 |
| 文字被转成图片 | 无 `a:t` | 只能 OCR |
| `.ppt` 中文乱码 | `TextBytesAtom` 按 ANSI 解 | 用 LibreOffice 转 pptx |
| OLE 嵌入表格 | `a:graphicData uri=".../ole"` | 需解包 `embeddings/` |
| 加密文件 | OLE `EncryptedPackage` | `msoffcrypto-tool` 解密 |

### 快速选型建议（按场景）

| 场景 | 推荐方案 |
|---|---|
| 常规抽文本（标题+正文） | `python-pptx` + 自定义阅读顺序 |
| 需要图表背后的数字 | 解 `ppt/charts/chartN.xml` 的 `numCache` |
| 需要 SmartArt 内容 | 解 `ppt/diagrams/data1.xml` + `cxnLst` |
| 批量 PPT → Markdown（RAG） | `markitdown`，或自研：`python-pptx` + 图表/SmartArt 补丁 |
| 需要视觉还原（截图/PDF） | `soffice --convert-to pdf` 再解析 |
| 图片内容理解 | 抽 `media/` + OCR / 视觉模型 |
| `.ppt` 老档案 | LibreOffice 转 `.pptx` |

**RAG / 知识库场景的切块建议**：

- **一页 = 一个块**是 PPT 最自然的粒度（页面本身就是作者的分块意图）；
- 块内顺序：标题 → 正文（按阅读顺序）→ 表格 → 图表数据 → SmartArt 层级文本 → 备注；
- 图表要转成"表格化文字"（分类 + 系列 + 数值），否则纯图片式图表无法被检索；
- SmartArt 要转成缩进列表，保留父子关系；
- 备注单独标记，不要与正文拼接；
- 每个块保留：文件、页码、页标题、是否有图片（有则附 `descr`）；
- 跨页比较（趋势页、对比页）建议额外生成"整份 PPT 的页面标题序列"作为导航层。

---

## 附：PPT 解析技术路线总览

| 文件类型 | 特征 | 推荐路线 |
|---|---|---|
| `.pptx` 常规 | ZIP + XML，形状树 | `python-pptx` + XML 补丁 |
| `.pptx` 含 SmartArt | 文本在 `dgm:data1.xml` | 解 ZIP + 拼 `cxnLst` |
| `.pptx` 含图表 | 数据在 `c:numCache` | 解 `charts/chartN.xml` |
| `.pptx` 图片为主（海报/宣发） | 整页是图片 | 抽 `media/` + OCR / 视觉模型 |
| `.pptx` 含 OLE 对象 | 嵌入 Excel/Visio | 解 `embeddings/` |
| `.ppt` 老档案 | OLE2 + OfficeArt 记录 | LibreOffice 转 `.pptx` |
| 需要保真排版 | 视觉位置/动画/字体 | 转 PDF 或渲染截图 |
| 加密演示文稿 | `EncryptedPackage` | `msoffcrypto-tool` 解密 |
