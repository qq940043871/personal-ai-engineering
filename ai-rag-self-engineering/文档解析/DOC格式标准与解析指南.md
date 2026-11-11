# DOC / DOCX 文档格式标准与解析完整指南

> 本文档与《PDF 格式标准与解析指南》配套，覆盖 Word 文档的开放标准背景、两代容器结构（OLE 二进制 vs OPC/ZIP 包）、正文对象树、文字/图片/表格/文本框的判定方法、样式与编号的继承机制、正文之外的文本载体，以及实际解析策略与常见坑位。

---

## 一、Word 文档是开放标准吗？

要分开看，因为 `.doc` 和 `.docx` 完全不是一类东西：

| 扩展名 | 格式名 | 本质 | 标准状态 |
|---|---|---|---|
| `.doc` | Word 97-2003 Binary | **OLE2 复合文档（CFB）二进制** | 微软以 **[MS-DOC]** 名义公开了规范，但它是"公开的私有格式"，不是 ISO 标准 |
| `.dot` | Word 模板 | 同 `.doc` | 同上 |
| `.docx` | WordprocessingML | **OOXML（ZIP + XML）** | **ECMA-376**，后成为 **ISO/IEC 29500**，是真正的开放国际标准 |
| `.dotx` | 模板 | 同 `.docx` | 同上 |
| `.docm` | 带宏 | 同 `.docx` + VBA 工程 | 同上 |
| `.doc` 加密版 | EncryptedPackage | OLE 包 + AES 密文 | 规范公开，但需口令 |

| 时间 | 事件 |
|---|---|
| 1990s | Word 使用私有二进制格式，靠逆向工程才能读（所以有 `antiword`、`wvWare` 这类工具） |
| 2006 | 微软发布 **ECMA-376**（OOXML 第一版） |
| 2008 | OOXML 成为 **ISO/IEC 29500**，`.docx` 正式成为开放标准 |
| 2012 起 | 微软公开 **[MS-DOC]**、**[MS-CFB]** 等二进制格式文档，`.doc` 变成"有规范可依"的私有格式 |

需要注意三点：

1. **开放 ≠ 一种写法**：OOXML 分 **Transitional**（兼容旧特性，Word 默认保存的）和 **Strict**（严格版，几乎没有软件用）。实际见到的 `.docx` 99% 是 Transitional。
2. **开放 ≠ 结构简单**：WordprocessingML 的完整 schema 有数千个元素，绝大多数是排版细节，解析只需要其中一小部分。
3. **`.doc` 依旧是主流存量**：老档案、政府/企业公文、扫描录入系统的导出件里大量是 `.doc`，必须准备转换链路。

因此做 Word 解析，完全可以基于公开规范开发，这也是 `python-docx`、`mammoth`、`docx2python`、`pandoc`、LibreOffice 能存在的基础。

---

## 二、两代容器结构

### 1. `.docx`：OPC 包（本质是 ZIP）

`.docx` 是一个符合 **OPC（Open Packaging Conventions）** 的 ZIP 包，把文件后缀改成 `.zip` 就能直接解开：

```text
a.docx (ZIP)
├─ [Content_Types].xml          # 声明每种扩展名/Part 的 MIME 类型
├─ _rels/.rels                  # 包级关系：指向主文档
├─ docProps/
│    ├─ core.xml                # 标题、作者、创建/修改时间
│    └─ app.xml                 # 页数、字数、公司等
└─ word/
     ├─ document.xml            # ★ 正文主体
     ├─ document.xml.rels       # 正文里的 rId → 目标文件映射
     ├─ styles.xml              # 样式表（段落/字符/表格/编号样式）
     ├─ numbering.xml           # 多级列表定义
     ├─ settings.xml            # 兼容性、修订开关、默认制表位
     ├─ fontTable.xml           # 字体表
     ├─ webSettings.xml
     ├─ theme/theme1.xml        # 主题字体与配色
     ├─ footnotes.xml           # 脚注
     ├─ endnotes.xml            # 尾注
     ├─ header1.xml, footer1.xml# 页眉页脚（可多份）
     ├─ comments.xml            # 批注
     ├─ media/image1.png        # 图片等二进制资源
     ├─ embeddings/oleObject1.bin # 嵌入的 OLE 对象（Excel 表、MathType 公式）
     └─ charts/, diagrams/      # 图表、SmartArt
```

