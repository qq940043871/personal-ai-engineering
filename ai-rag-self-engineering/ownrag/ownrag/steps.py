"""步骤注册总入口：import 即注册。main.py 与脚本统一从这里引，注册顺序不再踩坑。"""
from ownrag import review  # noqa: F401 (解析复核：prepare_review / review_gate)
from ownrag.index import chunker, store  # noqa: F401 (store 内含 index_upsert/embed)
from ownrag.ingest import av_asr, excel_staging, pdf_mineru  # noqa: F401

__all__ = ["pdf_mineru", "av_asr", "excel_staging", "chunker", "store", "review"]
