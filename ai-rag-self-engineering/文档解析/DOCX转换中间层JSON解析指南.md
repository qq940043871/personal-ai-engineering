# DOCX → 中间层 JSON 解析指南

> 本文档与《DOC / DOCX 格式标准与解析完整指南》配套。前者讲 `.docx` 的容器、对象树与文字载体，本篇讲**落地**：如何把 `document.xml` 解析成一棵可编辑、可渲染、可分页、可回写的中间层 JSON（Tiptap / ProseMirror 风格），以及每一步的判定规则、单位换算、坑位。
>
> 参考实现来自中原云商合同模板系统（Java + Apache POI）：`PoiWordToTiptapConverter`（DOCX → JSON）、`DocumentModelService`（JSON → HTML）、`PaginationService`（JSON → 预分页）、`DocxVariableReplacer`（JSON 变量 → DOCX 回写）。本文把它的规则抽成与语言无关的规范，最后给一份 Python 复刻骨架。

---

## 一、为什么要中间层 JSON

同一份 `.docx`，导出路线不同，代价完全不同：

| 路线 | 产物 | 能编辑 | 能回写 DOCX | 能预分页 | 典型问题 |
|---|---|---|---|---|---|
| `.docx → HTML 字符串` | 带内联 CSS 的 HTML | 勉强（改样式=改字符串） | 不能 | 不能 | 结构藏在 `style="..."` 里，无法做节点级操作 |
| `.docx → PDF` | 固定版式 | 不能 | 不能 | 已完成 | 只读，结构全丢 |
| `.docx → 中间层 JSON` | 语义节点树 | 能 | 能（配变量替换器） | 能 | 需要自己定义 schema 与单位口径 |
| 直接操作 `.docx` | 原始 OPC 包 | 要 Word | 能 | 不能 | 浏览器无法预览，分页只能靠 Word 引擎 |

中间层 JSON 必须同时满足五条硬要求，否则不如直接用 HTML：

1. **结构无损**：段落 / 表格 / 合并单元格 / 图片 / 超链接的**文档顺序**必须保住；
2. **样式可分两级**：段落级（对齐、缩进、行距）+ run 级（字体、字号、粗斜体、颜色）；
3. **可往返**：JSON ↔ HTML ↔ PDF ↔ DOCX 变量替换，任一路径都不能丢正文；
4. **block 粒度**：分页引擎要能对每个顶层块估高并插分页符，因此段落、表格必须是**顶层平铺节点**；
5. **可标注**：能挂 `variable` 节点、能给出"JSON 节点 → 纯文本偏移"的映射，供 AI 变量抽取回填。

参考实现的分工：

| 类 | 职责 | 输入 → 输出 |
|---|---|---|
| `PoiWordToTiptapConverter` | DOCX 语义解析（唯一真相源） | `byte[] docx` → `{type:"doc", content:[...]}` + title |
| `DocumentModelService` | 布局引擎：变量替换 + 节点树渲染 | `DocumentModel JSON` + `Map<key,value>` → `fullHtml/headerHtml/footerHtml/pageConfig` |
| `PaginationService` | 估算 block 高度并插 `pageBreak` | `doc` + `pageConfig` → `{doc, pageCount}` |
| `DocxVariableReplacer` | 不走 JSON，直接在 DOCX 层替换 `{{VAR}}` | `docx` + 变量 → `docx`（供 LibreOffice 出高保真 PDF） |

注意最后一行：**中间层 JSON 不是唯一出口**。"浏览器预览 + 变量填充"走 JSON，"归档级高保真 PDF"仍走 DOCX 原文件替换。两条链路共享同一套变量命名。

---

## 二、整体形状：DocumentModel

顶层只有两个区：`body`（正文语义树）与 `meta`（版面与正文之外的一切）。

```json
{
  "body": {
    "type": "doc",
    "content": [
      { "type": "heading", "attrs": { "level": 1, "textAlign": "center", "marginBottom": "12pt" },
        "content": [ { "type": "text", "text": "煤炭买卖合同", "marks": [ { "type": "bold" } ] } ] },
      { "type": "paragraph", "attrs": { "textAlign": "left", "textIndent": "24pt", "lineHeight": "1.80" },
        "content": [
          { "type": "text", "text": "合同编号：" },
          { "type": "variable", "attrs": { "key": "NETNO", "label": "合同编号" } }
        ] },
      { "type": "table", "content": [
          { "type": "tableRow", "content": [
              { "type": "tableCell", "attrs": { "colspan": 2, "background": "#F2F2F2" },
                "content": [ { "type": "paragraph", "attrs": { "textAlign": "center" },
                               "content": [ { "type": "text", "text": "标的" } ] } ] }
          ] }
      ] },
      { "type": "pageBreak" }
    ]
  },
  "meta": {
    "pageConfig": {
      "pageSize": "A4",
      "pageOrientation": "portrait",
      "pageMargin": { "top": "2.54cm", "right": "3.17cm", "bottom": "2.54cm", "left": "3.17cm" }
    },
    "header": {
      "enabled": true,
      "content":       { "type": "doc", "content": [ { "type": "paragraph", "content": [ { "type": "text", "text": "河南国龙矿业有限公司" } ] } ] },
      "firstPageContent": { "type": "doc", "content": [] }
    },
    "footer": {
      "enabled": true,
      "content": { "type": "doc", "content": [ { "type": "paragraph", "attrs": { "textAlign": "center" },
        "content": [ { "type": "text", "text": "第 " },
                     { "type": "variable", "attrs": { "key": "page", "label": "页码" } },
                     { "type": "text", "text": " 页 / 共 " },
                     { "type": "variable", "attrs": { "key": "totalPage", "label": "总页数" } },
                     { "type": "text", "text": " 页" } ] } ] }
    },
    "watermark": { "enabled": false, "type": "text", "text": "原件", "fontSize": 36,
                   "fontFamily": "宋体", "color": "#C0C0C0", "opacity": 0.5, "spacing": 200, "rotate": -45 },
    "sections": []
  }
}
```

