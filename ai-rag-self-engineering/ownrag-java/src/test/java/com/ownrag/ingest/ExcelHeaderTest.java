package com.ownrag.ingest;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.apache.poi.ss.util.CellRangeAddress;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Excel 入库阻断项回归（docs 10-Excel通道口径.md §五）：
 * 表头行探测、多级表头、合并单元格、列名去重。
 * 这四条不成立时的表现不是"结果差一点"，而是 CREATE TABLE duplicate column 直接失败入待办。
 */
class ExcelHeaderTest {

    @Test
    void 表头在第一行() {
        List<List<String>> grid = grid(
                row("月份", "部门", "报销金额"),
                row("2024-01", "研发部", "12350.50"),
                row("2024-02", "市场部", "9120.75"));
        assertEquals(0, ExcelStageStep.detectHeaderRow(grid));

        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, new ArrayList<CellRangeAddress>());
        assertNotNull(t);
        assertEquals(Arrays.asList("月份", "部门", "报销金额"), t.columns);
        assertEquals(2, t.rows.size());
        assertFalse(t.twoLevel);
    }

    @Test
    void 跳过顶部标题行() {
        // 领导在 Excel 顶部写一行标题是常态：取第 0 行会把"部门/金额/日期"整个丢掉
        List<List<String>> grid = grid(
                row("2024年报销汇总", "", ""),
                row("部门", "金额", "日期"),
                row("研发部", "100", "2024-01-05"));
        assertEquals(1, ExcelStageStep.detectHeaderRow(grid));

        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, new ArrayList<CellRangeAddress>());
        assertNotNull(t);
        assertEquals(Arrays.asList("部门", "金额", "日期"), t.columns);
        assertEquals(1, t.rows.size());
    }

    @Test
    void 多级表头合并成父_子() {
        List<List<String>> grid = grid(
                row("费用", "", "", "备注"),
                row("交通", "住宿", "餐费", ""),
                row("100", "200", "300", "含税"));
        List<CellRangeAddress> merged = new ArrayList<>();
        merged.add(new CellRangeAddress(0, 0, 0, 2));   // 父级「费用」横向合并 3 列

        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, merged);
        assertNotNull(t);
        assertTrue(t.twoLevel, "父级行有空洞 + 子级纯文本 → 必须识别为两级表头");
        assertEquals(0, t.headerRow);
        assertEquals(Arrays.asList("费用_交通", "费用_住宿", "费用_餐费", "备注"), t.columns);
        assertEquals(1, t.rows.size(), "第二行是表头，不是数据行");
        assertEquals(Arrays.asList("100", "200", "300", "含税"), t.rows.get(0));
    }

    @Test
    void 重名列自动加后缀() {
        // 现状是 CREATE TABLE 直接报 duplicate column；重名是 Excel 里最常见的脏数据形态之一
        assertEquals(Arrays.asList("金额", "金额_2", "金额_3"),
                ExcelStageStep.dedup(Arrays.asList("金额", "金额", "金额")));
        assertEquals(Arrays.asList("金额_2", "金额_2_2"),
                ExcelStageStep.dedup(Arrays.asList("金额_2", "金额_2")));

        List<List<String>> grid = grid(
                row("金额", "金额 ", "备注"),
                row("1", "2", "x"));
        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, new ArrayList<CellRangeAddress>());
        assertNotNull(t);
        assertEquals(Arrays.asList("金额", "金额_2", "备注"), t.columns);
        // 物理名同样必须唯一，否则 DDL 直接失败
        assertEquals(3, new java.util.LinkedHashSet<>(t.physical).size());
    }

    @Test
    void 整列全空的列被丢弃() {
        List<List<String>> grid = grid(
                row("a", "b", ""),
                row("1", "2", ""));
        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, new ArrayList<CellRangeAddress>());
        assertNotNull(t);
        assertEquals(Arrays.asList("a", "b"), t.columns);
    }

    @Test
    void 表头合并单元格向右填充() {
        // 合并区在表头行：不填充就会出现空列名 → 退化成 col_1，schema linking 无从下手
        List<List<String>> grid = grid(
                row("费用", "", "备注"),
                row("交通", "住宿", "餐费"),
                row("100", "200", "300"));
        List<CellRangeAddress> merged = new ArrayList<>();
        merged.add(new CellRangeAddress(0, 0, 0, 1));

        ExcelStageStep.Table t = ExcelStageStep.toTable(grid, merged);
        assertNotNull(t);
        assertEquals(1, t.mergedHeader);
        for (String name : t.columns) {
            assertFalse(name.startsWith("col_"), "表头合并没填充：" + t.columns);
        }
    }

    private static List<String> row(String... values) {
        return new ArrayList<>(Arrays.asList(values));
    }

    @SafeVarargs
    private static List<List<String>> grid(List<String>... rows) {
        return new ArrayList<>(Arrays.asList(rows));
    }
}
