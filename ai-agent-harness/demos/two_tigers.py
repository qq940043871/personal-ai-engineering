#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《两只老虎》中文儿歌歌词打印程序
"""

def print_two_tigers():
    """
    美观打印《两只老虎》完整歌词
    """
    # 歌词标题
    title = "🐯 两只老虎 🐯"
    separator = "=" * 30
    
    # 完整歌词内容
    lyrics = [
        ["两只老虎，两只老虎，",
         "跑得快，跑得快，",
         "一只没有耳朵，",
         "一只没有尾巴，",
         "真奇怪！真奇怪！"],
        ["两只老虎，两只老虎，",
         "跑得快，跑得快，",
         "一只没有眼睛，",
         "一只没有嘴巴，",
         "真奇怪！真奇怪！"],
        ["两只老虎，两只老虎，",
         "跑得快，跑得快，",
         "一只没有耳朵，",
         "一只没有尾巴，",
         "真奇怪！真奇怪！"]
    ]
    
    # 开始打印
    print("\n" + separator)
    print(title.center(30))
    print(separator + "\n")
    
    # 逐段打印歌词
    for i, verse in enumerate(lyrics, 1):
        print(f"【第{i}段】")
        for line in verse:
            print("  " + line)
        print()  # 段落间空行
    
    # 结尾装饰
    print(separator)
    print("🎶 经典儿歌，代代相传 🎶".center(30))
    print(separator + "\n")


if __name__ == "__main__":
    print_two_tigers()
