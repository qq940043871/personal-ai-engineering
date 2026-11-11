# EXCEL / XLSX 表格格式标准与解析完整指南

> 本文档与《PDF 格式标准与解析指南》配套，覆盖 Excel 工作簿的开放标准背景、两代容器结构（BIFF 二进制 vs OPC/ZIP 包）、工作簿对象树、单元格取值与显示值的差异、合并单元格与公式的处理，以及实际解析策略与常见坑位。

---

## 一、Excel 文件是开放标准吗？

和 Word 一样，要按扩展名区分：

| 扩展名 | 格式名 | 本质 | 标准状态 |
|---|---|---|---|
| `.xls` | Excel 97-2003 Binary（BIFF8） | **OLE2 复合文档**，内部是二进制记录流 | 微软公开 **[MS-XLS]**，属"公开的私有格式" |
| `.xlsx` | SpreadsheetML | **OOXML（ZIP + XML）** | **ECMA-376 / ISO/IEC 29500**，真正的开放标准 |
| `.xlsm` | 启用宏的工作簿 | 同 `.xlsx` + `vbaProject.bin` | 同上 |
| `.xlsb` | Excel Binary Workbook（BIFF12） | **ZIP 容器，但内容是二进制记录** | ECMA-376 Part 1 内的二进制部件约定 |
| `.csv` | 纯文本 | 无格式，只有行列 | 无标准（RFC 4180 是事实约定） |

| 时间 | 事件 |
|---|---|
| 1985–2003 | BIFF2 → BIFF8，逐年演化，靠逆向工程和 `[MS-XLS]` 才能读 |
| 2006 | OOXML 随 ECMA-376 发布，`.xlsx` 出现（Excel 2007） |
| 2008 | OOXML 成为 **ISO/IEC 29500** |
| 2012 起 | `[MS-XLS]`、`[MS-XLSB]` 文档公开 |

三个必须知道的事实：

1. **`.xlsx` 是 XML，但可读性不等于简单**：一个普通 sheet 的 XML 里有几十种属性，且大量信息（列宽、样式）和值分离。
2. **`.xls` 与 `.xlsx` 的数据模型不同**：BIFF8 有"记录"概念（`LABELSST`、`NUMBER`、`RK`、`MULRK`），OOXML 有"单元格元素 + 共享字符串表"概念。
3. **`.xlsb` 常被误认为 zip 就能读**：它能 unzip，但 `.bin` 部件是二进制记录，必须用 `pyxlsb` 这类专门解析器。

---

## 二、两代容器结构

### 1. `.xlsx`：OPC 包（本质是 ZIP）

把后缀改成 `.zip` 即可解开：

```text
a.xlsx (ZIP)
├─ [Content_Types].xml
├─ _rels/.rels
├─ docProps/core.xml, app.xml
└─ xl/
     ├─ workbook.xml              # ★ 工作簿：sheet 列表、定义名称、1904 开关
     ├─ _rels/workbook.xml.rels   # rId → 各 sheet 路径
     ├─ worksheets/
     │    ├─ sheet1.xml           # ★ 单元格数据
     │    └─ sheet2.xml
     ├─ sharedStrings.xml         # ★ 共享字符串表（所有文本单元格的实际文字）
     ├─ styles.xml                # ★ 数字格式、字体、边框、填充（决定"显示值"）
     ├─ theme/theme1.xml
     ├─ tables/table1.xml         # 结构化表格（带表头、可被公式引用）
     ├─ drawings/drawing1.xml     # 图片、形状
     ├─ charts/chart1.xml         # 图表
     ├─ media/image1.png
     ├─ comments1.xml             # 旧式批注
     ├─ threadedComments/…        # 新式（@提及）批注
     ├─ pivotCache/, pivotTables/ # 数据透视表
     ├─ calcChain.xml             # 计算链（只记录"哪些格是公式"）
     └─ externalLinks/            # 外部工作簿引用
```

