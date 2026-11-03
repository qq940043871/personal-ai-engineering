import os
import shutil
import logging
from pathlib import Path
from typing import Optional


class BatchRenameUtil:
    """
    批量重命名工具类
    支持对指定文件夹下的所有文件进行重命名，保留文件名的前N个字符
    """
    
    def __init__(self, max_length: int = 20, enable_logging: bool = True):
        """
        初始化批量重命名工具
        
        Args:
            max_length (int): 文件名保留的最大字符数，默认为20
            enable_logging (bool): 是否启用日志功能，默认为True
        """
        self.max_length = max_length
        
        # 设置日志
        if enable_logging:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )
        self.logger = logging.getLogger(__name__)
        self.enable_logging = enable_logging
    
    def rename_files_in_directory(self, directory_path: str, include_subdirs: bool = False) -> dict:
        """
        重命名指定目录下的所有文件
        
        Args:
            directory_path (str): 目标目录路径
            include_subdirs (bool): 是否包含子目录，默认为False
            
        Returns:
            dict: 包含重命名结果的字典
        """
        directory = Path(directory_path)
        if not directory.exists():
            error_msg = f"目录不存在: {directory_path}"
            if self.enable_logging:
                self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        if not directory.is_dir():
            error_msg = f"路径不是目录: {directory_path}"
            if self.enable_logging:
                self.logger.error(error_msg)
            raise NotADirectoryError(error_msg)
        
        if self.enable_logging:
            self.logger.info(f"开始处理目录: {directory_path}, 包含子目录: {include_subdirs}")
        
        # 统计信息
        result = {
            'processed': 0,
            'renamed': 0,
            'skipped': 0,
            'errors': [],
            'renamed_files': []
        }
        
        # 获取所有文件
        if include_subdirs:
            files = [f for f in directory.rglob('*') if f.is_file()]
        else:
            files = [f for f in directory.iterdir() if f.is_file()]
        
        if self.enable_logging:
            self.logger.info(f"找到 {len(files)} 个文件")
        
        for file_path in files:
            try:
                if self.enable_logging:
                    self.logger.debug(f"处理文件: {file_path}")
                
                renamed = self._rename_single_file(file_path)
                result['processed'] += 1
                
                if renamed:
                    new_name = str(file_path.parent / self._get_new_filename(file_path.name))
                    if self.enable_logging:
                        self.logger.info(f"重命名: {file_path.name} -> {os.path.basename(new_name)}")
                    
                    result['renamed'] += 1
                    result['renamed_files'].append({
                        'original': str(file_path),
                        'new': new_name
                    })
                else:
                    if self.enable_logging:
                        self.logger.debug(f"跳过文件（无需重命名）: {file_path.name}")
                    result['skipped'] += 1
                    
            except Exception as e:
                error_msg = f"处理文件时出错 {file_path}: {str(e)}"
                if self.enable_logging:
                    self.logger.error(error_msg)
                result['errors'].append({
                    'file': str(file_path),
                    'error': str(e)
                })
        
        if self.enable_logging:
            self.logger.info(f"处理完成 - 总计: {result['processed']}, 重命名: {result['renamed']}, 跳过: {result['skipped']}")
            if result['errors']:
                self.logger.warning(f"发现 {len(result['errors'])} 个错误")
        
        return result
    
    def _rename_single_file(self, file_path: Path) -> bool:
        """
        重命名单个文件
        
        Args:
            file_path (Path): 文件路径
            
        Returns:
            bool: 是否进行了重命名操作
        """
        original_name = file_path.name
        new_name = self._get_new_filename(original_name)
        
        # 如果新文件名与原文件名相同，则跳过
        if original_name == new_name:
            return False
        
        new_path = file_path.parent / new_name
        
        # 如果新文件名已存在，添加数字后缀
        counter = 1
        original_new_path = new_path
        while new_path.exists():
            stem = original_new_path.stem
            suffix = original_new_path.suffix
            # 确保加上数字后缀后总长度不超过max_length
            available_length = self.max_length - len(str(counter)) - 1  # -1 for underscore
            if available_length <= 0:
                # 如果没有足够的空间添加数字，则尝试更复杂的命名策略
                available_length = self.max_length - 4  # 使用 _1, _2, 等
                if available_length <= 0:
                    raise ValueError(f"无法为文件生成唯一名称: {original_name}")
            
            if len(stem) > available_length:
                new_stem = stem[:available_length]
            else:
                new_stem = stem
            
            new_stem = f"{new_stem}_{counter}"
            new_name_with_counter = f"{new_stem}{suffix}"
            new_path = file_path.parent / new_name_with_counter
            counter += 1
        
        # 执行重命名
        file_path.rename(new_path)
        return True
    
    def _get_new_filename(self, original_name: str) -> str:
        """
        根据原始文件名生成新文件名（保留前N个字符）
        
        Args:
            original_name (str): 原始文件名
            
        Returns:
            str: 新文件名
        """
        # 分离文件名和扩展名
        stem, suffix = os.path.splitext(original_name)
        
        # 只保留文件名的前N个字符
        if len(stem) > self.max_length:
            new_stem = stem[:self.max_length]
        else:
            new_stem = stem
        
        # 重新组合文件名
        new_name = new_stem + suffix
        return new_name
    
    def preview_rename(self, directory_path: str, include_subdirs: bool = False) -> list:
        """
        预览重命名结果（不实际执行重命名）
        
        Args:
            directory_path (str): 目标目录路径
            include_subdirs (bool): 是否包含子目录，默认为False
            
        Returns:
            list: 预览结果列表
        """
        directory = Path(directory_path)
        if not directory.exists():
            error_msg = f"目录不存在: {directory_path}"
            if self.enable_logging:
                self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        if not directory.is_dir():
            error_msg = f"路径不是目录: {directory_path}"
            if self.enable_logging:
                self.logger.error(error_msg)
            raise NotADirectoryError(error_msg)
        
        if self.enable_logging:
            self.logger.info(f"预览模式 - 开始处理目录: {directory_path}, 包含子目录: {include_subdirs}")
        
        preview_result = []
        
        # 获取所有文件
        if include_subdirs:
            files = [f for f in directory.rglob('*') if f.is_file()]
        else:
            files = [f for f in directory.iterdir() if f.is_file()]
        
        if self.enable_logging:
            self.logger.info(f"预览模式 - 找到 {len(files)} 个文件")
        
        for file_path in files:
            original_name = file_path.name
            new_name = self._get_new_filename(original_name)
            
            if original_name != new_name:
                preview_result.append({
                    'original': str(file_path),
                    'new': str(file_path.parent / new_name),
                    'needs_rename': True
                })
            else:
                preview_result.append({
                    'original': str(file_path),
                    'new': str(file_path),
                    'needs_rename': False
                })
        
        return preview_result


