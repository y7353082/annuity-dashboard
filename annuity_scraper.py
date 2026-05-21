#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年金投资管理数据自动抓取脚本
从22家机构官网抓取季度报告数据

使用方法:
    python annuity_scraper.py [--quarter 2025Q4] [--output output.json] [--workers 5]

依赖安装:
    pip install aiohttp beautifulsoup4 lxml
"""

import asyncio
import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

# ==================== 配置 ====================

@dataclass
class Institution:
    id: int
    name: str
    url: str
    # 可选: 自定义解析配置
    table_keywords: List[str] = field(default_factory=list)
    encoding: str = "utf-8"
    # 某些网站可能需要特殊请求头
    extra_headers: Dict[str, str] = field(default_factory=dict)


INSTITUTIONS = [
    Institution(1, "太平养老", "https://tppension.cntaiping.com/njjy/lbz-qynjjtzglqk/",
                table_keywords=["投资管理", "收益"]),
    Institution(2, "华夏基金", "http://www.chinaamc.com/yanglaojijin/nianjin/nianjinyeji/index.shtml",
                table_keywords=["年金", "投资"]),
    Institution(3, "银华基金", "https://www.yhfund.com.cn/main/annuity/reveal/index.shtml",
                table_keywords=["年金", "投资"]),
    Institution(4, "招商基金", "http://www.cmfchina.com/main/yljj/qynj/xxpl/index.shtml",
                table_keywords=["年金", "投资"]),
    Institution(5, "中金公司", "https://www.cicc.com/business/list_185_199_1.html",
                table_keywords=["年金", "投资"]),
    Institution(6, "平安养老", "https://yl.pingan.com/branding/products/annuity",
                table_keywords=["投资管理", "收益情况"]),
    Institution(7, "泰康资产", "https://www.taikangasset.cn/comproduct/ylbusiness/enterprisefunds/enterpriseinfo/list_294_1.html",
                table_keywords=["年金", "投资"]),
    Institution(8, "国寿养老", "https://www.chinalifepension.cn/chinalifepension/jgkh/qynj_yljcpxxpl/index.html",
                table_keywords=["年金", "投资"]),
    Institution(9, "人保养老", "https://www.picc-pension.com.cn/html1/category/181220/19-2.htm",
                table_keywords=["年金", "投资"]),
    Institution(10, "南方基金", "http://www.nffund.com/main/yljj/njxxpl/index.shtml?catalogId=14547",
                table_keywords=["年金", "投资"]),
    Institution(11, "易方达", "https://www.efunds.com.cn/lm/yljxxpl/",
                table_keywords=["年金", "投资"]),
    Institution(12, "博时基金", "https://www.bosera.com/column/index.do?classid=00020002000600010009",
                table_keywords=["年金", "投资"]),
    Institution(13, "中信证券", "http://www.cs.ecitic.com/newsite/ywzx/zcgl/qynj/xxdt/",
                table_keywords=["投资管理", "收益"]),
    Institution(14, "华泰资产", "https://www.htam.com.cn/yljcp_list.html",
                table_keywords=["年金", "投资"]),
    Institution(15, "国泰基金", "http://www.gtfund.com/Etrade/Report/nianjinreport/",
                table_keywords=["年金", "投资"]),
    Institution(16, "工银瑞信", "https://www.icbcubs.com.cn/PensionInvestment/PensionInvestment/PensionInvestment.html",
                table_keywords=["年金", "投资"]),
    Institution(17, "长江养老", "http://www.cj-pension.com.cn/cjyl/Channel/3505179_1/qynjcpxxpl/jdxxpl/",
                table_keywords=["年金", "投资"]),
    Institution(18, "富国基金", "https://www.fullgoal.com.cn/main/InstiServices/Retirement/RetirementInfoDis/qynjtzgl/index.html",
                table_keywords=["年金", "投资"]),
    Institution(19, "嘉实基金", "https://www.jsfund.cn/main/pensions/AnnuityBusiness/AnnuityBusinessinfo/index.shtml",
                table_keywords=["年金", "投资"]),
    Institution(20, "海富通", "https://www.hftfund.com/annuity/service/info/index.html",
                table_keywords=["年金", "投资"]),
    Institution(21, "建信养老", "https://www.ccbpension.com/#/product/ProductDisclosure",
                table_keywords=["年金", "投资"]),
    Institution(22, "新华养老", "https://www.newchinapension.com/xhylbx/_300468/312175/index.html",
                table_keywords=["年金", "投资"]),
]

CATEGORIES = [
    ("single_fixed", "单一计划", "固定收益类"),
    ("single_equity", "单一计划", "含权益类"),
    ("pooled_fixed", "集合计划", "固定收益类"),
    ("pooled_equity", "集合计划", "含权益类"),
    ("other_fixed", "其他计划", "固定收益类"),
    ("other_equity", "其他计划", "含权益类"),
]

# 关键词映射，用于从文本中识别计划类型和组合类型
PLAN_TYPE_KEYWORDS = {
    "single": ["单一", "单"],
    "pooled": ["集合", "集"],
    "other": ["其他", "他"],
}

ASSET_TYPE_KEYWORDS = {
    "fixed": ["固收", "固定", "债券", "货币"],
    "equity": ["权益", "股票", "混合", "含权"],
}

# ==================== 日志 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("annuity_scraper")

# ==================== HTML 获取 ====================

class Fetcher:
    """异步HTTP请求器，带重试和超时"""

    def __init__(self, max_workers: int = 5, timeout: int = 30, retries: int = 3):
        self.max_workers = max_workers
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.retries = retries
        self.semaphore = asyncio.Semaphore(max_workers)

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    async def fetch(self, institution: Institution) -> Tuple[Institution, Optional[str]]:
        """获取单个机构页面HTML"""
        async with self.semaphore:
            for attempt in range(1, self.retries + 1):
                try:
                    headers = {**self.headers, **institution.extra_headers}
                    async with aiohttp.ClientSession(timeout=self.timeout) as session:
                        async with session.get(
                            institution.url, headers=headers, ssl=False
                        ) as resp:
                            if resp.status == 200:
                                # 尝试自动检测编码
                                html = await resp.text()
                                logger.info(f"[OK] {institution.name}: 获取成功 ({len(html)} bytes)")
                                return institution, html
                            else:
                                logger.warning(
                                    f"[FAIL] {institution.name}: HTTP {resp.status} (尝试 {attempt}/{self.retries})"
                                )
                except asyncio.TimeoutError:
                    logger.warning(f"[FAIL] {institution.name}: 超时 (尝试 {attempt}/{self.retries})")
                except Exception as e:
                    logger.warning(f"[FAIL] {institution.name}: {type(e).__name__}: {e} (尝试 {attempt}/{self.retries})")

                if attempt < self.retries:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

            logger.error(f"[FAIL] {institution.name}: 所有重试均失败")
            return institution, None

    async def fetch_all(self, institutions: List[Institution]) -> List[Tuple[Institution, Optional[str]]]:
        """并发获取所有机构页面"""
        tasks = [self.fetch(inst) for inst in institutions]
        return await asyncio.gather(*tasks)


# ==================== 数据解析 ====================

class DataParser:
    """从HTML中解析年金数据"""

    def __init__(self):
        self.results: Dict[str, Dict] = {}

    def parse_all(self, pages: List[Tuple[Institution, Optional[str]]]) -> Dict[str, Dict]:
        """解析所有页面"""
        for inst, html in pages:
            if html:
                try:
                    data = self.parse_institution(inst, html)
                    self.results[inst.name] = data
                    if data:
                        logger.info(f"[OK] {inst.name}: 解析成功 ({len(data)} 条记录)")
                    else:
                        logger.warning(f"[WARN] {inst.name}: 未能解析出数据，可能需要手动调整解析规则")
                except Exception as e:
                    logger.error(f"[FAIL] {inst.name}: 解析异常: {e}")
                    self.results[inst.name] = {}
            else:
                self.results[inst.name] = {}
        return self.results

    def parse_institution(self, inst: Institution, html: str) -> Dict[str, Dict]:
        """解析单个机构的HTML"""
        soup = BeautifulSoup(html, "lxml")

        # 策略1: 查找包含关键词的表格
        table = self._find_target_table(soup, inst.table_keywords)
        if not table:
            # 策略2: 查找页面中最大的数据表格
            table = self._find_largest_table(soup)

        if not table:
            return {}

        return self._parse_table(table, inst)

    def _find_target_table(self, soup: BeautifulSoup, keywords: List[str]) -> Optional[Tag]:
        """查找包含指定关键词的表格"""
        if not keywords:
            return None

        # 先找表格标题
        for tag in soup.find_all(["h2", "h3", "h4", "div", "span", "p", "caption"]):
            text = tag.get_text()
            if any(kw in text for kw in keywords):
                # 向上/向下查找最近的表格
                table = tag.find_next("table")
                if table:
                    return table
                table = tag.find_previous("table")
                if table:
                    return table

        # 直接找包含关键词的表格
        for table in soup.find_all("table"):
            text = table.get_text()
            if any(kw in text for kw in keywords):
                # 检查表格中是否有数字数据
                if re.search(r'\d{1,3}(,\d{3})*\.?\d*', text):
                    return table

        return None

    def _find_largest_table(self, soup: BeautifulSoup) -> Optional[Tag]:
        """查找页面中最大的表格（数据最多的）"""
        tables = soup.find_all("table")
        if not tables:
            return None

        best_table = None
        best_score = 0
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            # 评分: 行数 * 含有数字的单元格数
            score = 0
            for row in rows:
                cells = row.find_all(["td", "th"])
                for cell in cells:
                    text = cell.get_text()
                    if re.search(r'\d+\.?\d*', text):
                        score += 1
            if score > best_score:
                best_score = score
                best_table = table

        return best_table

    def _parse_table(self, table: Tag, inst: Institution) -> Dict[str, Dict]:
        """解析表格数据"""
        result = {}
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            row_text = row.get_text()

            # 识别计划类型和组合类型
            plan_type = self._detect_plan_type(row_text)
            asset_type = self._detect_asset_type(row_text)

            if not plan_type or not asset_type:
                continue

            key = f"{plan_type}_{asset_type}"

            # 提取数字
            numbers = self._extract_numbers(row)
            if len(numbers) < 3:
                continue

            # 匹配数值到字段
            count, nav, ret = self._match_fields(numbers, row_text)

            if count or nav or ret:
                result[key] = {
                    "count": str(int(count)) if count else "",
                    "nav": f"{nav:.2f}" if nav else "",
                    "return": f"{ret:.2f}" if ret else "",
                }

        return result

    def _detect_plan_type(self, text: str) -> Optional[str]:
        """识别计划类型"""
        text = text.lower()
        for ptype, keywords in PLAN_TYPE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return ptype
        return None

    def _detect_asset_type(self, text: str) -> Optional[str]:
        """识别组合类型"""
        text = text.lower()
        for atype, keywords in ASSET_TYPE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return atype
        return None

    def _extract_numbers(self, row: Tag) -> List[float]:
        """从一行单元格中提取所有数字"""
        numbers = []
        for cell in row.find_all(["td", "th"]):
            text = cell.get_text().strip()
            # 匹配数字，包括千分位逗号
            matches = re.findall(r'[\d,]+\.?\d*', text)
            for m in matches:
                try:
                    numbers.append(float(m.replace(",", "")))
                except ValueError:
                    pass
        return numbers

    def _match_fields(self, numbers: List[float], row_text: str) -> Tuple[float, float, float]:
        """
        将提取的数字匹配到 count/nav/return 三个字段
        使用启发式规则
        """
        if not numbers:
            return 0, 0, 0

        # 去重并排序
        unique_nums = list(dict.fromkeys(numbers))
        sorted_nums = sorted(unique_nums)

        count, nav, ret = 0, 0, 0

        # 收益率: 通常在 0~30 之间，且常带有2位小数
        return_candidates = [n for n in unique_nums if -50 < n < 50]
        if return_candidates:
            # 取最大的合理值（收益率通常比组合数大但比净值小）
            ret = return_candidates[-1]

        # 组合数: 通常是较小的整数 (< 10000)
        count_candidates = [n for n in unique_nums
                           if n < 10000 and n > 0
                           and (n == int(n) or abs(n - int(n)) < 0.01)
                           and n != ret]
        if count_candidates:
            count = count_candidates[-1]  # 取最大的整数（组合数通常比收益率大）

        # 资产净值: 通常是最大的数字 (> 1000)
        nav_candidates = [n for n in unique_nums if n > 1000 and n != ret]
        if nav_candidates:
            nav = max(nav_candidates)

        # 如果启发式失败，使用位置推断
        if count == 0 and nav == 0 and ret == 0:
            if len(unique_nums) >= 3:
                # 假设格式: [count, nav, return] 或类似
                count = unique_nums[0] if unique_nums[0] < 10000 else 0
                ret = unique_nums[-1] if unique_nums[-1] < 50 else 0
                nav = max(n for n in unique_nums if n != ret) if unique_nums else 0

        return count, nav, ret


# ==================== 报告生成 ====================

def generate_report(results: Dict[str, Dict], quarter: str, output_path: str):
    """生成JSON报告"""
    # 构建与HTML页面兼容的格式
    output = {
        "quarter": quarter,
        "exportDate": datetime.now().isoformat(),
        "source": "auto_scraper",
        "summary": {
            "total_institutions": len(INSTITUTIONS),
            "success_count": sum(1 for v in results.values() if v),
            "failed_count": sum(1 for v in results.values() if not v),
        },
        "data": results,
        "verification_needed": [],
    }

    # 标记需要人工核对的数据
    for name, data in results.items():
        if not data:
            output["verification_needed"].append({
                "institution": name,
                "reason": "未抓取到数据，可能需要手动录入或调整解析规则",
            })
        elif len(data) < 6:
            missing = [key for key, _, _ in CATEGORIES if key not in data]
            output["verification_needed"].append({
                "institution": name,
                "reason": f"部分数据缺失: {', '.join(missing)}",
                "suggestion": "请手动核对并补充缺失数据",
            })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output


def print_summary(results: Dict[str, Dict]):
    """打印汇总信息"""
    print("\n" + "=" * 60)
    print("抓取结果汇总")
    print("=" * 60)

    success = 0
    partial = 0
    failed = 0

    for inst in INSTITUTIONS:
        data = results.get(inst.name, {})
        if not data:
            status = "[失败]"
            failed += 1
        elif len(data) == 6:
            status = "[完整]"
            success += 1
        else:
            status = f"[部分 {len(data)}/6]"
            partial += 1

        print(f"  {inst.id:2d}. {inst.name:12s} {status}")

    print("-" * 60)
    print(f"总计: {success} 完整 | {partial} 部分 | {failed} 失败")
    print(f"成功率: {(success + partial * 0.5) / len(INSTITUTIONS) * 100:.1f}%")
    print("=" * 60)

    if failed > 0 or partial > 0:
        print("\n提示: 抓取失败或部分成功的机构，建议:")
        print("  1. 访问该机构官网手动查看数据格式")
        print("  2. 在 annuity-collector.html 中手动录入")
        print("  3. 或修改本脚本中该机构的解析规则后重新运行")


# ==================== 主程序 ====================

async def main():
    parser = argparse.ArgumentParser(description="年金投资管理数据自动抓取")
    parser.add_argument("--quarter", default="2025Q4", help="季度，如 2025Q4")
    parser.add_argument("--output", default=None, help="输出JSON文件路径")
    parser.add_argument("--workers", type=int, default=5, help="并发数 (默认5)")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时秒数 (默认30)")
    parser.add_argument("--retries", type=int, default=3, help="重试次数 (默认3)")
    args = parser.parse_args()

    if args.output is None:
        args.output = f"annuity_data_{args.quarter}_{datetime.now().strftime('%Y-%m-%d')}.json"

    print(f"\n{'='*60}")
    print(f"年金投资管理数据自动抓取")
    print(f"季度: {args.quarter}")
    print(f"机构数: {len(INSTITUTIONS)}")
    print(f"并发数: {args.workers}")
    print(f"输出文件: {args.output}")
    print(f"{'='*60}\n")

    # 1. 获取所有页面
    fetcher = Fetcher(
        max_workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
    )
    logger.info("开始抓取页面...")
    pages = await fetcher.fetch_all(INSTITUTIONS)

    # 2. 解析数据
    logger.info("开始解析数据...")
    parser = DataParser()
    results = parser.parse_all(pages)

    # 3. 生成报告
    report = generate_report(results, args.quarter, args.output)

    # 4. 打印汇总
    print_summary(results)

    print(f"\n[OK] 数据已保存至: {Path(args.output).resolve()}")
    print(f"\n使用方式:")
    print(f'  1. 在 annuity-collector.html 页面中点击"导入JSON"导入此文件')
    print(f"  2. 或直接查看 JSON 文件内容")

    # 如果有需要核对的，输出详细信息
    if report["verification_needed"]:
        print(f"\n[注意] 以下机构需要人工核对:")
        for item in report["verification_needed"]:
            print(f"    - {item['institution']}: {item['reason']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
