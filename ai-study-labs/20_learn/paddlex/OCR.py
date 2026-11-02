from paddlex import create_pipeline

pipeline = create_pipeline(pipeline="OCR")

output = pipeline.predict(
    input="D:\\workspace\\p001_ai_study_py\\12_ocr\\1.jpg",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
for res in output:
    res.print()
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/")