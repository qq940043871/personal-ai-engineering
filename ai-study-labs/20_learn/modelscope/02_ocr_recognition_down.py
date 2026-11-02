#模型下载
from modelscope import snapshot_download
model_dir = snapshot_download('iic/cv_convnextTiny_ocr-recognition-general_damo',local_dir='models/cv_convnextTiny_ocr-recognition-general_damo')