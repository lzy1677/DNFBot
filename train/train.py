"""
YOLOv8n/s 训练脚本
目标：推理速度 60+ FPS（1920x1080 游戏画面，实际推理使用 640 输入）

模型选择：
  yolov8n  — 最快，样本少时推荐
  yolov8s  — 精度更高，速度稍慢

运行前先执行：python prepare_dataset.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

DATASET_YAML = Path(__file__).parent.parent / "data" / "dataset.yaml"
PROJECT_DIR = Path(__file__).parent / "runs"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="yolov8n", choices=["yolov8n", "yolov8s"],
                   help="基础模型 (default: yolov8n)")
    p.add_argument("--epochs", type=int, default=200)
    p.add_argument("--imgsz", type=int, default=640,
                   help="训练输入尺寸，640 保证推理速度")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default="0", help="GPU id，cpu 则填 cpu")
    p.add_argument("--workers", type=int, default=4)
    return p.parse_args()


def main():
    args = parse_args()

    from ultralytics import YOLO

    model = YOLO(f"{args.model}.pt")

    results = model.train(
        data=str(DATASET_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(PROJECT_DIR),
        name=args.model,
        # 数据增强：模拟游戏内场景变化
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.3,
        degrees=0.0,        # 游戏画面不旋转
        translate=0.1,
        scale=0.3,
        fliplr=0.5,
        mosaic=0.8,
        mixup=0.1,
        # 训练优化
        optimizer="AdamW",
        lr0=0.001,
        weight_decay=0.0005,
        warmup_epochs=5,
        cos_lr=True,
        close_mosaic=20,    # 最后 20 epoch 关闭 mosaic 稳定收敛
        # 导出友好
        save_period=50,
        plots=True,
    )

    # 导出为 ONNX 和 TensorRT（可选，进一步提速）
    best_pt = Path(results.save_dir) / "weights" / "best.pt"
    print(f"\n训练完成，最优权重: {best_pt}")
    print("导出 ONNX（可用于更快推理）:")
    print(f"  python -m ultralytics export model={best_pt} format=onnx imgsz=640 half=True")
    print("导出 TensorRT（需要 TensorRT 环境，速度最快）:")
    print(f"  python -m ultralytics export model={best_pt} format=engine imgsz=640 half=True device=0")


if __name__ == "__main__":
    main()
