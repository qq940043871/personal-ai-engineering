from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks

animal_recognition= pipeline(
            Tasks.animal_recognition,
            model='models/cv_resnest101_animal_recognition')
result = animal_recognition('https://pailitao-image-recog.oss-cn-zhangjiakou.aliyuncs.com/mufan/img_data/maas_test_data/dog.png')
print(result)