### `meta` 各字段语义

| 字段 | 类型 | 说明 | 默认值（渲染时） |
|---|---|---|---|
| `pageConfig.pageSize` | string | `A4` / `A3` / `A5` / `LETTER` / `LEGAL` | `A4` |
| `pageConfig.pageOrientation` | string | `portrait` / `landscape`（横向时宽高互换） | `portrait` |
| `pageConfig.pageMargin` | object \| string | `{top,right,bottom,left}` 或单个值，带单位字符串 `"2.54cm"` / `"25mm"` / `"1in"` | 四边 `2.5cm`（分页引擎按 `2.54cm`） |
| `header.enabled` | bool | 关闭时整块不渲染（不是渲染空 div） | `false` |
| `header.content` | doc 节点 | 默认页眉 | — |
| `header.firstPageContent` | doc 节点 | 首页不同页眉（`@page :first`） | — |
| `header.oddContent` / `evenContent` | doc 节点 | 奇偶页不同（渲染器当前只做替换，不做区分） | — |
| `footer.*` | 同上 | 页脚支持 `page` / `totalPage` 系统变量 | — |
| `watermark.enabled` | bool | 文字水印走 SVG data-URI 平铺，图片水印走 `background-image` | `false` |
| `sections[]` | array | 分节自定义页眉页脚，每项含 `header` / `footer`，变量替换会递归进去 | — |

**关键口径：参考实现的 Java 转换器只产出 `body`，`meta` 由编辑器/前端补。** 因为渲染、分页、PDF 全部依赖 `meta`，落库前必须补全，否则 PDF 只能拿到默认 A4 + 无边距页眉页脚。自己实现时应当从 `word/document.xml` 的 `w:sectPr` 直接推导：

| `meta` 字段 | DOCX 来源 | 换算 |
|---|---|---|
| `pageSize` | `w:sectPr/w:pgSz/@w:w`、`@w:h`（twip） | 11906×16838 ≈ A4；16838×11906 ≈ A3；宽>高 → landscape |
| `pageOrientation` | `w:pgSz/@w:orient` | `landscape` / 缺省 `portrait` |
| `pageMargin.*` | `w:sectPr/w:pgMar/@w:top|right|bottom|left`（twip） | `twip / 567` 得 cm，写成 `"2.54cm"` |
| `header/footer` | `w:sectPr/w:headerReference`、`w:footerReference` → `word/headerN.xml` | `rId` 查 `document.xml.rels`，再解析 `w:hdr`/`w:ftr` 下的 `w:p`（复用正文段落规则） |

---

## 三、节点类型与属性

### 1. 节点总表

| type | 类别 | 必有字段 | 关键 attrs | content |
|---|---|---|---|---|
| `doc` | 根 | `content` | — | block |
| `paragraph` | block | `type` | `textAlign` / `textIndent` / `marginTop` / `marginBottom` / `marginLeft` / `marginRight` / `lineHeight` / `pageBreakBefore` | inline |
| `heading` | block | `attrs.level` | `level`(1-6) + 同 paragraph 全部 | inline |
| `bulletList` | block | `content` | — | `listItem` |
| `orderedList` | block | `content` | — | `listItem` |
| `listItem` | block | `content` | — | `paragraph`（参考实现只放一个） |
| `table` | block | `content` | —（参考实现不存列宽/边框） | `tableRow` |
| `tableRow` | block | `content` | — | `tableCell` |
| `tableCell` / `tableHeader` | block | `type` | `colspan` / `rowspan` / `background` / `verticalAlign` | block |
| `blockquote` / `codeBlock` | block | `type` | `codeBlock.language`（可选） | block / text |
| `text` | inline leaf | `text` | — | 无 |
| `variable` | inline leaf | `attrs.key` `attrs.label` | — | 无 |
| `image` | leaf | `attrs.src` | `src`(data URI) / `alt` / `width` / `height` | 无 |
| `hardBreak` | inline leaf | `type` | — | 无 |
| `pageBreak` | block leaf | `type` | — | 无 |
| `horizontalRule` | block leaf | `type` | — | 无 |

### 2. 段落属性（`paragraph` / `heading` 共用）

| attrs | 取值 | 来源 | 说明 |
|---|---|---|---|
| `textAlign` | `left` / `center` / `right` / `justify` | `w:jc`（含样式链回溯） | 转换器**总是**写入，未设置时为 `left` |
| `textIndent` | `"24pt"` / `"-12pt"` | `w:ind/@w:firstLine`（正）/ `@w:hanging`（负） | twip ÷ 20 |
| `marginLeft` / `marginRight` | `"36pt"` | `w:ind/@w:left` / `@w:right` | 同上 |
| `marginTop` / `marginBottom` | `"6pt"` | `w:spacing/@w:before` / `@w:after` | 同上 |
| `lineHeight` | `"1.80"`（无单位=倍数）或 `"28.0pt"` | `w:spacing/@w:line` + `@w:lineRule` | AUTO → `line/240`；EXACT/AT_LEAST → pt |
| `pageBreakBefore` | `true` | `w:pPr/w:pageBreakBefore` | 渲染时补 `page-break-before:always` |

### 3. Marks（run 级样式）

`marks` 是数组，顺序即渲染嵌套顺序（先出现的在外层）。

