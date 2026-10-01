#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from image_generator import generate_cover_image

def test_image_generation():
    """测试图片生成功能"""
    prompt = "A futuristic AI robot assistant, cyberpunk style, glowing blue eyes, digital background, cinematic lighting, professional 8K wallpaper"
    output_path = os.path.join(os.path.dirname(__file__), "output", "test_cover.jpg")
    
    print(f"测试配图生成...")
    print(f"提示词: {prompt}")
    print(f"输出路径: {output_path}")
    
    result = generate_cover_image(prompt, output_path)
    
    if result["success"]:
        print(f"\n✅ 配图生成成功!")
        print(f"  保存路径: {result['path']}")
        print(f"  图片URL: {result['url']}")
    else:
        print(f"\n❌ 配图生成失败: {result.get('error')}")
        return False
    
    return True

if __name__ == "__main__":
    test_image_generation()