关键点：

- **`workbook.xml` 决定 sheet 的顺序和名称**，而 `worksheets/sheetN.xml` 的文件名编号**不一定对应显示顺序**（重命名/移动/删除 sheet 后编号会错位）——必须通过 `workbook.xml.rels` 的 `rId` 映射；
- **文本不在 sheet 里**，而是在 `sharedStrings.xml` 里按索引共享，sheet 里只存 `<v>12</v>` 这样的下标；
- **日期、百分比、货币、千分位都不是数据类型**，只是数字 + 一个 `numFmtId`。这是 Excel 解析最大的认知门槛。

### 2. `.xls`：BIFF8 记录流

`.xls` 是 OLE2 复合文档，核心是一个 `Workbook`（旧版叫 `Book`）流，里面是**顺序排列的变长记录**：

```text
记录 = [2 字节类型 type][2 字节长度 len][len 字节数据]

BOF(0x0809)            # 流开始，声明 BIFF 版本
  BOUNDSHEET(0x0085)   # 每个 sheet：名字 + 数据起始偏移
  SST(0x00FC)          # 共享字符串表（超长时用 CONTINUE 记录拼接）
  FORMAT / XF          # 数字格式、单元格格式索引
  ...
BOF → sheet 数据
  DIMENSIONS(0x0200)   # 数据范围
  ROW(0x0208)          # 行属性（高度、隐藏）
  LABELSST(0x00FD)     # 文本单元格：行、列、XF、SST 索引
  NUMBER(0x0203)       # 浮点数
  RK(0x027E)           # 压缩数字（整数/浮点的小编码）
  MULRK(0x00BD)        # 一行多个 RK
  FORMULA(0x0006)      # 公式 + 缓存结果
  STRING(0x0207)       # 公式的字符串结果
  MERGEDCELLS(0x00E5)  # 合并区域
  EOF(0x000A)
```

难点：

- `RK` 编码把数字压缩在 4 字节里（低位标记 ×100 / ÷100 / 整数 / IEEE754 高位），手写解析极易出错；
- `SST` 超过 8224 字节会被拆到多条 `CONTINUE` 记录，**字符串可能跨记录边界**；
- 中文用 UTF-16LE，但每个字符串带"压缩/非压缩"标志；
- 单元格格式（`XF`）要回溯到 `FORMAT` 才能知道显示格式。

**实践结论：`.xls` 不要手写解析器，用 `xlrd`（1.x/2.x 读 xls）或 `python-calamine`，或者 LibreOffice 转 `.xlsx`。**

### 3. `.xlsb`：ZIP + 二进制记录

能 unzip，`xl/worksheets/sheet1.bin` 是 BIFF12 记录，需要 `pyxlsb`。注意 `pyxlsb` 支持读单元格值，但对样式/合并单元格支持有限。

---

## 三、工作簿在对象树中的表示

```text
xl/workbook.xml
├─ workbookPr (@date1904)          # 日期系统开关
├─ sheets
│    └─ sheet (name, sheetId, r:id) # ★ 显示顺序以这里为准
├─ definedNames                     # 定义名称（含打印区域、命名区域）
└─ calcPr

xl/worksheets/sheetN.xml
├─ sheetPr
├─ dimension (@ref)                 # 声称的数据范围（★ 不可全信）
├─ sheetViews                       # 冻结窗格、缩放、选中格
├─ sheetFormatPr                    # 默认行高、默认列宽
├─ cols                             # 列宽、隐藏、分组
│    └─ col (min, max, width, hidden, outlineLevel)
├─ sheetData                        # ★ 真正的数据
│    └─ row (@r 行号, @ht, @hidden, @outlineLevel)
│         └─ c (@r 单元格地址, @t 类型, @s 样式索引)
│              ├─ f                  # 公式
│              ├─ v                  # 值（数字或共享字符串索引）
│              └─ is                 # 内联字符串（t="inlineStr"）
├─ mergeCells                       # 合并区域
├─ conditionalFormatting            # 条件格式（不改 <v>）
├─ dataValidations                  # 下拉/校验规则
├─ hyperlinks                       # 超链接
├─ printOptions / pageSetup         # 打印设置
├─ drawing                          # 图片、图表
├─ legacyDrawing                    # 旧式批注锚点
└─ tableParts                       # 引用 xl/tables/
```