| mark.type | 触发条件 | attrs |
|---|---|---|
| `bold` | `w:b` | — |
| `italic` | `w:i` | — |
| `underline` | `w:u` 且非 `none` | — |
| `strike` | `w:strike` | — |
| `superscript` / `subscript` | `w:vertAlign` | — |
| `link` | `w:hyperlink` 或 `HYPERLINK` 域 | `href`、`target:"_blank"` |
| `textStyle` | 颜色 / 字体 / 字号任一存在 | `color:"#FF0000"`、`fontFamily`、`fontSize:"12pt"` |
| `highlight` | `w:highlight` | `color`（缺省 `#ffff00`） |

规则要点：

- **颜色、字体、字号必须聚合成一个 `textStyle`**，不能拆成三个 mark。`PaginationService` 只从 `textStyle.attrs.fontSize` 读字号，拆开会导致高度估算失真；
- `fontSize` 带单位字符串 `"12pt"`，不是数字；
- 渲染器按数组顺序包裹：`[bold, italic]` → `<em><strong>…</strong></em>`；
- 未识别的 mark 直接忽略，不能报错（向前兼容）。

### 4. 表格单元格

| attrs | 来源 | 说明 |
|---|---|---|
| `colspan` | `w:tcPr/w:gridSpan` | 仅 `>1` 时写入 |
| `rowspan` | `w:tcPr/w:vMerge="restart"` + 向下数 `continue` 行数 | 仅 `>1` 时写入；`continue` 格**整格丢弃**（不生成节点） |
| `background` | `w:tcPr/w:shd/@w:fill` | 补 `#`，如 `#F2F2F2` |
| `verticalAlign` | `w:tcPr/w:vAlign` | 仅 `center` / `bottom`，缺省 `top` |

单元格 `content` 是 **block 数组**（`paragraph`，允许嵌套 `table`），不是字符串——这一点与 HTML 不同，取单元格文本必须递归。

---

## 四、DOCX → JSON 映射规则

### 1. Body 层分派

只按 `w:body` 的**直接子元素**顺序遍历，遇到什么转什么：

```text
w:p     → paragraph / heading / list 上下文累积
w:tbl   → table
w:sdt   → 取 w:sdtContent 内的 w:p / w:tbl 拍平（参考实现 DTO 层跳过 body 级 sdt，属已知缺口）
w:sectPr → 不产出节点，写入 meta.pageConfig
```

**禁止用"所有段落"的扁平接口**（如 `document.getParagraphs()`）当正文顺序，它会把表格里的段落也混进来，破坏顺序。

### 2. 段落 → `paragraph` / `heading`

判定顺序（优先级从高到低，参考实现只做了 1-2）：

| 优先级 | 判据 | 说明 |
|---|---|---|
| 1 | `w:pPr/w:outlineLvl` @val ∈ 0..8 | 最可靠，0 = 一级标题；9 = 正文 |
| 2 | `styleId` 匹配 `(?i)Heading(\d+)` | 参考实现做法，取 group(1) 夹到 1..6；无 `\d+` 时默认 **3 级** |
| 3 | `styles.xml` 沿 `basedOn` 链找 `w:name`/`outlineLvl` | 中文版 styleId 常是 `1`、`a3`，必须回溯 |
| 4 | 字号 + 加粗 + 居中 + 段前段后 | 启发式，仅兜底 |

坑：`Heading` 判定**只认英文样式 ID**，中文 Word 里手改的"标题 1"可能 styleId 为 `1`，会全部退化成 `paragraph`。自己实现必须补 1、3 两条。

### 3. 行内：run → `text` + `marks`

`w:p` 下按子元素顺序处理：

| 元素 | 处理 |
|---|---|
| `w:r` | 每段文本生成一个 `text` 节点，附带本 run 的 marks |
| `w:hyperlink` | 下钻其 `w:r`，文本加 `link` mark（`r:id` 查 `document.xml.rels`；`w:anchor` 拼 `#锚点`） |
| `w:tab` | 有前导符制表位 → 点串（见 §4.9）；否则 `"\t"` |
| `w:bookmarkStart/End` | 丢弃 |
| `w:oMath` / `w:oMathPara` | 抽纯文本，作为普通 `text`（分式 → `a/b`，根式 → `√(x)`） |
| `w:fldChar` / `w:instrText` | 状态机，见 §4.8 |

**run 会被 Word 拆得很碎**（拼写检查、修订、格式切换），所以转换前必须先做 §五 的 `mergeSameStyleRuns`，否则 JSON 里满屏单字 `text` 节点，后续渲染、估高、检索全部受影响。

### 4. `{{VAR}}` → `variable` 节点

单个 run 的文本内，用正则 `\{\{\s*([\w.]+)\s*\}\}` 切分：

```text
"合同编号：{{NETNO}}" →
[ {type:"text", text:"合同编号："},
  {type:"variable", attrs:{key:"NETNO", label:"NETNO"}} ]
```

注意三个陷阱：

- **只在单个 run 内匹配**。`{{` 和 `}}` 被拆到两个 run 里就识别不到——这正是必须先合并 run 的原因；样式不同的两半无法合并，此时只能退化为普通文本（或做跨 run 文本预扫描并回填）；
- 变量节点**继承位置但不继承 marks**（参考实现不复制 rPr）。若希望占位符在编辑器里保留粗体，需手动把 marks 复制到 variable 节点；
- 变量替换时 `variable` → `text`，**保留原 marks**，这样"加粗的占位符"填值后仍加粗。

### 5. 列表 → `bulletList` / `orderedList`

判定与合并规则：

