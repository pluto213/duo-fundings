"""
初始化基金持仓信息
从东方财富获取每只基金的重仓股票，输出到文件供用户审核

用法: python scripts/init_fund_holdings.py
"""

import csv
import os
import re
import sys
import time
from io import StringIO

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TRANSACTIONS_CSV = os.path.join(DATA_DIR, "import_transactions.csv")
SUMMARY_CSV = os.path.join(DATA_DIR, "import_holdings_summary.csv")
MAPPING_CSV = os.path.join(DATA_DIR, "fund_mapping.csv")
OUTPUT_CSV = os.path.join(DATA_DIR, "fund_holdings_init.csv")
FAILED_CSV = os.path.join(DATA_DIR, "fund_holdings_failed.csv")
HOLDINGS_CSV = os.path.join(DATA_DIR, "import_holdings.csv")


def get_all_fund_codes() -> list[str]:
    """从两个 CSV 文件提取所有基金代码"""
    codes = set()

    for csv_path in [TRANSACTIONS_CSV, SUMMARY_CSV]:
        if not os.path.exists(csv_path):
            continue
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = (row.get("fund_code") or "").strip()
                if code and len(code) == 6:
                    codes.add(code)

    return sorted(codes)


def load_fund_mapping() -> dict[str, str]:
    """加载基金映射关系

    Returns:
        dict: {fund_code: mapped_fund_code}
    """
    mapping = {}
    if not os.path.exists(MAPPING_CSV):
        return mapping

    with open(MAPPING_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = (row.get("fund_code") or "").strip()
            mapped = (row.get("mapped_fund_code") or "").strip()
            if code and mapped:
                mapping[code] = mapped

    return mapping


def get_fund_name(fund_code: str) -> str:
    """获取基金名称"""
    import akshare as ak
    try:
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is not None and not df.empty:
            mapping = dict(zip(df["item"], df["value"]))
            return str(mapping.get("基金名称", fund_code))
    except Exception:
        pass
    return fund_code


def get_fund_holdings(fund_code: str, date: str = "2026") -> tuple[list[dict], str]:
    """获取基金重仓股票（手动解析东方财富 API）

    Returns:
        (持仓列表, 报告期日期)
        list of dict: [{"stock_code": "600519", "stock_name": "贵州茅台", "weight": 0.095}, ...]
    """
    try:
        url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
        params = {
            "type": "jjcc",
            "code": fund_code,
            "topline": "10",
            "year": date,
            "month": "",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fundf10.eastmoney.com/",
        }

        r = requests.get(url, params=params, headers=headers, timeout=15)
        content = r.text

        # 提取 HTML 内容
        html_match = re.search(r'content:"(.*?)"', content, re.DOTALL)
        if not html_match:
            return [], None

        html = html_match.group(1)
        if "暂无" in html or not html.strip():
            return [], None

        # 提取报告日期
        report_date_match = re.search(r'截止至：.*?(\d{4}-\d{2}-\d{2})', html)
        report_date = report_date_match.group(1) if report_date_match else None

        # 解析表格
        tables = pd.read_html(StringIO(html))
        if not tables:
            return [], None

        df = tables[0]

        # 标准化列名
        col_map = {
            "股票代码": "stock_code",
            "股票名称": "stock_name",
            "占净值 比例": "weight",
            "占净值比例": "weight",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if "stock_code" not in df.columns or "weight" not in df.columns:
            return [], None

        # 处理 weight
        df["weight"] = (
            df["weight"]
            .astype(str)
            .str.replace("%", "", regex=False)
        )
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        if df["weight"].max() > 1:
            df["weight"] = df["weight"] / 100

        results = []
        for _, row in df.iterrows():
            w = row.get("weight", 0)
            if pd.isna(w) or w <= 0:
                continue
            results.append({
                "stock_code": str(row.get("stock_code", "")),
                "stock_name": str(row.get("stock_name", "")),
                "weight": round(float(w), 4),
            })

        return results, report_date

    except Exception as e:
        return [{"error": str(e)}], None


def main():
    print("=" * 50)
    print("初始化基金持仓信息")
    print("=" * 50)

    # 获取所有基金代码
    fund_codes = get_all_fund_codes()
    print(f"共 {len(fund_codes)} 只基金")

    # 加载映射关系
    mapping = load_fund_mapping()
    if mapping:
        print(f"基金映射: {len(mapping)} 条")
        for k, v in mapping.items():
            print(f"  {k} → {v}")
    print()

    results = []

    for i, code in enumerate(fund_codes, 1):
        print(f"[{i}/{len(fund_codes)}] {code} ...", end=" ")

        # 获取基金名称
        fund_name = get_fund_name(code)
        print(f"{fund_name}", end=" ")

        # 检查是否有映射
        query_code = mapping.get(code, code)
        if query_code != code:
            print(f" → {query_code}", end=" ")

        # 获取持仓
        holdings, report_date = get_fund_holdings(query_code)

        if not holdings:
            print("❌ 无数据")
            results.append({
                "fund_code": code,
                "fund_name": fund_name,
                "report_date": "",
                "stock_code": "",
                "stock_name": "数据获取失败，请手动补充",
                "weight": "",
                "status": "failed",
            })
        elif "error" in holdings[0]:
            print(f"❌ {holdings[0]['error'][:30]}")
            results.append({
                "fund_code": code,
                "fund_name": fund_name,
                "report_date": "",
                "stock_code": "",
                "stock_name": f"错误: {holdings[0]['error'][:50]}",
                "weight": "",
                "status": "error",
            })
        else:
            print(f"✓ {len(holdings)} 只重仓股 (报告期: {report_date})")
            for h in holdings:
                results.append({
                    "fund_code": code,
                    "fund_name": fund_name,
                    "report_date": report_date or "",
                    "stock_code": h["stock_code"],
                    "stock_name": h["stock_name"],
                    "weight": h["weight"],
                    "status": "ok",
                })

        # 避免请求过快
        time.sleep(0.5)

    # 分离成功和失败的结果
    ok_results = [r for r in results if r["status"] == "ok"]
    failed_results = [r for r in results if r["status"] != "ok"]

    # 写入成功结果
    print()
    print(f"写入文件: {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fund_code", "fund_name", "report_date", "stock_code", "stock_name", "weight", "status"])
        writer.writeheader()
        writer.writerows(ok_results)

    # 写入失败结果
    if failed_results:
        print(f"写入文件: {FAILED_CSV}")
        with open(FAILED_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["fund_code", "fund_name", "report_date", "stock_code", "stock_name", "weight", "status"])
            writer.writeheader()
            writer.writerows(failed_results)
    else:
        # 没有失败的基金，删除旧的失败文件
        if os.path.exists(FAILED_CSV):
            os.remove(FAILED_CSV)
            print(f"删除旧文件: {FAILED_CSV}")

    # 生成 import_holdings.csv（所有基金代码）
    print(f"写入文件: {HOLDINGS_CSV}")
    all_codes = sorted(set(r["fund_code"] for r in results))
    with open(HOLDINGS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["fund_code", "fund_name", "buy_nav", "shares", "buy_date", "note"])
        for code in all_codes:
            fund_name = next((r["fund_name"] for r in results if r["fund_code"] == code), code)
            writer.writerow([code, fund_name, "", "", "", ""])

    # 统计
    ok_count = len(set(r["fund_code"] for r in ok_results))
    fail_count = len(set(r["fund_code"] for r in failed_results))
    print()
    print(f"成功: {ok_count} 只, 失败: {fail_count} 只")
    print()
    print("下一步:")
    print(f"1. 检查 {OUTPUT_CSV} 确认重仓股数据")
    print(f"2. 对于失败的基金，打开 {FAILED_CSV} 手动补充")
    print(f"3. 打开 {HOLDINGS_CSV} 填写你的持仓信息")


if __name__ == "__main__":
    main()
