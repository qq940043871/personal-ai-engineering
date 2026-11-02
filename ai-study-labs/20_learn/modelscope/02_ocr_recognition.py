from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
import cv2

ocr_recognition = pipeline(Tasks.ocr_recognition, model='models/cv_convnextTiny_ocr-recognition-general_damo')

### 使用url
img_url = 'http://duguang-labelling.oss-cn-shanghai.aliyuncs.com/mass_img_tmp_20220922/ocr_recognition.jpg'
result = ocr_recognition(img_url)
print(result)

### 使用图像文件
### 请准备好名为'ocr_recognition.jpg'的图像文件
# img_path = 'ocr_recognition.jpg'
# img = cv2.imread(img_path)
# result = ocr_recognition(img)
# print(result)