1. 段落有 `numId` 且**不是标题**，才进列表；
2. `isOrderedList`：按 `ilvl` 找 `w:lvlOverride/w:lvl/w:numFmt` → 找不到再找 `w:abstractNum/w:lvl` → 再退到 `lvl(0)`；`numFmt != bullet` 即有序（`decimal`、`chineseCounting`、`lowerLetter`…）；
3. 连续段落「有序性相同 + numId 相同」合并进同一个 list；切换 numId、切换类型、遇到非列表段落或表格时关闭当前 list；
4. 每项生成 `listItem{ content: [ paragraph ] }`。

**限制（要清楚知道自己实现时是否接受）**：

- `ilvl` 不参与分组 → 多级列表被压平成一级；
- 序号**不写进文本**（`1.`、`（一）` 由渲染器生成），这与《DOC 指南》第七章一致：认不出编号体系就会丢"第 3 条"这类可检索信息。RAG 场景建议额外把还原后的序号写入 `listItem.attrs.marker`；
- `numId=0` 表示无编号。

### 6. 表格

```text
w:tbl
├─ w:tblGrid/w:gridCol @w:w          → 逻辑列数与列宽（参考实现不写入 JSON）
└─ w:tr
    └─ w:tc
        ├─ w:tcPr/w:gridSpan         → colspan
        ├─ w:tcPr/w:vMerge           → restart: 算 rowspan；continue: 丢弃该格
        ├─ w:tcPr/w:shd @w:fill      → background
        ├─ w:tcPr/w:vAlign           → verticalAlign
        └─ w:p / w:tbl                → content（递归）
```

`rowspan` 计算：从 `restart` 格所在行往下逐行看**同一 cellIdx**，`vMerge=continue` 就 +1，遇到 `restart`/无 vMerge/行不存在就停。

三条必须做的修正：

1. **悬空 continue**：某列第一行就是 `continue`（没有 `restart`），直接去掉 `vMerge`，否则整行单元格消失；
2. **`gridSpan` 非法值**（0 或负数）：改写为 1；
3. **行长不齐**：转换后按 `gridSpan` 累计的逻辑列数补齐，渲染端才能画出矩形。

参考实现不写 `table` 级 attrs（宽度、边框、样式），因为渲染统一走 CSS（`border-collapse`、`1px solid #333`）。若要做版式还原，应补 `attrs.colWidths`（`gridCol/@w:w` → pt 数组）。

### 7. 图片

```text
w:drawing → wp:inline|wp:anchor → a:graphic → a:graphicData(uri=…/picture)
   → pic:pic → pic:blipFill → a:blip @r:embed → word/media/imageN.png
```

产出：

```json
{ "type": "image",
  "attrs": { "src": "data:image/png;base64,iVBOR…", "alt": "描述文字", "width": 240 } }
```

- `r:embed` 是 `rId`，必须查 `word/_rels/document.xml.rels` 拿目标 part，再取二进制；
- MIME 按扩展名推断（`png/jpeg/gif/bmp/svg`）；
- `a:graphicData` 的 `uri` 必须判断：`/picture` 才是图片，`/wordprocessingShape` 是文本框、`/chart` 是图表、`/diagram` 是 SmartArt，不能一律当图片；
- 单位陷阱：POI 的 `getWidth()` 返回 **pt**，而分页引擎把它当 **px** 用。自己实现时统一成 px（`EMU / 9525`）并显式写 `width`/`height`。

### 8. 超链接与域

复杂域是「begin → instrText → separate → 结果 run → end」五段（见《DOC 指南》7.2）。处理策略：

| 域类型 | 处理 |
|---|---|
| `HYPERLINK` | 从 `instrText` 里取第一个引号内 URL，域内文本加 `link` mark |
| `PAGE` / `NUMPAGES` | 丢弃结果（页脚里另用 `{{page}}` 系统变量） |
| `TOC` | 丢弃结果，否则目录标题与正文重复 |
| `REF` / `NOTEREF` / `SEQ` | **保留结果文本**（参考实现把域内 run 全丢弃，这是它的缺口） |
| 其他 | 保留结果文本 |

实现上用 `insideField` 布尔状态机跨 run 传递；遇到 `fldChar type=begin` 置位、`end` 复位，`instrText` 永不输出。

### 9. 制表符与前导符

`w:tab` 本身没有宽度，必须查段落（或样式链）的 `w:tabs/w:tab`：

| 属性 | 取值 |
|---|---|
| `@w:pos` | twip，位置 |
| `@w:val` | `left` / `center` / `right` |
| `@w:leader` | `none` / `dot` / `hyphen` / `underscore` |

- 无前导符 → 输出 `"\t"`；
- 有前导符 → 按 `宽pt/4` 估点数，输出 `" · "` / `" - "` / `" _ "` 重复串。这是**近似**方案（Word 是排版时填充），目录行的点线对不齐属正常现象；要做准必须走"转 PDF 再解析坐标"。

### 10. 修订、内容控件、分页

| 场景 | 规则 |
|---|---|
| `w:ins` | 视为正文（等价"接受修订"） |
| `w:del` | 丢弃（文字在 `w:delText`，不产出） |
| `w:moveFrom` / `w:moveTo` | 丢 `moveFrom`，留 `moveTo` |
| `w:rPrChange` / `w:pPrChange` | 丢弃（历史格式） |
| `w:sdt` | 取 `w:sdtContent` 内 `w:p`，转成普通 `paragraph`（**不能整块跳过**，目录与表单字段都在里面） |
| `w:br @w:type="page"` | 产出 `pageBreak`（也可留给分页引擎按版面重算） |
| `mc:AlternateContent` | 只取 `mc:Choice`，忽略 `mc:Fallback`，否则图片/文本框抽两遍 |

