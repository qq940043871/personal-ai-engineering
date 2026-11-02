"""
批量重命名工具使用示例
"""

from batch_rename import BatchRenameUtil
import os
from pathlib import Path


def example_usage():
    """使用示例"""
    print("=== 批量重命名工具使用示例 ===\n")
    
    # 示例1: 基本使用
    print("1. 基本使用方法:")
    print("   renamer = BatchRenameUtil(max_length=20)")
    print("   result = renamer.rename_files_in_directory('/path/to/directory')")
    print()
    
    # 示例2: 自定义字符数
    print("2. 自定义保留字符数:")
    print("   renamer = BatchRenameUtil(max_length=15)  # 保留前15个字符")
    print("   result = renamer.rename_files_in_directory('/path/to/directory')")
    print()
    
    # 示例3: 包含子目录
    print("3. 包含子目录中的文件:")
    print("   renamer = BatchRenameUtil(max_length=20)")
    print("   result = renamer.rename_files_in_directory('/path/to/directory', include_subdirs=True)")
    print()
    
    # 示例4: 预览模式
    print("4. 预览模式（不实际重命名）:")
    print("   renamer = BatchRenameUtil(max_length=20)")
    print("   preview_result = renamer.preview_rename('/path/to/directory')")
    print("   for item in preview_result:")
    print("       if item['needs_rename']:")
    print("           print(f'{item[\"original\"]} -> {item[\"new\"]}')")
    print()
    
    # 示例5: 命令行使用
    print("5. 命令行使用:")
    print("   python batch_rename.py /path/to/directory")
    print("   python batch_rename.py /path/to/directory -l 15  # 保留前15个字符")
    print("   python batch_rename.py /path/to/directory --include-subdirs  # 包含子目录")
    print("   python batch_rename.py /path/to/directory --preview  # 预览模式")
    print()
    
    # 实际操作示例
    print("6. 实际操作示例:")
    print("   # 创建一个测试目录和文件")
    test_dir = Path("test_rename_example")
    test_dir.mkdir(exist_ok=True)
    
    try:
        # 创建一些测试文件
        test_files = [
            "这是一个非常长的文件名需要被截断的测试文件1.txt",
            "another_very_long_filename_that_needs_to_be_truncated_test_file2.docx",
            "short.txt"
        ]
        
        for filename in test_files:
            (test_dir / filename).touch()
            print(f"      创建测试文件: {filename}")
        
        print(f"\n      测试目录: {test_dir}")
        print("      执行重命名操作...")
        
        # 使用重命名工具
        renamer = BatchRenameUtil(max_length=20)
        result = renamer.rename_files_in_directory(str(test_dir))
        
        print(f"      处理完成: {result['processed']} 个文件, {result['renamed']} 个重命名")
        
        print("      重命名后的文件:")
        for file_path in test_dir.iterdir():
            print(f"        {file_path.name}")
    finally:
        # 清理测试目录
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
    
    print("\n=== 使用说明 ===")
    print("1. 该工具会保留文件扩展名不变，只截断文件名部分")
    print("2. 如果截断后的文件名已存在，会自动添加数字后缀避免冲突")
    print("3. 默认保留前20个字符，可通过max_length参数自定义")
    print("4. 支持预览模式，可以先查看重命名效果再执行实际操作")
    print("5. 包含完整的错误处理和日志功能")


if __name__ == "__main__":
    example_usage()