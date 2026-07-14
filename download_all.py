"""全データ一括ダウンロードスクリプト

株価・財務データ・センチメントをダウンロードし、データベースを最新状態に更新する。

使用例:
    python download_all.py              # 全データを一括ダウンロード
    python download_all.py --incremental # 株価のみ差分更新（軽量）
    python download_all.py --prices      # 株価のみ
    python download_all.py --financials  # 財務データのみ
    python download_all.py --sentiment   # センチメントのみ
"""

import argparse
import sys

from db.schema import init_db
from db.tickers import update_ticker_list


def main():
    parser = argparse.ArgumentParser(description="Download all data for stockChecker")
    parser.add_argument("--incremental", action="store_true", help="株価のみ差分更新（軽量）")
    parser.add_argument("--prices", action="store_true", help="株価のみダウンロード")
    parser.add_argument("--financials", action="store_true", help="財務データのみダウンロード")
    parser.add_argument("--sentiment", action="store_true", help="センチメントのみダウンロード")
    args = parser.parse_args()

    # 特定のフラグがない場合は全部を実行
    all_flag = not (args.prices or args.financials or args.sentiment)

    print("=== Initializing database ===")
    init_db()

    print("\n=== Updating ticker list ===")
    update_ticker_list()

    if args.incremental:
        print("\n=== Updating prices (incremental) ===")
        from db.downloader_prices import update_incremental
        update_incremental()
    elif args.prices or all_flag:
        print("\n=== Downloading prices ===")
        from db.downloader_prices import download_all
        download_all()

    if args.financials or all_flag:
        print("\n=== Downloading financials ===")
        from db.downloader_financials import download_all
        download_all()

    if args.sentiment or all_flag:
        print("\n=== Downloading sentiment ===")
        from db.downloader_sentiment import download_next_batch
        download_next_batch(n=50)

    print("\n=== All downloads complete! ===")


if __name__ == "__main__":
    main()