关键点：

- **单元格是稀疏存储**：只有有值/有格式的格子才出现，中间的空行空列完全不写，必须按 `@r` 与 `r="B12"` 自行还原坐标；
- **`row` 的 `@r` 可以不连续**，`c` 的 `@r` 也可以跳（`A1`、`D1`、`H1`）；
- **`dimension` 不可信**：某些生成器（Java POI、Python 库、在线导出）会写错，直接用会截断数据；遍历 `sheetData` 才是真相；
- 列宽用 `col @width`（字符宽度，基于默认字体的最大数字宽度），行高用 `row @ht`（磅），**隐藏行/列靠 `hidden="1"`**。

---

## 四、单元格怎么存值

### 1. `t` 属性（数据类型）全表

```xml
<c r="B2" t="s" s="3"><v>42</v></c>
```

| `@t` 取值 | 含义 | `<v>` 内容 |
|---|---|---|
| 省略（默认 `n`） | 数字 | 数字字面量，如 `3.14`、`1.2E-5` |
| `s` | **共享字符串** | `sharedStrings.xml` 里的**下标** |
| `inlineStr` | 内联字符串 | 文字在 `<is><t>` 里，不用 SST |
| `str` | 公式的字符串结果 | 字符串字面量 |
| `b` | 布尔 | `0` / `1` |
| `e` | 错误值 | `#DIV/0!`、`#N/A`、`#REF!` |
| `d` | ISO 8601 日期（少见） | `2024-01-15T00:00:00` |

### 2. 共享字符串表（SST）

```xml
<sst count="120" uniqueCount="98">
  <si><t>姓名</t></si>
  <si><r><rPr><b/></rPr><t>张</t></r><r><t>三</t></r></si>   <!-- 富文本 -->
  <si><t xml:space="preserve"> 前后有空格 </t></si>
</sst>
```

要点：

- `<si>` 可能是**富文本**（多个 `<r>`），要拼接所有 `<t>` 才是完整文字；
- `<t xml:space="preserve">` 表示有首尾空格，**不能 strip**（业务字段里可能真的有意义）；
- 可能带 `<rPh>`（日文注音/拼音），**不属于正文**，要排除；
- `uniqueCount` 是去重后的条数，`count` 是引用总次数，用 `uniqueCount` 校验数据完整性。

### 3. 公式与缓存值

```xml
<c r="C1"><f>A1+B1</f><v>300</v></c>
<c r="D1"><f t="shared" ref="D1:D10" si="0">A1*2</f><v>200</v></c>
<c r="D2"><f t="shared" si="0"/><v>400</v></c>          <!-- 共享公式的后续格 -->
<c r="E1"><f t="array" ref="E1:E5">{SUM(A1:A5*B1:B5)}</f><v>1</v></c>
```

| 公式类型 | 标记 | 说明 |
|---|---|---|
| 普通公式 | `<f>` | 每格各写一遍 |
| 共享公式 | `t="shared" ref=... si=N` | **只有首格有公式文本**，后续格是空 `<f si="N"/>` |
| 数组公式 | `t="array" ref=...` | 一个公式覆盖区域 |
| 数据表 | `t="dataTable"` | 模拟运算表 |

**`<v>` 是缓存值**，由 Excel 上次计算写入。所以：

