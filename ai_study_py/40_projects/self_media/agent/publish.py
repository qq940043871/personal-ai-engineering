
#!/usr/bin/env python3
import os
import sys
import logging
import argparse
import re
import time

sys.path.insert(0, os.path.dirname(__file__))

from config import VOLC_API_KEY, WECHAT_APPID, WECHAT_APPSECRET, ARTICLE_AUTHOR, OUTPUT_DIR
from article_generator import generate_article, generate_image_prompt
from image_generator import generate_cover_image
from markdown_to_html import markdown_to_wechat_html, extract_digest
from wechat_api import (
    get_access_token,
    upload_permanent_image,
    create_draft
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("publisher")


def publish_article(title: str, skip_image: bool = False, skip_wechat: bool = False) -> dict:
    if not VOLC_API_KEY:
        return {"success": False, "error": "VOLC_API_KEY未配置，请在.env中设置"}

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', title)[:50]

    print(f"\n{'='*60}")
    print(f"  标题: {title}")
    print(f"{'='*60}")

    # Step 1: 生成文章
    print("\n[1/5] 生成文章内容...")
    article_result = generate_article(title)
    if not article_result["success"]:
        return article_result

    md_content = article_result["content"]

    md_path = os.path.join(OUTPUT_DIR, f"{safe_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"  Markdown已保存: {md_path}")

    # Step 2: 生成配图
    cover_path = None
    if not skip_image:
        print("\n[2/5] 生成配图提示词...")
        img_prompt = generate_image_prompt(title)
        if img_prompt:
            print(f"  提示词: {img_prompt[:80]}...")

            print("  生成封面图中...")
            cover_path = os.path.join(OUTPUT_DIR, f"{safe_name}_cover.jpg")
            img_result = generate_cover_image(img_prompt, cover_path, size="1024x576")
            if img_result["success"]:
                print(f"  封面图已保存: {cover_path}")
            else:
                print(f"  封面图生成失败: {img_result.get('error')}")
                cover_path = None
        else:
            print("  提示词生成失败，跳过配图")
    else:
        print("\n[2/5] 跳过配图生成")

    # Step 3: 转换HTML
    print("\n[3/5] 转换为微信公众号HTML...")
    html_content = markdown_to_wechat_html(md_content)

    html_path = os.path.join(OUTPUT_DIR, f"{safe_name}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  HTML已保存: {html_path}")

    digest = extract_digest(html_content)

    # Step 4: 发布到微信
    if not skip_wechat:
        if not WECHAT_APPID or not WECHAT_APPSECRET:
            print("\n[4/5] 微信公众号未配置，跳过发布")
            print(f"  请在.env中设置 WECHAT_APPID 和 WECHAT_APPSECRET")
        else:
            print("\n[4/5] 发布到微信公众号草稿箱...")

            try:
                access_token = get_access_token()
                print(f"  access_token获取成功")

                thumb_media_id = None
                if cover_path and os.path.isfile(cover_path):
                    print("  上传封面图到永久素材...")
                    thumb_media_id = upload_permanent_image(access_token, cover_path)
                    print(f"  封面图上传成功: {thumb_media_id}")

                if not thumb_media_id:
                    print("  无封面图，将不设置封面")
                    return {"success": False, "error": "需要封面图才能创建草稿"}

                print("  创建草稿...")
                result = create_draft(
                    access_token=access_token,
                    title=title,
                    content=html_content,
                    thumb_media_id=thumb_media_id,
                    author=ARTICLE_AUTHOR,
                    digest=digest,
                    show_cover_pic=0
                )

                if result["success"]:
                    print(f"\n  ✅ 草稿创建成功! media_id={result['media_id']}")
                    print(f"  请到公众号后台【草稿箱】查看")
                else:
                    print(f"\n  ❌ 草稿创建失败: {result.get('error')}")

            except Exception as e:
                print(f"\n  ❌ 发布失败: {str(e)}")
                logger.error(f"微信发布异常: {str(e)}")
    else:
        print("\n[4/5] 跳过微信发布")

    # Step 5: 总结
    print(f"\n[5/5] 完成!")
    print(f"  标题: {title}")
    print(f"  Markdown: {md_path}")
    print(f"  HTML: {html_path}")
    if cover_path:
        print(f"  封面图: {cover_path}")
    print(f"{'='*60}\n")

    return {
        "success": True,
        "title": title,
        "md_path": md_path,
        "html_path": html_path,
        "cover_path": cover_path
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="微信公众号文章自动生成与发布")
    parser.add_argument("--title", "-t", type=str, help="文章标题")
    parser.add_argument("--no-image", action="store_true", help="跳过配图生成")
    parser.add_argument("--no-wechat", action="store_true", help="跳过微信发布(仅生成本地文件)")
    parser.add_argument("--batch", "-b", type=str, help="批量模式: 指定标题文件路径，每行一个标题")

    args = parser.parse_args()

    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            titles = [line.strip() for line in f if line.strip()]

        print(f"批量模式: 共 {len(titles)} 个标题")
        for i, title in enumerate(titles, 1):
            print(f"\n>>> [{i}/{len(titles)}] 处理: {title}")
            result = publish_article(
                title,
                skip_image=args.no_image,
                skip_wechat=args.no_wechat
            )
            if i < len(titles):
                print("\n等待3秒后继续...")
                time.sleep(3)
    elif args.title:
        publish_article(
            args.title,
            skip_image=args.no_image,
            skip_wechat=args.no_wechat
        )
    else:
        parser.print_help()
