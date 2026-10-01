import os
import requests
from tqdm import tqdm
import re
from bs4 import BeautifulSoup
import concurrent.futures
import argparse

# 默认文件路径
DEFAULT_HTML_FILE = "d:\\workspace\\p001_ai_study_py\\00_utils\\退市新规.html"
DEFAULT_BASE_DIR = "d:\\workspace\\p001_ai_study_py\\00_utils"

# 从HTML文件路径提取文件夹名并创建下载目录
def create_download_dir_from_html(html_file, base_dir):
    # 提取HTML文件名（不包含扩展名）
    html_filename = os.path.splitext(os.path.basename(html_file))[0]
    # 创建以HTML文件名命名的下载目录
    download_dir = os.path.join(base_dir, html_filename)
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"创建下载目录: {download_dir}")
    else:
        print(f"使用已有目录: {download_dir}")
    
    return download_dir

# 解析HTML文件
def parse_html(file_path):
    print(f"正在解析HTML文件: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    videos = []
    
    # 查找所有包含videourl属性的p标签
    for p_tag in soup.find_all('p', {'videourl': True}):
        video_url = p_tag['videourl']
        # 获取标题文本（去除图标标签和空白字符）
        title = p_tag.text.strip()
        # 清理标题中的非法字符，用于文件名
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
        
        videos.append({
            'url': video_url,
            'title': title,
            'safe_title': safe_title
        })
    
    return videos

# 下载单个视频
def download_video(video_info, download_dir):
    url = video_info['url']
    title = video_info['title']
    safe_title = video_info['safe_title']
    
    # 从URL中提取文件名或使用标题作为文件名
    file_name = f"{safe_title}.mp4"
    file_path = os.path.join(download_dir, file_name)
    
    # 检查文件是否已存在
    if os.path.exists(file_path):
        print(f"文件已存在，跳过下载: {file_name}")
        return True
    
    print(f"开始下载: {title}")
    
    try:
        # 使用stream参数流式下载
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()  # 检查请求是否成功
            
            # 获取文件大小
            total_size = int(r.headers.get('content-length', 0))
            
            # 使用tqdm显示下载进度
            with open(file_path, 'wb') as f, tqdm(
                desc=file_name,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                leave=False  # 下载完成后不保留进度条
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
        
        print(f"下载完成: {title} -> {file_path}")
        return True
    except Exception as e:
        print(f"下载失败: {title} - {str(e)}")
        # 清理失败的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        return False

# 主函数
def main(html_file, base_dir, max_workers=5):
    # 根据HTML文件名创建下载目录
    download_dir = create_download_dir_from_html(html_file, base_dir)
    
    # 解析HTML获取视频信息
    videos = parse_html(html_file)
    print(f"成功解析到 {len(videos)} 个视频")
    print(f"使用 {max_workers} 个线程进行并行下载")
    
    # 使用线程池并行下载所有视频
    success_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有下载任务
        future_to_video = {
            executor.submit(download_video, video, download_dir): i+1 for i, video in enumerate(videos)
        }
        
        # 处理完成的任务
        for future in concurrent.futures.as_completed(future_to_video):
            video_num = future_to_video[future]
            try:
                result = future.result()
                if result:
                    success_count += 1
                print(f"处理进度: {success_count}/{len(videos)}")
            except Exception as e:
                print(f"任务 {video_num} 发生异常: {str(e)}")
    
    print(f"\n{'-'*50}")
    print(f"下载完成! 成功: {success_count}/{len(videos)}")
    print(f"所有视频保存在: {download_dir}")

if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='下载HTML文件中的视频')
    parser.add_argument('--html', type=str, default=DEFAULT_HTML_FILE,
                       help=f'HTML文件路径 (默认: {DEFAULT_HTML_FILE})')
    parser.add_argument('--base-dir', type=str, default=DEFAULT_BASE_DIR,
                       help=f'基础下载目录 (默认: {DEFAULT_BASE_DIR})')
    parser.add_argument('--threads', type=int, default=2,
                       help='下载线程数 (默认: 2)')
    
    args = parser.parse_args()
    
    # 运行主函数
    main(args.html, args.base_dir, args.threads)