关键点：

- **正文只有 `word/document.xml`**，其他都是配套资源；
- 图片不是"插在文字中间"，而是以 `rId` 引用 `word/media/` 下的独立文件；
- 关系（relationship）是两级：`_rels/.rels` 找主文档，`word/_rels/document.xml.rels` 找图片/页眉/脚注；
- 文件里**没有"第几页"的概念**，分页是排版引擎渲染时算的（硬分页符 `w:br type="page"` 除外）。

### 2. `.doc`：OLE2 复合文档

`.doc` 是一个"文件里的文件系统"（CFB，Compound File Binary），内部按**流（stream）**存放数据：

```text
a.doc (OLE2 / CFB)
├─ WordDocument        # ★ FIB（文件信息块）+ 正文字符数据
├─ 0Table / 1Table     # 表流：piece table、样式表、章节信息
├─ Data                # 内嵌图片、绘图对象
├─ ObjectPool          # OLE 对象池
├─ SummaryInformation  # 摘要信息（作者、标题）
└─ \x05SummaryInformation 等
```

`.doc` 的难点在于正文不是连续字符串，而是由 **piece table（分片表）** 拼起来的，每片可能来自不同位置，可以是 8 位（CP1252）或 16 位（UTF-16LE）编码。这也是为什么 `.doc` 解析器容易出现乱码、丢字、顺序错乱。

**实践结论：不要自己解析 `.doc`，先无损转成 `.docx` 再处理。**

```bash
# LibreOffice 无头转换（最稳，跨平台）
soffice --headless --convert-to docx --outdir out/ a.doc

# Windows 批量
for %f in (*.doc) do soffice --headless --convert-to docx --outdir out "%f"
```

| 转换方案 | 优点 | 缺点 |
|---|---|---|
| LibreOffice (`soffice`) | 保真度高、支持表格/图片/页眉 | 需装 LibreOffice，首次启动慢，并发要隔离用户目录 |
| Word COM (`win32com`) | 保真度最高 | 仅 Windows + 必须装 Office，不能多线程 |
| `antiword` | 轻量、纯文本 | 只出文本，表格/图片全丢 |
| `catdoc` | 轻量 | 中文支持差 |
| Aspose.Words | 商业库，质量好 | 收费 |

---

## 三、"文档"在对象树中的表示

`document.xml` 是一棵很扁的树，`w:body` 下顺序排列着段落、表格、内容控件和节属性：

```text
w:document
└─ w:body
     ├─ w:p                    # 段落（最常见）
     │    ├─ w:pPr             # 段落属性：样式、对齐、缩进、编号
     │    └─ w:r               # 文本 run（一段同样式文字）
     │         ├─ w:rPr        # 字符属性：字体、字号、粗斜体、颜色
     │         └─ w:t          # ★ 真正的文字
     ├─ w:tbl                  # 表格
     ├─ w:sdt                  # 内容控件（可包段落/表格/整块）
     ├─ w:bookmarkStart/End    # 书签、目录锚点
     ├─ w:commentRangeStart    # 批注范围
     └─ w:sectPr               # 节属性（页边距、纸张、页眉页脚引用）
```

关键点：

- **`w:t` 是唯一真正承载文字的元素**，`w:p` 只是容器，`w:r` 是同样式片段；
- 一句话常被切成多个 `w:r`（因为拼写检查、格式变化、修订痕迹），所以要按段落拼接 run 才能得到完整句子；
- `w:body` 末尾的 `w:sectPr` 是最后一节的属性；中间分节时 `w:sectPr` 出现在某个 `w:p/w:pPr` 里；
- `w:sdt`、`w:ins`、`w:hyperlink` 都是"中间层"，里面的 `w:r` 依然是正文。

### 为什么 Word 解析比 PDF 简单、又比纯文本复杂

比 PDF 简单：文字是**真实的 Unicode 字符**，有段落结构，有表格结构，不需要还原绘制指令。

比纯文本复杂：

