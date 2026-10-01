import os
import random
import paddle
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import cv2

# 输出Paddle版本
print(paddle.__version__)

plt.subplot(1, 2, 1)
img = cv2.imread(
    "cityscapes/leftImg8bit/train/aachen/aachen_000001_000019_leftImg8bit.png"
)
plt.imshow(img)
plt.axis("off")
plt.subplot(1, 2, 2)
img = cv2.imread(
    "cityscapes/gtFine/train/aachen/aachen_000001_000019_gtFine_color.png"
)
plt.imshow(img)
plt.axis("off")
plt.xticks([])
plt.yticks([])
plt.subplots_adjust(wspace=0.1, hspace=0.1)
