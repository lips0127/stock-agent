"""VIX 2.0 离线训练入口（CLI）。

用法：
  python -m scripts.train_vix2                      # 默认参数训练并落盘
  python -m scripts.train_vix2 --pt 0.06 --sl 0.04 --horizon 20
  python -m scripts.train_vix2 --no-save            # 只评估不落盘
  python -m scripts.train_vix2 --backfill           # 训练后立即回填 vix2_history

训练完成后打印元数据（含可解释权重 / CV-AUC / OOS-AUC）。
固定随机种子，重跑得到一致权重（设计书 §6 验收标准）。
"""

import argparse
import json
import warnings

warnings.filterwarnings("ignore")


def main():
    ap = argparse.ArgumentParser(description="Train VIX 2.0 ML model")
    ap.add_argument("--pt", type=float, default=0.05, help="止盈 barrier 基准宽度")
    ap.add_argument("--sl", type=float, default=0.05, help="止损 barrier 基准宽度")
    ap.add_argument("--horizon", type=int, default=20, help="时间 barrier（交易日）")
    ap.add_argument("--no-rv-scale", action="store_true", help="关闭 RV 动态缩放 barrier")
    ap.add_argument("--no-save", action="store_true", help="只评估不落盘")
    ap.add_argument("--backfill", action="store_true", help="训练后回填 vix2_history")
    ap.add_argument("--backfill-days", type=int, default=0, help="回填天数（0=全历史）")
    args = ap.parse_args()

    from backend.core.database import init_db
    from backend.services.vix2_model import train_model

    init_db()
    label_params = {
        "pt": args.pt, "sl": args.sl, "horizon": args.horizon,
        "rv_scale": not args.no_rv_scale,
    }
    print(f"训练参数: {label_params}")
    meta = train_model(
        label_params=label_params,
        save=not args.no_save,
        progress=lambda m: print(f"  · {m}", flush=True),
    )

    print("\n=== 训练结果 ===")
    print(json.dumps({k: v for k, v in meta.items() if k != "scaler"},
                     ensure_ascii=False, indent=2))

    if args.backfill and not args.no_save:
        from backend.services.vix2_service import backfill_vix2
        print("\n=== 回填 vix2_history ===")
        res = backfill_vix2(days=args.backfill_days or 0)
        print(json.dumps(res, ensure_ascii=False))

    print("\nDONE")


if __name__ == "__main__":
    main()