- 文字被拆成大量 run，且嵌套在 `hyperlink` / `ins` / `sdt` / `smartTag` 里；
- 编号、项目符号、目录序号**不存在于文本中**，是排版时生成的；
- 图片、文本框、公式是独立对象，位置与"阅读顺序"无关；
- 页眉页脚、脚注、批注、尾注的文本在**别的 XML 文件**里。

---

## 四、如何判断一段内容是文字、图片、表格还是文本框

Word 里没有"这一块是图片"的标记，只能看元素类型。判定规则全在 `document.xml` 里：

| 元素 | 含义 | 判断结果 |
|---|---|---|
| `w:t` | 文本字符 | 文字 |
| `w:tbl` | 表格 | 表格 |
| `w:drawing` | DrawingML 图形容器 | 图片或文本框（需下钻） |
| `w:pict` | VML 旧式图形容器 | 同上（老文档/兼容模式） |
| `w:object` | 嵌入 OLE 对象 | 嵌入表格/公式/文件 |
| `w:txbxContent` | 文本框内容 | **文本，但脱离正文流** |
| `m:oMath` / `m:oMathPara` | OMML 公式 | 公式（可转 LaTeX/文本） |
| `w:fldChar` + `w:instrText` | 复杂域 | 域代码（PAGE/TOC/REF 等） |
| `w:footnoteReference` | 脚注引用 | 指向 `footnotes.xml` |
| `mc:AlternateContent` | 兼容双写 | 同一对象出现两份，需去重 |

### 下钻判断 `w:drawing` 里是什么

```text
w:drawing
└─ wp:inline 或 wp:anchor          # 嵌入 / 浮动
     └─ a:graphic
          └─ a:graphicData (uri 决定类型)
               ├─ pic:pic → pic:blipFill → a:blip r:embed  → 图片
               ├─ wps:wsp → wps:txbx → w:txbxContent        → 文本框
               └─ wpg:wgp                                   → 组合图形
```

`a:graphicData` 的 `uri` 是最快的判据：

| uri 结尾 | 类型 |
|---|---|
| `/picture` | 图片 |
| `/wordprocessingShape` | 形状 / 文本框 |
| `/wordprocessingGroup` | 组合 |
| `/chart` | 图表 |
| `/diagram` | SmartArt |

### 用 python-docx 快速判断

```python
from docx import Document
from docx.oxml.ns import qn

def classify_body(doc):
    stats = {"para": 0, "image": 0, "table": 0, "textbox": 0}
    for p in doc.paragraphs:
        if p.text.strip():
            stats["para"] += 1
        xml = p._p.xml
        if "<w:drawing" in xml or "<w:pict" in xml:
            stats["image"] += 1
        if "<w:txbxContent" in xml:
            stats["textbox"] += 1
    stats["table"] = len(doc.tables)
    return stats
```

更稳的做法：**先按 `w:p` / `w:tbl` 遍历主流程，再单独扫一遍 `w:drawing` 与 `w:txbxContent`**，因为文本框里的段落不会被 `doc.paragraphs` 返回。

---

## 五、文字怎么存：段落、run 与样式继承

### 1. 一个段落的完整形态

```xml
<w:p>
  <w:pPr>
    <w:pStyle w:val="Heading1"/>      <!-- 段落样式 -->
    <w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>  <!-- 列表 -->
    <w:jc w:val="center"/>            <!-- 对齐 -->
    <w:ind w:firstLine="420"/>        <!-- 首行缩进（twip） -->
  </w:pPr>
  <w:r>
    <w:rPr>
      <w:rFonts w:ascii="Times" w:eastAsia="宋体"/>
      <w:b/><w:sz w:val="24"/><w:szCs w:val="24"/>  <!-- 24 半点 = 12pt -->
    </w:rPr>
    <w:t xml:space="preserve">第一章 </w:t>
  </w:r>
  <w:r><w:rPr><w:b/></w:rPr><w:t>绪论</w:t></w:r>
</w:p>
```

### 2. 常用属性对照

