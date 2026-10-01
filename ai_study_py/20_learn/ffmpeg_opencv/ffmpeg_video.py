import subprocess

def run_ffmpeg_command():
    # 定义FFmpeg命令及其参数
    command = [
        'ffmpeg',
        '-i', 'https://cmgw-vpc.lechange.com:8890/iot/LCO/CTNH3F2S/509D9ABPCPF46A9/0/1/20250303T070845/openhzf471207b98e241099b69f63b4f2a403b.m3u8?proto=https&source=open',
        '-an',
        '-vf', 'scale=640:480',
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        'OUT.mp4'
    ]

    try:
        # 使用subprocess调用FFmpeg命令
        subprocess.run(command, check=True)
        print("FFmpeg命令执行成功！")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg命令执行失败，错误信息：{e}")
    except FileNotFoundError:
        print("错误：未找到FFmpeg可执行文件。请确保FFmpeg已安装并添加到系统路径中。")

if __name__ == "__main__":
    run_ffmpeg_command()