- `openpyxl.load_workbook(data_only=True)` 读的是 `<v>`，**从没被 Excel 打开保存过的文件，`<v>` 可能不存在** → 返回 `None`；
- 用 `data_only=False` 读的是 `<f>`，拿到公式文本但拿不到结果；
- 想要"重算后的值"，只能用 Excel COM / LibreOffice 无头重算，或者自己实现公式引擎（不现实）。

### 4. 富文本与换行

- 单元格内换行是 `\n`（`<t>` 里的真实换行符），配合 `wrapText` 显示；读出来就是 `\n`；
- 富文本单元格部分加粗/变色不影响取值，只是多几个 `<r>`；
- 超长字符串在 BIFF8 里会被 `CONTINUE` 拆断，OOXML 里没有这个问题。

---

## 五、"值"与"显示"的差异（最核心的坑）

Excel 里 **`2024-01-15` 存的是 `45306`**，**`15%` 存的是 `0.15`**，**`1,234.56` 存的是 `1234.56`**。差异全部来自 `styles.xml`：

```text
styles.xml
├─ numFmts
│    └─ numFmt (numFmtId=176, formatCode="yyyy""年""m""月""d""日""")
├─ fonts / fills / borders
├─ cellStyleXfs                     # 命名样式的格式
└─ cellXfs                        # ★ 单元格格式（被 c/@s 索引）
     └─ xf (numFmtId=176, fontId=1, fillId=0, borderId=0, applyNumberFormat=1)
```

`<c r="B2" s="3">` 的 `s="3"` 就是 `cellXfs` 的第 3 项（0 基），从中取 `numFmtId`，再决定怎么解释 `<v>`。

### 1. 内置 `numFmtId` 速查

| numFmtId | 格式 | 类型 |
|---|---|---|
| 0 | `General` | 通用（自动判断） |
| 1 | `0` | 整数 |
| 2 | `0.00` | 两位小数 |
| 3 | `#,##0` | 千分位整数 |
| 4 | `#,##0.00` | 千分位两位小数 |
| 9 | `0%` | 百分比 |
| 10 | `0.00%` | 两位百分比 |
| 11 | `0.00E+00` | 科学计数 |
| 14 | `m/d/yyyy` | 日期 |
| 15 | `d-mmm-yy` | 日期 |
| 16 / 17 | `d-mmm` / `mmm-yy` | 日期 |
| 18–21 | `h:mm AM/PM` 等 | 时间 |
| 22 | `m/d/yyyy h:mm` | 日期时间 |
| 37–40 | 会计专用 | 货币 |
| 45 / 46 / 47 | `mm:ss` / `[h]:mm:ss` / `mmss.0` | 时长 |
| 49 | `@` | **文本** |

自定义格式从 164 开始编号，定义在 `numFmts` 里。

### 2. 日期序列号

| 日期系统 | 起点 | 说明 |
|---|---|---|
| 1900（Windows 默认） | `1900-01-01 = 1` | **含虚构的 1900-02-29**，导致序列号 60 不存在；序列号 ≥61 才与真实日期对齐 |
| 1904（Mac 传统） | `1904-01-01 = 0` | 由 `workbookPr @date1904="1"` 标记 |

```python
from datetime import datetime, timedelta

def serial_to_datetime(v, date1904=False):
    if date1904:
        return datetime(1904, 1, 1) + timedelta(days=float(v))
    # 1900 系统的经典写法：以 1899-12-30 为基准
    return datetime(1899, 12, 30) + timedelta(days=float(v))
```

`1899-12-30` 这个"魔法基准"同时吸收了两个 bug：1900 闰年虚构日 + 序列号从 1 开始的偏移。对 `1..59` 的早期序列号会有 1 天误差，实务中几乎不影响。

**时间也是小数**：`0.5` = 12:00:00；`1.5` = 1900-01-01 12:00。带 `[h]` 的格式表示"超过 24 小时的时长"，不要转成日期。

### 3. 格式决定语义的几种情况

