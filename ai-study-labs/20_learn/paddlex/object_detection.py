from paddlex import create_pipeline

pipeline = create_pipeline(pipeline="object_detection")

output = pipeline.predict("D:\\workspace\\p005_paddlepaddle\\PaddleX\\1.jpg", threshold=0.5)

for res in output:
    res.print()
    res.save_to_img("./output/")
    res.save_to_json("./output/")