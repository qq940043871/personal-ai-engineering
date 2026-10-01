
import os
from dotenv import load_dotenv

load_dotenv()

VOLC_API_KEY = os.getenv("VOLC_API_KEY", "")
VOLC_BASE_URL = os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM_MODEL = os.getenv("LLM_MODEL", "doubao-seed-2-0-pro-260215")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "doubao-seedream-4-5-251128")

WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")

ARTICLE_AUTHOR = os.getenv("ARTICLE_AUTHOR", "慢学AI")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "output"))