| 维度 | 元素/属性 | 说明 |
|---|---|---|
| 段落样式 | `w:pStyle @w:val` | 指向 `styles.xml` 的 `styleId` |
| 大纲级别 | `w:outlineLvl @w:val` | 0=一级标题，9=正文；标题层级的最佳来源 |
| 对齐 | `w:jc @w:val` | left/center/right/both(两端)/distribute |
| 缩进 | `w:ind` | `firstLine` / `left` / `hanging`，单位 twip（1/20 pt） |
| 行距 | `w:spacing` | `line` + `lineRule`（auto/exact/atLeast） |
| 字体 | `w:rFonts` | `ascii`/`eastAsia`/`hAnsi`/`cs` 分别管西文、中文、复杂文种 |
| 字号 | `w:sz` / `w:szCs` | **半磅值**，`w:sz=24` 即 12pt |
| 加粗/斜体/下划线 | `w:b` / `w:i` / `w:u` | 都是开关型 |
| 上下标 | `w:vertAlign` | superscript / subscript |
| 颜色 | `w:color @w:val` | 如 `FF0000` |
| 高亮 | `w:highlight @w:val` | yellow/green… |
| 隐藏文字 | `w:vanish` | **不可见内容，抽取时通常要跳过** |
| 删除线 | `w:strike` / `w:dstrike` | 单/双删除线 |

### 3. 样式继承链（解析层级标题的关键）

Word 的最终格式 = 层层叠加，后者覆盖前者：

```text
styles.xml / w:docDefaults        # 全局默认（默认字体、默认字号、默认行距）
      ↓
w:style (styleId="Heading1")      # 段落样式，可 basedOn 另一个样式
      ↓
w:pStyle 引用的样式（沿 basedOn 链往上找）
      ↓
w:pPr 直接属性                     # 段落级直接格式
      ↓
w:rPr 直接属性                     # run 级直接格式（最优先）
```

`docDefaults` 里通常写着默认中文字体（如宋体小四），很多文档的正文段落**没有任何 `w:rPr`**，视觉样式全靠默认值和样式表 —— 所以只读 `document.xml` 不看 `styles.xml` 会得到"全篇无格式"的假象。

`python-docx` 已经帮你解决了继承：`paragraph.style.name`、`run.font.size` 会回溯样式链（但 `run.font.size` 返回 `None` 时，真实字号在 `style` 上，需要自己再查）。

### 4. 特殊字符 run

| 元素 | 含义 | 转文本建议 |
|---|---|---|
| `w:tab` | 制表符 | `\t` |
| `w:br` | 换行（`type="page"` 为分页） | `\n` 或分页标记 |
| `w:cr` | 回车 | `\n` |
| `w:noBreakHyphen` | 不间断连字符 | `-` |
| `w:sym` | 符号字体字符 | 按 `w:char` 查 Symbol/Wingdings 码表，否则乱码 |
| `w:softHyphen` | 可选连字符 | 忽略 |

---

## 六、表格与合并单元格

### 1. 结构

```text
w:tbl
├─ w:tblPr            # 表格属性：tblStyle、tblW、jc、tblBorders、tblLayout
├─ w:tblGrid          # ★ 列定义，w:gridCol @w:w 是每列宽（twip）
│    ├─ w:gridCol
│    └─ w:gridCol
└─ w:tr               # 行
     ├─ w:trPr        # tblHeader（表头行）、cantSplit、trHeight
     └─ w:tc          # 单元格
          ├─ w:tcPr   # tcW、gridSpan、vMerge、vAlign、shd
          └─ w:p      # ★ 单元格里必须有段落，文字在段落里
```

**注意：单元格内容不是 `w:t`，而是 `w:p`（甚至 `w:tbl` 嵌套表）**，所以"取单元格文本"必须做段落拼接。

### 2. 合并单元格的两种机制

| 机制 | 元素 | 表现 |
|---|---|---|
| 横向合并 | `w:tcPr/w:gridSpan @w:val="3"` | 一个 `w:tc` 横跨 3 个网格列 |
| 纵向合并 | `w:tcPr/w:vMerge` | 首格 `@w:val="restart"` 标记起始，后续格 `@w:val="continue"`（或无 val）表示被合并 |

解析时的处理原则：

1. 以 `w:tblGrid` 的列数作为**逻辑列数**；
2. 遍历每行，遇到 `gridSpan` 就占多列，其余列留空；
3. 遇到 `vMerge=continue` 就向上回填起始格的值（或留空但记住归属）；
4. 转 Markdown 时**必须补齐成矩形**，否则表格会错列。

