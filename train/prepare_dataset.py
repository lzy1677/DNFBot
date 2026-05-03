"""
准备 YOLOv8 训练数据集：
- 仅保留有对应标注文件的图像
- 按 8:2 比例划分 train/val
- 输出到 data/dataset/ 目录
"""

import os
import shutil
import random
from pathlib import Path

SEED = 42
VAL_RATIO = 0.2

BASE_DIR = Path(__file__).parent.parent / "data"
IMAGE_DIR = BASE_DIR / "image"
LABEL_DIR = BASE_DIR / "label"
DATASET_DIR = BASE_DIR / "dataset"


def main():
    random.seed(SEED)

    img_stems = {p.stem for p in IMAGE_DIR.glob("*.jpg")}
    lbl_stems = {p.stem for p in LABEL_DIR.glob("*.txt")}
    paired = sorted(img_stems & lbl_stems)

    print(f"有效样本数: {len(paired)}  (剔除无标注: {len(img_stems - lbl_stems)})")

    random.shuffle(paired)
    n_val = max(1, int(len(paired) * VAL_RATIO))
    val_set = set(paired[:n_val])
    train_set = set(paired[n_val:])
    print(f"Train: {len(train_set)}  Val: {len(val_set)}")

    for split, stems in [("train", train_set), ("val", val_set)]:
        img_out = DATASET_DIR / "images" / split
        lbl_out = DATASET_DIR / "labels" / split
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for stem in stems:
            shutil.copy2(IMAGE_DIR / f"{stem}.jpg", img_out / f"{stem}.jpg")
            shutil.copy2(LABEL_DIR / f"{stem}.txt", lbl_out / f"{stem}.txt")

    print(f"数据集已生成到: {DATASET_DIR}")


if __name__ == "__main__":
    main()