| 存储值 | numFmt | 真实含义 | 解析注意 |
|---|---|---|---|
| `45306` | `yyyy-mm-dd` | 2024-01-15 | 不转就是"四万五" |
| `0.1536` | `0.00%` | 15.36% | 展示值与存储值差 100 倍 |
| `1234567` | `#,##0,,"万"` | 123 万 | **千位分隔符里逗号可当缩放** |
| `1` | 自定义 `"是";"否"` | 布尔语义 | 靠格式区分正负数/文字 |
| `20240115` | `General` | 数字，非日期 | 需要业务规则判断 |
| `"0012"` | `@` | 文本 | 前导零必须按文本保留 |

### 4. 判断"这一格到底显示什么"

```python
from openpyxl import load_workbook

wb = load_workbook("a.xlsx", data_only=True)
ws = wb["Sheet1"]
c = ws["B2"]
print(c.value)          # 存储值
print(c.number_format)  # 格式串，如 "yyyy-mm-dd" / "0.00%" / "@"
print(c._style.numFmtId)
```

判定流程：

```text
read <v> + cellXfs[s].numFmtId
  ├─ numFmtId ∈ 日期集合 ∪ 自定义含 y/m/d/h/s → 序列号转 datetime
  ├─ 格式含 "%"                                  → 值 × 100 再加 %
  ├─ 格式含 "@" 或 t="s"/inlineStr               → 文本
  ├─ 格式含 "[Red]"、条件段（;）                 → 分段显示，注意取对应段
  └─ 其他                                        → 数值原样
```

---

## 六、合并单元格、隐藏、分组与其他结构

### 1. 合并单元格

```xml
<mergeCells count="2">
  <mergeCell ref="A1:C1"/>
  <mergeCell ref="B2:B5"/>
</mergeCells>
```

**关键事实：只有左上角那一格有值，其余全为空 `<c>`（或根本不存在）。**

这就是"读出来一堆 NaN"的根因。处理方式：

```python
def fill_merged(ws):
    for rng in ws.merged_cells.ranges:
        top_left = ws.cell(rng.min_row, rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                if r == rng.min_row and c == rng.min_col:
                    continue
                ws.cell(r, c).value = top_left   # 或按业务决定是否回填
```

是否回填要看语义：

- **表头合并**（`A1:C1` 是大标题）→ 回填会造成重复，应该"向下/向**上**合并成列名"或直接丢弃；
- **纵向合并的分类列**（`B2:B5` 都是"华东区"）→ 回填才正确；
- **横向合并的数据格** → 一般回填。

### 2. 隐藏与分组

| 特性 | 位置 | 影响 |
|---|---|---|
| 隐藏 sheet | `workbook.xml` 中 `sheet @state="hidden"` / `"veryHidden"` | 默认不该抽，但可能是数据源 |
| 隐藏行 | `row @hidden="1"` | 过滤行可能是"已作废"数据 |
| 隐藏列 | `col @hidden="1"` + `@min/@max` | 辅助列/公式列 |
| 分组折叠 | `@outlineLevel` + `@collapsed` | 明细行被折叠 |
| 冻结窗格 | `sheetView/pane` | 说明前 N 行是表头（有用的启发式） |
| 筛选 | `autoFilter` | 当前视图是筛选后的子集 |

### 3. 条件格式

```xml
<conditionalFormatting sqref="C2:C100">
  <cfRule type="cellIs" operator="greaterThan" dxfId="0"><formula>100</formula></cfRule>
</conditionalFormatting>
```

要点：**条件格式只改显示，不改 `<v>`**。所以"用红色标出的异常值"在数据里看不出任何异常 —— 如果业务含义依赖颜色（常见于财务表），必须解析 `dxfs` 与规则，或者退化为"颜色不可恢复"。

### 4. 其他结构化信息

