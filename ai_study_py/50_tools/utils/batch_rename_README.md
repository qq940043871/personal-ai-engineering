# 批量重命名工具

一个用于批量重命名文件夹下所有文件的Python工具，支持保留文件名的前N个字符（默认为20个字符）。

## 功能特点

- 保留文件扩展名不变，只截断文件名部分
- 支持自定义保留字符数（默认20个字符）
- 支持包含子目录中的文件
- 提供预览模式，可预览重命名效果而不实际执行
- 自动处理文件名冲突，添加数字后缀避免覆盖
- 完整的错误处理和日志功能

## 使用方法

### 1. 作为模块导入使用

```python
from batch_rename import BatchRenameUtil

# 创建重命名工具实例（默认保留20个字符）
renamer = BatchRenameUtil(max_length=20)

# 重命名指定目录下的所有文件
result = renamer.rename_files_in_directory('/path/to/directory')

# 包含子目录
result = renamer.rename_files_in_directory('/path/to/directory', include_subdirs=True)

# 预览模式（不实际重命名）
preview_result = renamer.preview_rename('/path/to/directory')
for item in preview_result:
    if item['needs_rename']:
        print(f"{item['original']} -> {item['new']}")
```

### 2. 命令行使用

```bash
# 基本使用
python batch_rename.py /path/to/directory

# 保留前15个字符
python batch_rename.py /path/to/directory -l 15

# 包含子目录中的文件
python batch_rename.py /path/to/directory --include-subdirs

# 预览模式（不实际重命名）
python batch_rename.py /path/to/directory --preview

# 查看帮助信息
python batch_rename.py --help
```

## 返回结果说明

`rename_files_in_directory` 方法返回一个字典，包含以下信息：

- `processed`: 总共处理的文件数
- `renamed`: 实际重命名的文件数
- `skipped`: 跳过的文件数（不需要重命名）
- `errors`: 错误列表
- `renamed_files`: 重命名文件的详细信息列表

## 注意事项

1. 工具会保留文件扩展名不变，只截断文件名部分
2. 如果截断后的文件名已存在，会自动添加数字后缀避免冲突
3. 当文件名冲突且添加数字后缀可能导致文件名超过指定长度时，会截断文件名以确保总长度不超过限制
4. 建议在使用前先用预览模式查看重命名效果
5. 请确保对目标目录有读写权限

## 示例

假设有以下文件：
- `这是一个非常长的文件名需要被截断的测试文件1.txt`
- `another_very_long_filename_that_needs_to_be_truncated_test_file2.docx`
- `short.txt`

重命名后变为：
- `这是一个非常长的文件名需要被截断的测试文.txt`
- `another_very_long_fi.docx`
- `short.txt`（保持不变，因为长度小于20）