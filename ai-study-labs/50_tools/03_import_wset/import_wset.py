#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import openpyxl  # 替换xlrd库

# 读取sql文件中的字段和表对应关系
def read_sql_mapping(sql_file_path):
    mapping = {}
    table_fields = {}
    
    # 读取文件时指定UTF-8编码
    with open(sql_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if not line or line.startswith("INSERT"):
            continue
        
        # 解析每行数据，如："第A2列数据：WSETNO,对应表TB_SET_WSETMATCH,TB_SET_WSETMATCHDTL"
        parts = line.split('：')
        if len(parts) < 2:
            continue
        
        # 获取字段和表信息
        field_info = parts[1].split(',对应表')
        if len(field_info) < 2:
            continue
        
        field_name = field_info[0]
        tables = field_info[1].split(',')
        
        # 存储字段和表的对应关系
        mapping[field_name] = tables
        
        # 为每个表收集字段
        for table in tables:
            if table not in table_fields:
                table_fields[table] = []
            table_fields[table].append(field_name)
    
    print("SQL映射关系：", mapping)
    print("表字段映射：", table_fields)
    return mapping, table_fields

# 生成SQL INSERT语句
def generate_sql_insert(table_name, fields, row_data):
    values = []
    header_row = row_data[0]
    row_values = row_data[1]
    
    print(f"\n处理表 {table_name}：")
    print(f"需要的字段：{fields}")
    print(f"Excel表头：{header_row}")
    
    for field in fields:
        # 在row_data中找到对应的值
        field_index = None
        
        # 尝试精确匹配
        for i, col_name in enumerate(header_row):
            if col_name is not None and field.strip() == col_name.strip():
                field_index = i
                break
        
        # 如果精确匹配失败，尝试模糊匹配
        if field_index is None:
            for i, col_name in enumerate(header_row):
                if col_name is not None and field.strip().lower() in str(col_name).strip().lower():
                    field_index = i
                    print(f"  模糊匹配：{field} -> {col_name}")
                    break
        
        if field_index is not None and field_index < len(row_values):
            value = row_values[field_index]
            print(f"  字段 {field} = {value} (类型: {type(value)})")
            
            # 根据值的类型处理
            if value is None:
                values.append("NULL")
            elif isinstance(value, str):
                # 处理字符串，转义单引号
                values.append("'" + value.replace("'", "''") + "'")
            elif isinstance(value, float):
                # 检查是否是整数
                if value.is_integer():
                    values.append(str(int(value)))
                else:
                    values.append(str(value))
            else:
                values.append("'" + str(value).replace("'", "''") + "'")
        else:
            print(f"  未找到字段 {field}")
            values.append("NULL")
    
    sql = "INSERT INTO {table} ({fields}) VALUES ({values});".format(
        table=table_name,
        fields=", ".join(fields),
        values=", ".join(values)
    )
    
    print(f"生成SQL：{sql}")
    return sql

# 主函数
def main():
    # 文件路径
    excel_file_path = "d:/workspace/p012_import_wset/batch_wset_one.xlsx"
    sql_file_path = "d:/workspace/p012_import_wset/sql"
    output_file_path = "d:/workspace/p012_import_wset/generated_sql.sql"
    
    # 读取字段和表的对应关系
    mapping, table_fields = read_sql_mapping(sql_file_path)
    print("字段和表的对应关系已读取")
    
    # 读取Excel文件
    try:
        workbook = openpyxl.load_workbook(excel_file_path)
        sheet = workbook.active  # 获取活动工作表
        print("Excel文件已打开，工作表名称：", sheet.title)
    except Exception as e:
        print("读取Excel文件失败：", e)
        return
    
    # 获取表头行（第一行）
    header_row = []
    for cell in sheet[1]:  # 第一行是表头
        header_row.append(cell.value)
    print("表头行：", header_row)
    
    # 准备写入SQL语句
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        # 遍历Excel中的数据行（从第二行开始）
        for row_idx in range(2, min(sheet.max_row + 1, 10)):  # 只处理前10行用于测试
            row_values = []
            for cell in sheet[row_idx]:
                row_values.append(cell.value)
            print("处理行：", row_idx - 1, row_values)  # 输出从1开始的行号
            
            # 构建当前行的数据结构
            row_data = (header_row, row_values)
            
            # 为每个表生成SQL语句
            for table_name, fields in table_fields.items():
                sql = generate_sql_insert(table_name, fields, row_data)
                output_file.write(sql + "\n")
    
    print("SQL语句已生成并保存到：", output_file_path)

if __name__ == "__main__":
    main()