| 信息 | 文件/元素 | 用途 |
|---|---|---|
| 定义名称 | `workbook.xml/definedNames` | 命名区域、打印区域、常量 |
| 结构化表格 | `xl/tables/tableN.xml` | **真表头 + 结构化引用，是最好的表格边界来源** |
| 数据透视表 | `pivotTables/` + `pivotCache/` | 透视结果是缓存，源数据在别处 |
| 超链接 | `hyperlinks` + `.rels` | `#Sheet2!A1` 内部跳转 / 外部 URL |
| 批注 | `comments1.xml` / `threadedComments/` | 说明、审阅意见 |
| 图片/图表 | `drawings/drawingN.xml` | 锚定在单元格上（`from/to` 行列） |
| 数据验证 | `dataValidations` | 下拉选项、取值范围 |
| 数组/动态数组 | `t="array"`、`_xlfn.` 前缀 | 溢出区域 |

### 5. 一个 sheet 里可能有多个表

Excel 没有"表"的强边界，除了 `tableParts`。常见的脏结构：

```text
A1:  "2024年销售统计表"        ← 大标题
A2:  "单位：万元"              ← 单位说明
A3:  表头行
A4-A100: 数据
A102: 空行
A103: "备注：数据来源财务系统"  ← 脚注
A105: 另一个表（不同列数）
```

所以**不能假设"第一个非空行就是表头"**，需要：
- 用 `dimension` + 实际数据扫描找出连续非空区块；
- 用列数变化/空行切分多表；
- 用冻结窗格位置、加粗+填充色（样式）辅助识别表头。

---

## 七、实际解析策略与常见坑

### 推荐解析路径

1. **先读 `workbook.xml`**：拿到 sheet 的真实顺序、名称、隐藏状态、`date1904`；
2. **读 `sharedStrings.xml`**：建立下标 → 文本的数组（处理富文本与 `rPh`）；
3. **读 `styles.xml`**：建立 `cellXfs 索引 → numFmtId → 格式语义（日期/百分比/文本/数值）` 映射；
4. **流式遍历 `sheetData`**：按 `row @r` 和 `c @r` 还原坐标，不要依赖 `dimension`；
5. **应用合并区域**：先收集 `mergeCells`，再决定回填策略；
6. **按格式解释值**：日期序列号转 `datetime`，百分比记原值 + 格式，文本保持字符串；
7. **识别表结构**：连续非空区块 + 列数稳定性 + 表头候选行；
8. **输出**：二维数组 + 表头 + sheet 名 + 单元格坐标（溯源用）。

### 六个容易踩的坑

1. **`data_only=True` 返回 `None`**：文件从未被 Excel 计算保存，`<v>` 不存在。解决：要求上游用 Excel 打开保存一次，或 LibreOffice 无头重算后另存。
2. **合并单元格导致大面积空值**：见上一节，必须先合并再判空。
3. **日期变数字**：不读 `numFmt` 就永远不知道 `45306` 是什么；`openpyxl` 会自动转常见日期格式，但**自定义格式的日期不转**（比如 `yyyy"年"m"月"`），需要自己处理。
4. **数字被存成文本**：`"0012"`、`"1,234"`、`"15%"`、`"2024.1.1"`。`pandas` 会把整列判成 `object`，做汇总直接报错或结果错误。
5. **表头不在第一行 / 多级表头**：大标题、单位行、双层表头（合并单元格）非常常见，硬编码 `header=0` 会毁掉整张表。
6. **一个 sheet 多张表**：`pandas.read_excel` 只会当成一张畸形大表，必须自己切块。

### 其他次要但要留意的点

