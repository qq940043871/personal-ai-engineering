import os
import zipfile
import tarfile

# 定义要扫描的文件夹路径
folder_path = 'D:\\zf_temp\\testlog'

# 定义 100MB 的字节数
SIZE_THRESHOLD = 100 * 1024 * 1024  

def extract_archive(zip_path, extract_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
    except Exception as e:
        print(f"解压 {zip_path} 失败，错误信息: {e}")

def scan_folder(folder):
    """
    扫描文件夹的函数，包括解压 war、zip、tar 压缩包和检查日志文件大小
    :param folder: 要扫描的文件夹路径
    """
    for root, dirs, files in os.walk(folder):
        for file in files:
            file_path = os.path.join(root, file)
            # 检查文件是否存在，若不存在则跳过
            if not os.path.exists(file_path):
                continue
            # 检查是否为 war、zip 或 tar 压缩包
            if file_path.lower().endswith('.war') or file_path.lower().endswith('.tar') :
                extract_path = os.path.splitext(file_path)[0]
                if os.path.exists(extract_path) and os.path.isdir(extract_path):
                    print(f"使用 os 模块检查，文件夹 {extract_path} 存在。")
                else:
                    extract_archive(file_path, extract_path)
                    # 递归扫描解压后的文件夹
                    scan_folder(extract_path)
                
            # 其他文件按普通文件处理，这里仅检查日志文件大小
            elif file.lower() == 'log4j.properties':
                scan_file_log4j(file_path)
            elif file.lower() == 'logback.xml':
                scan_file_logback(file_path)

def scan_file_log4j(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                if 'MaxFileSize' in line:
                    parts = line.split('=')
                    if len(parts) > 1:
                        value = parts[1].lstrip()
                        value = value.replace('MB', '').replace('m', '').replace('M', '')
                        value = value.replace(' ', '')
                        try:
                            if(int(value) > 100):
                                print(f"scan_file_log4j: {file_path}")
                                break
                        except Exception as e:
                            print(f"判断 {file_path} 失败，错误信息: {e}")            
                
    except FileNotFoundError:
        print(f"文件 {file_path} 未找到。")

def scan_file_logback(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
             for line in file:
                if 'maxFileSize' in line:
                    value = line
                    value = value.replace('<maxFileSize>', '').replace('</maxFileSize>', '').replace('MB', '').replace('\n', '')
                    value = value.replace(' ', '')
                    try:
                        if(int(value) > 100):
                            print(f"scan_file_logback: {file_path}")
                            break
                    except Exception as e:
                        print(f"判断 {file_path} 失败，错误信息: {e}")     
    except FileNotFoundError:
        print(f"文件 {file_path} 未找到。")

if __name__ == "__main__":
    scan_folder(folder_path)