```python
def table_to_rows(table):
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if cell._tc in seen:        # 合并单元格会重复返回同一个 tc
                continue
            seen.add(cell._tc)
            cells.append(cell.text.replace("\n", " ").strip())
        rows.append(cells)
    return rows
```

`python-docx` 的 `row.cells` 对合并单元格会**重复返回同一个 `_tc`**，靠 `seen` 去重才能还原真实列数。

### 3. 其他表格细节

| 特性 | 位置 | 影响 |
|---|---|---|
| 表头重复 | `w:trPr/w:tblHeader` | 跨页表头，抽取时可作列名 |
| 行不允许跨页 | `w:trPr/w:cantSplit` | 纯排版信息 |
| 表头/首列样式 | `w:tblLook` | 视觉性 |
| 嵌套表 | `w:tc/w:tbl` | 需递归 |
| 浮动表格 | `w:tblPr/w:tblpPr` | 位置脱离正文流 |

---

## 七、看不见的文本：编号、域、目录、修订、内容控件

这一节是 Word 解析**最容易丢信息**的地方，因为它们的文字"不在 `w:t` 里"或"不只一份"。

### 1. 自动编号 / 项目符号

段落只有 `w:numPr`（`ilvl` + `numId`），序号由 `numbering.xml` 生成：

```text
numbering.xml
├─ w:abstractNum (abstractNumId=5)
│    └─ w:lvl (ilvl=0)  w:start=1  w:numFmt=decimal  w:lvlText="%1."
└─ w:num (numId=3) → abstractNumId=5
                      └─ w:lvlOverride (可选，改起始值)
```

要点：

- `w:numFmt` 取值：`decimal`、`lowerLetter`、`upperRoman`、`chineseCounting`（一二三）、`bullet`（`w:lvlText` 是个符号字符）等；
- **序号需要自己按文档顺序累计**：同一 `numId` + 同一 `ilvl` 递增，`ilvl` 变小则下层重启；
- 若不还原，正文会丢掉 "1."、"（一）"、"(a)" 这类标识，标题层级和条款归属全乱。

### 2. 域（Field）

复杂域由三个 run 组成：

```xml
<w:r><w:fldChar w:fldCharType="begin"/></w:r>
<w:r><w:instrText xml:space="preserve"> PAGE \* MERGEFORMAT </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r>
<w:r><w:t>3</w:t></w:r>          <!-- 域结果：显示出来的东西 -->
<w:r><w:fldChar w:fldCharType="end"/></w:r>
```

| 域代码 | 含义 | 解析建议 |
|---|---|---|
| `PAGE` / `NUMPAGES` | 页码 / 总页数 | 丢弃（噪声） |
| `TOC` | 目录 | **丢弃域结果**，否则目录文字与正文标题重复 |
| `REF` / `NOTEREF` | 交叉引用（"见 3.2 节"） | 保留结果文本 |
| `HYPERLINK` | 超链接 | 保留文字 + 取 URL |
| `SEQ` | 图表编号（图 1、表 2） | 保留结果 |
| `MERGEFIELD` | 邮件合并字段 | 若未合并且显示域代码，需清理 |
| `INCLUDETEXT` | 引用外部文件 | 结果文本可能来自别的文件 |

简单域 `w:fldSimple @w:instr` 结构更扁平，但同样有"代码 + 结果"两部分。

### 3. 修订痕迹

| 元素 | 含义 |
|---|---|
| `w:ins` | 插入的内容（作者、时间在属性上） |
| `w:del` | 删除的内容，文字在 **`w:delText`** |
| `w:moveFrom` / `w:moveTo` | 移动的源/目标 |
| `w:rPrChange` / `w:pPrChange` | 格式修订历史 |

坑：如果直接把所有 `w:t` 抽出来，`w:ins` 会被当正文（合理），但 `w:del` 里是 `w:delText`，多数库会忽略它（也合理）；麻烦在于**接受修订版**和**拒绝修订版**的文本不同，RAG 里最好按"接受全部修订"输出，并记录存在修订。

### 4. 内容控件（`w:sdt`）

