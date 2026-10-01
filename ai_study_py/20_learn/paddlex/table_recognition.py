from paddlex import create_pipeline

pipeline = create_pipeline(pipeline="table_recognition")

output = pipeline.predict(
    input="table_recognition.jpg",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
)

for res in output:
    res.print()
    res.save_to_img("./output/")
    res.save_to_xlsx("./output/")
    res.save_to_html("./output/")
    res.save_to_json("./output/")