### 11. 正文之外的文本

| 载体 | 参考实现 | 建议落点 |
|---|---|---|
| 页眉 / 页脚 | **未抽取** | `meta.header.content` / `meta.footer.content`（doc 节点），`enabled` 由 `headerReference` 是否存在决定 |
| 脚注 / 尾注 | 未抽取 | 正文位置留 `{type:"footnoteRef", attrs:{id}}`，文本放 `meta.footnotes`，或直接拼成行内 `text` |
| 批注 | 未抽取 | 默认不进正文（元信息），需要时放 `meta.comments[{author,date,anchorText,text}]` |
| 文本框 `w:txbxContent` | 未抽取 | 会随 `w:drawing` 一起丢失；做版式还原时按 `wp:anchor` 坐标重排，或单独成块标注"文本框" |
| 图表数据 | 未抽取 | 只保留图片快照，`c:ser` 数字不进 JSON |

### 12. 单位换算速查

| 源 | 目标 | 公式 |
|---|---|---|
| twip（`w:ind`、`w:spacing`、`w:pgMar`、`w:pgSz`） | pt | `twip / 20` |
| twip | cm | `twip / 567` |
| 半磅值 `w:sz` | pt | `val / 2` |
| `w:spacing/@w:line` + `lineRule=AUTO` | 倍数 | `line / 240` |
| EMU（`wp:extent`、`a:ext`） | px | `emu / 9525` |
| EMU | pt | `emu / 12700` |
| cm | px（96 DPI） | `cm * 37.795` |
| 字符宽度估算 | px | 中文 `fontSize`，拉丁 `fontSize * 0.54`，粗体 ×1.05 |

---

## 五、转换前的四步预处理

顺序不能调，后一步依赖前一步的产物。四步都是"用副作用改 `XWPFDocument` 再转换"，Python 侧对应"改 lxml 树"。

| 顺序 | 步骤 | 做什么 | 为什么不能省 |
|---|---|---|---|
| 1 | `fillDefaultStyles` | 无 `w:rFonts` → 补 `SimSun`/`宋体`；无 `w:sz` → 补 `24`（=12pt） | 多数正文 run **没有任何 rPr**，样式全在 `docDefaults`/样式表里。不补则 JSON 里 90% 的 `text` 没有 marks，看起来"全篇无格式" |
| 2 | `mergeSameStyleRuns` | 相邻 run 的 fontFamily/fontSize/bold/italic/underline/strike/color/vertAlign **全部相等**才合并；带图片或域代码的 run 不合并 | 不合并则 `{{VAR}}` 可能被拆到两个 run 里识别不到；且节点数暴涨 |
| 3 | `fixEmptyParagraphs` | 把 run 文本里的软换行（VT，`U+000B`）统一成 `\n` | 否则 `\n` 丢失，段落变成一整行 |
| 4 | `fixTableMerges` | 清掉「无 `restart` 的 `vMerge=continue`」；`gridSpan<=0` 改 1 | 不修则整行单元格在转换阶段被丢弃，表格错列 |

副作用提醒：第 1 步会让**几乎每个 run 都带 `textStyle`**，JSON 体积显著变大（一份 300KB 的 docx 可产出 1–2MB JSON）。若不在乎"像素级还原"，可以在合并 run 之后再决定是否省略与全局默认相同的 `textStyle`。

---

## 六、JSON 的四条消费链路

### 1. JSON → HTML（布局引擎）

节点 → 标签的固定映射：

| type | 标签 / 输出 |
|---|---|
| `doc` | `div` |
| `paragraph` | `p`，attrs 拼成 `style` |
| `heading` | `h{level}`（level 夹到 1..6），自带 `page-break-after:avoid` |
| `bulletList` / `orderedList` / `listItem` | `ul` / `ol` / `li` |
| `table` / `tableRow` / `tableCell` / `tableHeader` | `table` / `tr` / `td` / `th`（`colspan`、`rowspan`） |
| `blockquote` / `codeBlock` | `blockquote` / `pre` |
| `text` | 转义后按 marks 依次包裹 |
| `variable`（未替换） | `<span class="contract-variable" data-variable="KEY">{{KEY}}</span>` |
| `image` | `<img src="…" />` |
| `hardBreak` | `<br />` |
| `pageBreak` | `<div style="page-break-before:always"/>` |
| `horizontalRule` | `<hr/>`（必须自闭合，OpenHTMLtoPDF 用 XML 解析器） |

段落 `style` 拼接顺序固定为：`text-align` → `text-indent` → `line-height` → `margin-top` → `margin-bottom` → `margin-left` → `margin-right`。

完整文档组装按目标引擎分两条：

| 引擎 | 页眉页脚方式 | 关键点 |
|---|---|---|
| OpenHTMLtoPDF | CSS Running Elements：`position: running(header)` + `@page { @top-center { content: element(header) } }` | 不支持 `position: fixed`；`@page :first` 做首页不同；页码用 `counter(page)` / `counter(pages)` |
| Playwright | 原生 `displayHeaderFooter` + `headerTemplate/footerTemplate` | 页眉页脚**不嵌进 HTML**；`{{page}}` 要转成 `<span class="pageNumber"></span>` |

水印统一走 CSS：文字水印生成 SVG → base64 → `body::before { background-image: url(data:image/svg+xml;base64,…) }`，`opacity`、`rotate`、`spacing` 都是 SVG 参数。

### 2. 变量替换

规则只有一条：**`variable` 节点就地替换为 `text` 节点，保留 `marks`**。