| 现象 | 原因 | 处理 |
|---|---|---|
| `dimension` 与实际不符 | 生成器写错 / 有格式无值的格子 | 忽略 `dimension`，遍历 `sheetData` |
| 超大文件内存爆掉 | `openpyxl` 默认全量加载 | `read_only=True` + `iter_rows()`，或 `python-calamine` |
| `read_only` 模式取不到合并单元格 | 该模式下 `ws.merged_cells` 不可用 | 先用普通模式读 `mergeCells`，或直接解 XML |
| 科学计数法丢失精度 | Excel 只有 **15 位有效数字** | 超过 15 位的 ID/卡号必须存成文本 |
| 公式引用了外部工作簿 | `externalLinks/` | 缓存值可能是旧的或 `#REF!` |
| 新函数读不出来 | `_xlfn.XLOOKUP`、`_xlfn.CONCAT` 前缀 | 解析时去掉 `_xlfn.` 前缀 |
| 中文乱码 | `.xls` 的 SST 编码判错 / GBK 编的 CSV | 用 `xlrd` 或 `calamine`；CSV 显式指定 `encoding` |
| 单元格内换行变空格 | 解析时做了 `strip()`/`join` | 保留 `\n`，按需替换 |
| 加密文件打不开 | 头部不是 `PK`，是 OLE 的 `EncryptedPackage` | 需要口令（`msoffcrypto-tool`） |
| `.xlsm` 打不开 | 有 `vbaProject.bin` | 正常读数据即可，宏不需要解析 |

### 快速选型建议（按场景）

| 场景 | 推荐方案 |
|---|---|
| 常规读 `.xlsx`（小文件） | `openpyxl`（`data_only=True`） |
| 大文件 / 只读流式 | `openpyxl` `read_only=True` 或 `python-calamine` |
| 数据分析、多 sheet 批量 | `pandas.read_excel(engine="calamine")` |
| 读 `.xls` | `xlrd`（2.x 仅支持 xls）或 `python-calamine` |
| 读 `.xlsb` | `pyxlsb` |
| 需要公式重算 | Excel COM / LibreOffice 无头重算 |
| 需要格式/颜色/边框 | `openpyxl`（`load_workbook` 非 `data_only`） |
| 表格抽取 → Markdown（RAG） | `markitdown`、`pandas.to_markdown`，或自研 + `openpyxl` |
| 提取图片/图表 | 直接解 ZIP 取 `xl/media/`、`xl/charts/` |

**RAG / 知识库场景的切块建议**：

- **一个 sheet 的连续数据区块 = 一个块**，块头写清 `文件 > sheet > 区域`；
- 表格转 Markdown 时补齐合并单元格、保留表头，**不要把一行拆成多块**；
- 数字列保留单位说明（"单位：万元"这类行要绑到表头上，不能丢）；
- 公式列要么带缓存值，要么标注"计算列"；
- 隐藏 sheet / 隐藏行默认不进索引，但要记录存在；
- 超宽表（几百列）优先按"实体-属性"转置成键值对再切块。

---

## 附：Excel 解析技术路线总览

| 文件类型 | 特征 | 推荐路线 |
|---|---|---|
| `.xlsx` 普通表 | ZIP + XML，值/格式分离 | `openpyxl` / `python-calamine` |
| `.xlsx` 大文件（10 万行+） | 全量加载会 OOM | `read_only=True` + 流式遍历 |
| `.xlsx` 含图表/图片/透视 | 数据在 `drawings`/`pivotCache` | 数据用 `openpyxl`，资源解 ZIP |
| `.xls` 老档案 | BIFF8 二进制记录 | `xlrd` / `calamine` / LibreOffice 转 xlsx |
| `.xlsb` 二进制工作簿 | ZIP 但内容为 BIFF12 | `pyxlsb` |
| 加密工作簿 | `EncryptedPackage` | `msoffcrypto-tool` 解密后再解析 |
| 报表类（多表头/多区块） | 一个 sheet 多张表 | 自研区块切分 + 表头识别 |
| 财务/对账类 | 依赖颜色与格式表达语义 | 必须解析 `styles.xml` + 条件格式 |
| CSV | 纯文本 | `pandas` + 显式 `encoding` / `sep` |