def main():
    """
    主函数，提供命令行接口
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='批量重命名工具：保留文件名前N个字符')
    parser.add_argument('directory', help='目标目录路径')
    parser.add_argument('-l', '--length', type=int, default=20, 
                       help='保留的字符数，默认为20')
    parser.add_argument('--include-subdirs', action='store_true',
                       help='是否包含子目录中的文件')
    parser.add_argument('--preview', action='store_true',
                       help='仅预览重命名结果，不实际执行')
    
    args = parser.parse_args()
    
    # 根据命令行参数决定是否启用日志
    enable_logging = True  # 默认启用日志
    renamer = BatchRenameUtil(max_length=args.length, enable_logging=enable_logging)
    
    if args.preview:
        print("预览重命名结果：")
        preview_result = renamer.preview_rename(args.directory, args.include_subdirs)
        for item in preview_result:
            if item['needs_rename']:
                print(f"  {item['original']} -> {item['new']}")
            else:
                print(f"  {item['original']} (无需重命名)")
    else:
        print(f"开始重命名目录: {args.directory}")
        result = renamer.rename_files_in_directory(args.directory, args.include_subdirs)
        
        print(f"处理完成！")
        print(f"  总共处理文件: {result['processed']}")
        print(f"  重命名文件: {result['renamed']}")
        print(f"  跳过文件: {result['skipped']}")
        
        if result['errors']:
            print(f"  错误数量: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    错误: {error['file']} - {error['error']}")


if __name__ == "__main__":
    main()