- 必须**深拷贝**整棵树再替换，否则同一份模板第二次渲染会拿到已污染的缓存；
- 系统变量 `page` / `totalPage` **不替换**，留给页脚渲染器；
- 替换范围：`body.content`、`meta.header.*`（`content`/`firstPageContent`/`oddContent`/`evenContent`）、`meta.footer.*`、`meta.sections[].header/footer`；
- 值为 `null` 时填空串，不要留 `{{KEY}}`（否则 PDF 里出现占位符）；
- 变量值里的 `<`、`&` 必须 HTML 转义（在渲染阶段做，不是替换阶段）。

### 3. 预分页

```text
剥离已有 pageBreak → 逐 block 估高 → 累加超页高则插 pageBreak → 回填 doc.content
```

估高模型（96 DPI）：

| 块 | 高度 |
|---|---|
| paragraph | `ceil(行内宽度 / 可用宽) * 字号*行高倍数 + marginTop + marginBottom`（默认 14px、1.8） |
| heading | 字号/行高按级取 24/20/16/15/14/14，marginTop 8、marginBottom 4 |
| table | 逐行取最高单元格（单元格宽按 `可用宽/3` 粗估），不跨页断裂 |
| list | 可用宽 −20，逐项累加，允许嵌套 |
| image | 按 `width/height` 等比缩放到可用宽，缺省 200px |
| 超大块（本身高于页高） | 独占一页，前后各插一个分页符 |

只要 block 估高，就必须保证**段落/表格是顶层节点**——这也是为什么不能把"整章"包成一个大 div。

### 4. 变量回写 DOCX（另一条链路）

不经过 JSON：`DocxVariableReplacer` 逐段落把 `w:r` 的文本拼起来 → 正则 `\{\{([^}]+)\}\}` → 替换 → 清空所有 run 的 content → 写回**第一个 run**。

- 优点：LibreOffice 出 PDF 时版式零损失；
- 代价：**整段格式被拉平**——第一个 run 的字体字号会套到整段，加粗等样式全部丢失；
- 必须与 JSON 链路**共用变量表**（`variablesJson`），否则两条路径填出来的合同不一致。

---

## 七、质量门：JSON 出来了怎么验

### 1. 结构校验（可写成断言）

| 检查项 | 规则 |
|---|---|
| 类型白名单 | `type` 必须在已知集合内，未知类型不报错但计入统计 |
| 层级 | `table > tableRow > tableCell`；`tableCell.content` 只能是 block；`listItem.content` 首元素应为 `paragraph` |
| 叶子 | `text` 必须有非空 `text`；`variable` 必须有 `attrs.key`；`image` 必须有 `attrs.src` |
| 合并 | `rowspan` 不得超过剩余行数；同一行 `colspan` 之和不超过 `gridCol` 数 |
| 表格矩形 | 每行按 `colspan` 展开后的逻辑列数一致 |
| 体积 | base64 图片总量超过阈值（如 5MB）应外部化，不要塞进 `LONGTEXT` |
| 节点数 | `text` 节点/字符数比值 > 1.5 说明 run 合并失败 |

### 2. 文本守恒（最容易发现丢字的手段）

```text
T1 = DOCX 全文提取（遍历 w:t + w:delText 排除 + 页眉页脚可选）
T2 = JSON 深度遍历拼接（text.text，variable → 原文 "{{key}}"）
比对 T1 与 T2 的字符集合/序列，diff 段落级定位
```

常见差异来源（都能对上号）：域结果被丢、文本框未抽取、`w:sym` 符号、页眉页脚未纳入。

### 3. 统计指标（进一次转换日志）

标题数 / 段落数 / 表格数（含嵌套）/ 合并单元格数 / 图片数 / 变量数 / 总字符数 / JSON 字节数 / 耗时。指标突变即回归。

### 4. JSON → 纯文本（RAG 切块用）

遍历规则：

| 节点 | 纯文本贡献 |
|---|---|
| `heading` | 换行 + 文本，并压入标题栈（`level` 决定弹出层级） |
| `paragraph` | 文本 + `\n` |
| `listItem` | 前缀 `- ` 或 `n. ` + 文本 + `\n` |
| `table` | 转 Markdown 表格（按 `colspan`/`rowspan` 补空格成矩形），整表独立成块 |
| `image` | `[图片: alt]` |
| `variable` | `{{key}}`（不要填空，否则检索不到"合同编号"这类语义位置） |
| `pageBreak` | 忽略（版面噪声） |

每个块记录：`headingPath`（如 `["第三章 交付", "3.2 验收"]`）、起始块序号、字符区间、`hasTable` / `hasImage` / `variableKeys`。

**偏移映射**：AI 变量抽取走的是"纯文本偏移 → 回填节点"的路子。做法与 `OffsetMapper`/`TextSegment` 一致：遍历 JSON 时记录每个 `text` 节点的 `[plainStart, plainEnd)`，LLM 返回 `{start,end,varName}` 后二分定位节点、算局部偏移、把 `text` 切成 `text + variable + text`。**从右往左替换**，否则偏移全乱。

---

## 八、常见坑位

