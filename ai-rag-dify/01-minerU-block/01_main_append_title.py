import os
import sys
from collections import defaultdict


def slice_markdown_by_delimiter(file_path, output_file="sliced_output.md", delimiter="@!@"):
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件 {file_path} 不存在")

        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            # 删除空行
            lines = [line for line in f.readlines() if line.strip() != '']

        # 提取一级标题
        main_title = None
        for line in lines:
            if line.startswith('# '):
                main_title = line.strip()[2:].strip()
                break

        if not main_title:
            raise ValueError("未找到一级标题")

        # 收集所有标题结构
        h2_titles = []  # 二级标题顺序
        h2_h3_mapping = defaultdict(list)  # 二级标题 -> 对应的三级标题列表
        current_h2 = None
        current_h3 = None

        # 先扫描整个文件，建立标题结构
        for line in lines:
            line = line.strip()
            if line.startswith('## '):
                current_h2 = line[3:].strip()
                if current_h2 not in h2_titles:
                    h2_titles.append(current_h2)
                current_h3 = None
            elif line.startswith('### '):
                current_h3 = line[4:].strip()
                if current_h2 and current_h3 not in h2_h3_mapping[current_h2]:
                    h2_h3_mapping[current_h2].append(current_h3)

        # 处理内容分割
        h2_segments = defaultdict(list)  # 二级标题 -> 分割后的内容块
        h3_segments = defaultdict(lambda: defaultdict(list))  # 二级标题 -> 三级标题 -> 分割后的内容块

        current_h2 = None
        current_h3 = None
        current_block = []

        def process_block(block, h2, h3=None):
            if not block:
                return
            content = '\n'.join(block).strip()
            if not content:
                return

            if delimiter in content:
                segments = [s.strip() for s in content.split(delimiter) if s.strip()]
                if h3:
                    h3_segments[h2][h3].extend(segments)
                else:
                    h2_segments[h2].extend(segments)
            else:
                if h3:
                    h3_segments[h2][h3].append(content)
                else:
                    h2_segments[h2].append(content)

        for line in lines:
            line = line.strip()
            if not line:
                current_block.append('')
                continue

            if line.startswith('## '):
                if current_h2 is not None:
                    process_block(current_block, current_h2, current_h3)
                    current_block = []
                current_h2 = line[3:].strip()
                current_h3 = None
            elif line.startswith('### '):
                if current_h2 is not None:
                    process_block(current_block, current_h2, current_h3)
                    current_block = []
                current_h3 = line[4:].strip()
            elif current_h2 is not None:
                current_block.append(line)

        # 处理最后一个块
        if current_h2 is not None and current_block:
            process_block(current_block, current_h2, current_h3)

        # 生成输出
        output_lines = []
        total_h2_parts = len(h2_titles)

        for h2_idx, h2 in enumerate(h2_titles, 1):
            # 处理二级标题下的直接内容（没有三级标题的内容）
            if h2 in h2_segments:
                segments = h2_segments[h2]
                total_segments = len(segments)

                for seg_idx, segment in enumerate(segments, 1):
                    output_lines.append(f"@!@\n")
                    output_lines.append(f"# {main_title}(第{h2_idx}部分)[共{total_h2_parts}部分]\n")
                    output_lines.append(f"## {h2}(第{seg_idx}部分)[共{total_segments}部分]\n")
                    output_lines.append(segment + '\n\n')

            # 处理三级标题下的内容
            if h2 in h2_h3_mapping:
                for h3_idx, h3 in enumerate(h2_h3_mapping[h2], 1):
                    if h3 in h3_segments[h2]:
                        segments = h3_segments[h2][h3]
                        total_segments = len(segments)

                        for seg_idx, segment in enumerate(segments, 1):
                            output_lines.append(f"@!@\n")
                            output_lines.append(f"# {main_title}(第{h2_idx}部分)[共{total_h2_parts}部分]\n")
                            output_lines.append(f"## {h2}(第{h3_idx}部分)[共{len(h2_h3_mapping[h2])}部分]\n")
                            output_lines.append(f"### {h3}(第{seg_idx}部分)[共{total_segments}部分]\n")
                            output_lines.append(segment + '\n\n')

        # 写入输出文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)

        print(f"✅ 已生成：{output_file}")

    except Exception as e:
        print(f"❌ 错误: {e}")


def main():
    if len(sys.argv) < 2:
        print("请提供输入文件名作为参数")
        print("用法: python script.py <input_file.md> [output_file.md]")
        return

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "sliced_output.md"

    slice_markdown_by_delimiter(file_path=input_file, output_file=output_file)


if __name__ == "__main__":
    main()