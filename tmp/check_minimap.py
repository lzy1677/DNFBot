# 临时校准脚本，在游戏运行时跑              
import sys
sys.path.insert(0, '.')                                                                                                                                                             
import cv2, numpy as np                                                                                                                                                                                  
from vision.capture import ScreenCapture

cap = ScreenCapture(window_title="地下城与勇士")
frame = cap.grab()
h, w = frame.shape[:2]

# 裁出小地图区域
x1, y1, x2, y2 = int(w*0.926), int(h*0.078), int(w*0.994), int(h*0.170)
minimap = frame[y1:y2, x1:x2]
cv2.imshow("minimap", cv2.resize(minimap, (minimap.shape[1]*4, minimap.shape[0]*4)))

# 鼠标点击坐标 → 归一化输出
def on_click(event, x, y, *_):
    if event == cv2.EVENT_LBUTTONDOWN:
        mw, mh = minimap.shape[1], minimap.shape[0]
        print(f"minimap_xy: [{x/mw/4:.2f}, {y/mh/4:.2f}]")  # 已考虑放大4倍
cv2.setMouseCallback("minimap", on_click)
cv2.waitKey(0)