| 现象 | 根因 | 处理 |
|---|---|---|
| 标题全变成普通段落 | 只匹配 `styleId` 的 `Heading\d`，中文版样式 ID 为 `1`/`a3` | 加 `outlineLvl` 判定 + `styles.xml` `basedOn` 回溯 |
| `{{VAR}}` 识别不到 | Word 把占位符拆进多个 run | 先合并同样式 run；跨样式时做段落级文本预扫描并回填 |
| 满屏单字 `text` 节点 | run 未合并 | `mergeSameStyleRuns`；判定条件要含 color/vertAlign |
| 目录内容重复进正文 | `TOC` 域结果被当正文 | 识别 `TOC` 域，丢弃结果 |
| 交叉引用文字消失 | 域内 run 一律丢弃 | 只丢 `PAGE`/`NUMPAGES`/`TOC`，其余保留结果 |
| 表格错列 / 整行缺失 | `vMerge=continue` 无 `restart`；`gridSpan` 非法 | 预处理清理 + 转换时丢弃 continue 格 |
| 表格宽度/边框全丢 | `table` 节点不存 `gridCol`/`tblBorders` | 需要版式时补 `attrs.colWidths`，渲染走 CSS |
| 图片丢失 | 只解析 `w:t`，未跟 `r:embed` | 解析 `document.xml.rels`，`a:blip` → media |
| JSON 体积爆炸 | 图片 base64 + 每 run 的 `textStyle` | 图片外置为 URL；省略与默认值相同的 `textStyle` |
| 段内换行变空格 | `w:br` 被转成文本 `\n`，HTML 里折叠 | 转换阶段就产出 `hardBreak` 节点，而不是 `"\n"` |
| 文本框/艺术字消失 | `w:txbxContent` 不在 `body` 主流程 | 单独扫一遍 `w:drawing`/`w:pict`，按锚点坐标单独成块 |
| 页眉页脚全丢 | 转换器只读 `document.xml` | 解析 `headerReference`/`footerReference` → `meta.header/footer` |
| 水印丢了 | 水印是 `headerN.xml` 里的 VML/图形 | 抽取文字或图片，落到 `meta.watermark` |
| 首页/横向页错乱 | `meta.pageConfig` 用默认 A4 | 从 `w:sectPr` 推导；多节文档要落 `meta.sections` |
| 分页位置离谱 | 估高模型用 px，字号却来自 pt | 统一换算（`pt * 1.333 = px`），中文字宽按全角算 |
| PDF 中文变方框 | OpenHTMLtoPDF 字体未注册 / 用了 TTC | 注册 `.ttf`（simhei/simkai/NotoSerifCJK），避免 `simsun.ttc` |
| 大文件 OOM | 50MB docx + base64 图片全在堆里 | 流式取图、限制单图大小、`-Xmx2g` 以上 |

---

## 九、Python 复刻骨架

Java/Python 在这件事上没有本质差别，关键是别用"扁平 API"。下面是最小可用骨架（`python-docx` + `lxml`），省略了错误处理与域状态机。

```python
import base64, re   # base64 供图片：a:blip @r:embed → rels → blob → data URI
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
TWIP2PT = 1 / 20.0
EMU2PX = 1 / 9525.0


def iter_blocks(parent_el, parent):
    """按文档顺序产出段落/表格——不要用 doc.paragraphs"""
    for child in parent_el.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def heading_level(p: Paragraph) -> int | None:
    ppr = p._p.pPr
    if ppr is not None and ppr.outlineLvl is not None:      # 最可靠
        return min(6, int(ppr.outlineLvl.val) + 1)
    m = re.match(r"(?i)heading(\d+)$", (p.style.style_id or "") if p.style else "")
    return max(1, min(6, int(m.group(1)))) if m else None


def marks_of(run) -> list[dict]:
    # 注意：python-docx 只读 run 的直接格式，不回溯 styles.xml。
    # 生产实现必须先用 docDefaults / 段落样式补齐默认字体字号（对应 Java 的 fillDefaultStyles）。
    marks = []
    if run.bold: marks.append({"type": "bold"})
    if run.italic: marks.append({"type": "italic"})
    if run.underline: marks.append({"type": "underline"})
    if run.font.strike: marks.append({"type": "strike"})
    style = {}
    if run.font.color and run.font.color.rgb:
        style["color"] = "#" + str(run.font.color.rgb)
    # 中文字体在 w:rFonts/@w:eastAsia，run.font.name 只取 ascii/hAnsi
    if run.font.name: style["fontFamily"] = run.font.name
    if run.font.size: style["fontSize"] = f"{run.font.size.pt:g}pt"   # EMU→pt 已由库处理
    if style: marks.append({"type": "textStyle", "attrs": style})
    return marks


def inline_nodes(p: Paragraph) -> list[dict]:
    nodes = []
    for run in p.runs:                       # 生产实现需下钻 w:hyperlink / w:sdt
        for seg in re.split(r"(\{\{\s*[\w.]+\s*\}\})", run.text):
            if not seg: continue
            m = VAR.fullmatch(seg)
            if m:
                nodes.append({"type": "variable",
                              "attrs": {"key": m.group(1), "label": m.group(1)}})
            else:
                node = {"type": "text", "text": seg}
                mk = marks_of(run)
                if mk: node["marks"] = mk
                nodes.append(node)
    return nodes


def convert_paragraph(p: Paragraph) -> dict:
    level = heading_level(p)
    attrs = {}
    if level:
        node = {"type": "heading", "attrs": {**attrs, "level": level}}
    else:
        node = {"type": "paragraph", "attrs": attrs}
    content = inline_nodes(p)
    if content:
        node["content"] = content
    return node


def convert_table(tbl: Table) -> dict:
    rows = []
    for row in tbl.rows:
        cells, col, seen = [], 0, set()
        for cell in row.cells:               # 合并格会重复返回同一 tc，需去重
            tc = cell._tc
            if tc in seen: continue
            seen.add(tc)
            attrs = {}
            tcpr = tc.tcPr
            span = tcpr.gridSpan.val if tcpr is not None and tcpr.gridSpan is not None else 1
            if span and span > 1: attrs["colspan"] = span
            cell_node = {"type": "tableCell"}
            if attrs: cell_node["attrs"] = attrs
            cell_node["content"] = [convert_paragraph(p) for p in cell.paragraphs]
            cells.append(cell_node)
            col += int(span or 1)
        rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "content": rows}


def convert(docx_path: str) -> dict:
    doc = Document(docx_path)
    body = doc.element.body
    return {"type": "doc",
            "content": [convert_paragraph(b) if isinstance(b, Paragraph) else convert_table(b)
                        for b in iter_blocks(body, doc)]}
```

