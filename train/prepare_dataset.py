"""
准备 YOLOv8 训练数据集：
- 合并原始数据 (data/image + data/label) 和新标注 (data/add_image + data/add_label)
- 仅保留有对应标注文件的图像
- 按 8:2 比例划分 train/val
- 输出到 data/dataset/ 目录
"""

import shutil
import random
from collections import Counter
from pathlib import Path
from typing import Set

SEED = 42
VAL_RATIO = 0.2

BASE_DIR = Path(__file__).parent.parent / "data"
DATASET_DIR = BASE_DIR / "dataset"

# 数据源（可扩展）
SOURCES = [
    {"image": BASE_DIR / "image",                  "label": BASE_DIR / "label"},
    {"image": BASE_DIR / "add_image",              "label": BASE_DIR / "add_label"},
    {"image": BASE_DIR / "nvguijian_image",        "label": BASE_DIR / "nvguijian_label"},
    {"image": BASE_DIR / "nvguijian_add_image",    "label": BASE_DIR / "nvguijian_add_label"},
]


def collect_pairs(src: dict) -> Set[str]:
    """收集一个有对应标注的图像 stem 集合。"""
    img_stems = {p.stem for p in src["image"].glob("*.jpg")}
    lbl_stems = {p.stem for p in src["label"].glob("*.txt")}
    paired = img_stems & lbl_stems
    orphan_imgs = len(img_stems - lbl_stems)
    orphan_lbls = len(lbl_stems - img_stems)
    if orphan_imgs or orphan_lbls:
        print("  {}: 无标注图像={}  无图像标注={}".format(
            src["image"].name, orphan_imgs, orphan_lbls))
    return paired


def copy_file(src_dir: Path, stem: str, ext: str, dst_dir: Path) -> None:
    src = src_dir / f"{stem}{ext}"
    for s in SOURCES:
        candidate = s["image" if ext == ".jpg" else "label"] / f"{stem}{ext}"
        if candidate.exists():
            shutil.copy2(candidate, dst_dir / f"{stem}{ext}")
            return
    # 兜底：从第一个源查找
    if src.exists():
        shutil.copy2(src, dst_dir / f"{stem}{ext}")


def main():
    random.seed(SEED)

    all_paired: Set[str] = set()
    for src in SOURCES:
        paired = collect_pairs(src)
        all_paired |= paired

    stems = sorted(all_paired)
    print(f"有效样本总数: {len(stems)}")

    # 统计各类别标注框数量
    cls_counter = Counter()
    for stem in stems:
        for src in SOURCES:
            lbl_file = src["label"] / f"{stem}.txt"
            if lbl_file.exists():
                for line in lbl_file.read_text().splitlines():
                    if line.strip():
                        cls_counter[int(line.split()[0])] += 1
                break
    if cls_counter:
        print(f"各类别框数: {dict(sorted(cls_counter.items()))}")

    random.shuffle(stems)
    n_val = max(1, int(len(stems) * VAL_RATIO))
    val_stems = set(stems[:n_val])
    train_stems = set(stems[n_val:])
    print(f"Train: {len(train_stems)}  Val: {len(val_stems)}")

    for split_name, split_stems in [("train", train_stems), ("val", val_stems)]:
        img_out = DATASET_DIR / "images" / split_name
        lbl_out = DATASET_DIR / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for stem in split_stems:
            copy_file(BASE_DIR / "image", stem, ".jpg", img_out)
            copy_file(BASE_DIR / "label", stem, ".txt", lbl_out)

    print(f"数据集已生成到: {DATASET_DIR}")


if __name__ == "__main__":
    main()
