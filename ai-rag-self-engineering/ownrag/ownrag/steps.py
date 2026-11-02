"""步骤注册总入口：import 即注册。main.py 与脚本统一从这里引，注册顺序不再踩坑。"""
from ownrag.ingest import pdf_mineru, av_asr, excel_staging   # noqa: F401
from ownrag.index import chunker, store                        # noqa: F401 (store 内含 index_upsert/embed)

__all__ = ["pdf_mineru", "av_asr", "excel_staging", "chunker", "store"]