要把这套骨架做到与 Java 版等价，必须补齐四件事：**run 预处理合并**、**`vMerge` 的 rowspan 计算与 continue 丢弃**、**`w:drawing` → `r:embed` → base64**、**域状态机**。验证方式：拿同一批 docx，Java 与 Python 各出一份 JSON，逐节点 diff（允许 `text` 分片不同，但把 JSON 拼成纯文本后必须完全一致）。

---

## 附 A：DOCX 元素 ↔ JSON 节点速查

| DOCX | JSON | 备注 |
|---|---|---|
| `w:body` | `body`（doc 节点） | 顺序遍历，勿扁平化 |
| `w:p` | `paragraph` / `heading` / `listItem` 内的 `paragraph` | 有 numId 且非标题 → 列表 |
| `w:pPr/w:jc` | `attrs.textAlign` | 必须回溯样式链 |
| `w:pPr/w:ind` | `attrs.textIndent/marginLeft/marginRight` | twip → pt |
| `w:pPr/w:spacing` | `attrs.lineHeight/marginTop/marginBottom` | AUTO → 倍数 |
| `w:pPr/w:outlineLvl` | `attrs.level` | 标题判定首选 |
| `w:r` | `text` + `marks` | 先合并同样式 run |
| `w:rPr/w:b|i|u|strike|vertAlign` | `bold|italic|underline|strike|superscript/subscript` | — |
| `w:rPr/w:color|rFonts|sz` | `textStyle{color,fontFamily,fontSize}` | 聚合成一个 mark |
| `w:t` | `text.text` | 唯一真正的文字 |
| `w:tab` | `text("\t")` 或点串 | 查 `w:tabs` 前导符 |
| `w:br @type=page` | `pageBreak` | 也可留给分页引擎 |
| `w:hyperlink` | `text` + `link` mark | `r:id` → rels |
| `w:fldChar`/`w:instrText` | 视域类型决定丢弃/保留 | 状态机 |
| `w:drawing`(uri=/picture) | `image` | `a:blip @r:embed` → media |
| `w:drawing`(uri=/wordprocessingShape) | 文本框 | 参考实现丢弃 |
| `m:oMath` | `text` | 分式 `a/b`、根式 `√()` |
| `w:tbl` | `table` | — |
| `w:tblGrid/w:gridCol` | 逻辑列数（建议 `attrs.colWidths`） | twip |
| `w:tr` / `w:tc` | `tableRow` / `tableCell` | — |
| `w:tcPr/w:gridSpan` | `attrs.colspan` | — |
| `w:tcPr/w:vMerge` | `attrs.rowspan` / 整格丢弃 | restart/continue |
| `w:tcPr/w:shd` | `attrs.background` | — |
| `w:sectPr` | `meta.pageConfig` | `pgSz`/`pgMar`/`orient` |
| `headerReference` / `footerReference` | `meta.header` / `meta.footer` | 独立 XML part |
| `{{KEY}}` 文本 | `variable{key,label}` | 单 run 内匹配 |

## 附 B：参考实现文件索引

| 文件 | 职责 | 关键方法/常量 |
|---|---|---|
| `service/PoiWordToTiptapConverter.java` | DOCX → JSON（主转换器） | `convert` / `convertBodyElements` / `convertParagraph` / `convertRunsInline` / `convertRun` / `buildMarks` / `convertTable` / `convertTableCell` / `calculateVSpan` / `extractTabStops` / `preprocessDocument` |
| `service/DocumentModelService.java` | JSON → HTML（布局引擎） | `renderToLayoutResult` / `fillModel` / `replaceVars` / `renderNodesToHtml` / `nodeToHtml` / `applyMark` / `buildParagraphStyle` / `renderHeaderHtml` / `renderFooterHtml` / `renderWatermarkCss` / `buildFullHtml`；系统变量 `page`/`totalPage` |
| `service/PaginationService.java` | JSON → 预分页 | `paginate` / `parsePageDimensions` / `estimateBlockHeight` / `estimateInlineWidth`；`CM_TO_PX=37.795`、`HEADING_SPECS` |
| `service/DocxVariableReplacer.java` | DOCX 层变量替换（LibreOffice 链路） | `replaceVariables` / `replaceInParagraph`；正则 `\{\{([^}]+)}}` |
| `service/PoiWordToHtmlConverter.java` | DOCX → HTML（另一条导出链，`BROWSER`/`EDITOR` 双模式） | `convertWithImages` / `buildParagraphStyleWithFlex` / `buildTableBorder` |
| `service/ai/OffsetMapper.java` + `TextSegment.java` | 纯文本偏移 ↔ 文本节点映射 | 供 LLM 标注变量后回填 |
| `service/ai/HtmlTemplateInjector.java` | 按偏移注入 `{{var}}` | 降序替换、跨节点合并 |
| `controller/WordConvertController.java` | 转换入口 | `POST /api/contract-template/convert-word-tiptap`（返回 `{json,title,method}`） |
| `entity/ContractTemplate.java` | 持久化 | `model_json`（LONGTEXT）、`docx_content`（LONGBLOB）、`variables_json` |
