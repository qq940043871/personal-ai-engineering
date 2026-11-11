import os
import shutil
from datetime import datetime

class StorageManager:
    """存储管理类"""
    
    @staticmethod
    def ensure_directory(directory):
        """确保目录存在"""
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 创建目录: {directory}")
        return directory
    
    @staticmethod
    def get_timestamped_filename(prefix, extension):
        """生成带时间戳的文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.{extension}"
    
    @staticmethod
    def list_files(directory, extension=None):
        """列出目录中的文件"""
        if not os.path.exists(directory):
            return []
        
        files = []
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                if extension:
                    if filename.lower().endswith(f".{extension}"):
                        files.append(filepath)
                else:
                    files.append(filepath)
        
        # 按修改时间排序（最新的在前）
        files.sort(key=os.path.getmtime, reverse=True)
        return files
    
    @staticmethod
    def clean_directory(directory, keep_days=7):
        """清理目录中超过指定天数的文件"""
        if not os.path.exists(directory):
            return
        
        cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 3600)
        deleted_count = 0
        
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                if os.path.getmtime(filepath) < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
        
        if deleted_count > 0:
            print(f"🧹 清理了 {deleted_count} 个过期文件")