```xml
<w:sdt>
  <w:sdtPr><w:alias w:val="姓名"/><w:tag w:val="name"/></w:sdtPr>
  <w:sdtContent>
    <w:p><w:r><w:t>张三</w:t></w:r></w:p>
  </w:sdtContent>
</w:sdt>
```

它常用于表单模板、目录、下拉选项。**内容在 `w:sdtContent` 里，是正常正文**，但很多简易解析器只遍历 `body` 的直接子节点，会把整个 `w:sdt` 跳过 —— 目录和表单字段就此消失。

---

## 八、正文之外的文本载体

`document.xml` 不是全部文本。以下位置各有独立文件，必须单独读取，否则会漏内容：

| 载体 | 文件 | 元素 | 常见内容 |
|---|---|---|---|
| 页眉 | `word/headerN.xml` | `w:hdr` → `w:p` | 公司名、文档标题、Logo |
| 页脚 | `word/footerN.xml` | `w:ftr` → `w:p` | 页码、密级、版权 |
| 脚注 | `word/footnotes.xml` | `w:footnote` | 注释、引用出处 |
| 尾注 | `word/endnotes.xml` | `w:endnote` | 参考文献 |
| 批注 | `word/comments.xml` | `w:comment` | 审阅意见（含作者、日期） |
| 文本框 | `document.xml` 内的 `w:txbxContent` | `w:p` | 图注、侧栏、海报文字 |
| 图表数据 | `word/charts/chartN.xml` | `c:ser` / `c:cat` / `c:val` | 图表背后的数字 |
| 嵌入对象 | `word/embeddings/*.bin` | OLE | 内嵌 Excel 表、MathType 公式 |

处理策略：

- **页眉页脚**：抽出来做"文档级元信息"（标题/密级），**不要**混进正文流，否则每页重复；
- **脚注尾注**：正文里保留引用标记，脚注文本单独成块，带上引用点；
- **批注**：默认不并入正文（它是"关于正文的元信息"），但审阅场景要保留作者与锚点段落；
- **文本框**：正文流里位置丢失，应按 `wp:anchor` 的坐标（EMU）重新插回大致位置，或单独成块并标注"文本框"。

---

## 九、实际解析策略与常见坑

### 推荐解析路径

1. **统一入口**：`.doc` 先 `soffice --convert-to docx`，`.docx` 直接开 ZIP；
2. **读 `styles.xml`**：先建立 `styleId → 样式名 + 大纲级别 + 字体字号` 的映射表；
3. **顺序遍历 `w:body`**：按子元素类型分派（`w:p` / `w:tbl` / `w:sdt`），不要用扁平化的 `doc.paragraphs`；
4. **段落内按 run 拼接文本**，同时记录 run 的字号/加粗/大纲级别（判断标题）；
5. **还原编号**：维护 `(numId, ilvl) → 计数器`，按 `w:numFmt` 生成前缀；
6. **表格递归**：处理 `gridSpan` / `vMerge`，输出矩形二维数组；
7. **补扫隐藏文本**：`w:txbxContent`、页眉页脚、脚注、域结果；
8. **过滤噪声**：`w:vanish`、TOC 域结果、`w:proofErr`、`w:bookmarkStart`、空段落、重复空行。

### 标题层级怎么判（比"字号大就是标题"更可靠）

优先级从高到低：

1. `w:outlineLvl`（大纲级别，来自段落样式或直接格式）；
2. `w:pStyle` 的 `styleId`（`Heading1`/`1`/`标题 1`/`Ttulo1` 等，取决于语言版本，**不要硬编码中文**）；
3. 样式名（`python-docx` 的 `paragraph.style.name`，会做本地化，但仍不可靠）；
4. 字号 + 加粗 + 居中 + 段前段后间距的启发式判断。

注意 `styleId` 在中文版 Word 里也可能是 `1`、`2`、`a3` 这类无意义值，必须去 `styles.xml` 查 `w:name` 和 `w:basedOn` 链。

### 六个容易踩的坑

