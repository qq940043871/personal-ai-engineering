from pathlib import Path

from paddlex import create_pipeline

HERE = Path(__file__).resolve().parent

pipeline = create_pipeline(pipeline="OCR")

output = pipeline.predict(
    input=str(HERE / "1.jpg"),
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

for res in output:
    res.print()
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/")
