from paddlex import create_pipeline
import cv2

pipeline = create_pipeline(pipeline="object_detection")

# 打开视频文件
video_path = 'D:\\2.mp4'  # 替换为你的视频文件路径
cap = cv2.VideoCapture(video_path)

# 检查视频是否成功打开
if not cap.isOpened():
    print("Error opening video file")
    exit()

# 循环读取视频帧
while cap.isOpened():
    # 读取一帧视频
    success, frame = cap.read()

    if success:
        # 使用模型进行目标检测
        output = pipeline.predict(frame, threshold=0.5)

        # 遍历检测结果
        for det in output:
            for boxes in det['boxes']:
                if boxes['label'] == 'bus':  # 假设类别名称为 'forklift'
                    # 获取检测框的坐标
                    xmin, ymin, w, h = boxes['bbox']
                    xmax = xmin + w
                    ymax = ymin + h
                    # 在图像上绘制检测框
                    cv2.rectangle(frame, (int(xmin), int(ymin)), (int(xmax), int(ymax)), (0, 255, 0), 2)
                    # 显示类别名称和置信度
                    label = f"{boxes['label']}: {boxes['score']:.2f}"
                    cv2.putText(frame, label, (int(xmin), int(ymin) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        # 显示带检测结果的帧
        cv2.imshow("PaddleX Forklift Detection", frame)

        # 按 'q' 键退出循环
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    else:
        # 若无法读取帧，退出循环
        break

# 释放视频捕获对象并关闭所有窗口
cap.release()
cv2.destroyAllWindows()