1. **`mc:AlternateContent` 双写**：同一个图片/文本框，`mc:Choice`（DrawingML）和 `mc:Fallback`（VML）各存一份，直接遍历会**抽到两遍**。只取 `mc:Choice` 分支。
2. **文本框脱离正文流**：`python-docx` 的 `doc.paragraphs` **不含**文本框里的段落；图表里的文字、艺术字也一样。
3. **超链接文字被漏掉**：`w:hyperlink` 里的 `w:r` 不是 `w:p` 的直接子级，早期 `python-docx` 的 `paragraph.text` 会跳过（1.1+ 提供 `paragraph.hyperlinks`），自己遍历时要显式下钻。
4. **编号全丢**：不做计数器还原，条款"3.2.1"、"（五）"就消失了；`numbering.xml` 缺失或 `numId=0` 表示"无编号"。
5. **目录污染**：`TOC` 域的**结果**是一堆带页码的标题行，和正文标题重复，必须识别并丢弃。
6. **加密与损坏**：`EncryptedPackage` 流的 `.doc`/`.docx` 打不开 ZIP；`.docx` 可能被第三方工具生成成非标准 ZIP（缺 `[Content_Types].xml`），需要容错。

### 其他次要但要留意的点

| 现象 | 原因 | 处理 |
|---|---|---|
| 中文乱码 | 字体是 Symbol/Wingdings，或 `.doc` piece table 编码判错 | 查 `w:sym` 码表；`.doc` 走 LibreOffice |
| 段落被拆成很多 run | 拼写检查、修订、格式切换 | 按 `w:p` 合并，保留首个有效 `rPr` |
| 表格错列 | `gridSpan` / `vMerge` 未处理 | 按 `tblGrid` 补齐矩形 |
| 数字/日期变成文本 | 原本就是文本，或域结果 | 正则识别 + 类型推断 |
| 页码/总页数混进正文 | `PAGE` 域在页脚 | 页脚单独处理 |
| 公式变空白 | OMML 不在 `w:t` | 解析 `m:oMath` 或直接丢 |
| 图片丢失 | 只读 `document.xml` 未跟 `rId` | 解析 `document.xml.rels` |
| 段落顺序错乱 | 浮动对象 + 文本框 | 按 `wp:anchor` 坐标重排 |

### 快速选型建议（按场景）

| 场景 | 推荐方案 |
|---|---|
| 简单抽正文段落 | `python-docx` |
| 转 HTML/Markdown（保留列表、表格、图片） | `mammoth` 或 `pandoc` |
| 需要精确保留表格二维结构 | `docx2python`（输出嵌套列表） |
| 批量文档 → Markdown（RAG 前置） | `pandoc -t gfm --extract-media` 或 LibreOffice + `markitdown` |
| `.doc` 老档案 | LibreOffice 转 `.docx` 后再处理 |
| 需要版式/分页/视觉还原 | 转 PDF 再解析（`soffice --convert-to pdf`） |

**RAG / 知识库场景的切块建议**：

- 以**标题层级**为一级切块边界，条款/小节为二级；
- 表格单独成块，转 Markdown 表格，保留表头与合并信息；
- 编号列表要还原序号，否则"第 3 条"无法被检索命中；
- 页眉页脚、页码、TOC、批注不进正文块；
- 每个块记录：章节路径、段落序号、是否有图片/公式、来源文件名。

---

## 附：Word 解析技术路线总览

| 文档类型 | 特征 | 推荐路线 |
|---|---|---|
| 现代 `.docx` | ZIP + XML，Word 2010+ 生成 | `python-docx` / `mammoth` / 直接解 XML |
| 兼容模式 `.docx` | Word 2003 文档另存，含大量 `w:pict` VML | 解 XML 时同时处理 `w:pict`，或 LibreOffice 转一遍 |
| 老式 `.doc` | OLE2 二进制 | LibreOffice / Word COM 转 `.docx`，或 `antiword`（只要文本） |
| 带宏 `.docm` | 含 `vbaProject.bin` | 同上，VBA 不需要解析 |
| 加密文档 | `EncryptedPackage` 流 | 需要口令解密后再走上面流程 |
| 公文/合同类 | 大量表格、编号条款、页眉密级 | `python-docx` 精细解析 + 编号还原 |
| 扫描件塞进 Word | 整页是 `w:drawing` 图片 | 抽出 `media/*` 走 OCR |
