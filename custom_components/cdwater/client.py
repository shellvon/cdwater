"""成都自来水API客户端"""

import logging
import random
import re
from typing import Dict, List, Optional
from urllib.parse import quote
from html.parser import HTMLParser
import aiohttp

_LOGGER = logging.getLogger(__name__)

# API URLs
BASE_URL = "https://www.cdwater.com.cn"
WATERBILL_URL = f"{BASE_URL}/htm/waterbill.html"
RECORD_URL_TEMPLATE = f"{BASE_URL}/record_{{random_value}}.html"
API_URL_TEMPLATE = f"{BASE_URL}/htm/getdbsign_{{random_value}}.html"

# 默认请求头
DEFAULT_HEADERS = {
    "Host": "www.cdwater.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh-CN;q=0.9,zh;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}


class CdwaterHTMLParser(HTMLParser):
    """简化的HTML解析器"""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = None
        self.current_row = None
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ["td", "th"] and self.in_row:
            self.in_cell = True
            self.cell_text = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            if self.current_table:
                self.tables.append(self.current_table)
            self.in_table = False
            self.current_table = None
        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.current_table.append(self.current_row)
            self.in_row = False
            self.current_row = None
        elif tag in ["td", "th"] and self.in_cell:
            self.current_row.append(self.cell_text.strip())
            self.in_cell = False
            self.cell_text = ""

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text += data


class CdwaterClient:
    """成都自来水客户端"""

    def __init__(self, captcha_recognizer=None, max_retries=3):
        """初始化客户端

        Args:
            captcha_recognizer: 验证码识别器，如果不提供则需要外部处理验证码
            max_retries: 最大重试次数
        """
        self._session = None
        self._captcha_recognizer = captcha_recognizer
        self._max_retries = max_retries

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self._session = aiohttp.ClientSession(
            headers=DEFAULT_HEADERS, timeout=aiohttp.ClientTimeout(total=30)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self._session:
            await self._session.close()

    async def get_water_bill_data(self, user_id: str) -> Dict:
        """获取水费账单数据

        Args:
            user_id: 用户号

        Returns:
            解析后的账单数据
        """
        if not self._session:
            raise RuntimeError("客户端未初始化")

        last_error = None

        # 重试机制
        for attempt in range(self._max_retries):
            try:
                _LOGGER.debug(f"开始第 {attempt + 1} 次尝试获取水费数据")

                # 第一步：访问主页面建立会话
                await self._visit_main_page()

                # 第二步：获取验证码
                captcha_text, confidence = await self._get_captcha()

                # 第三步：提交查询请求
                response_text = await self._submit_query(user_id, captcha_text)

                # 第四步：解析响应数据
                result = self._parse_response(response_text)

                if result.get("success"):
                    _LOGGER.info(
                        f"第 {attempt + 1} 次尝试成功，验证码: {captcha_text}, 置信度: {confidence:.3f}"
                    )
                    return result
                else:
                    # 解析失败，检查是否需要重试
                    error_msg = result.get("error", "未知错误")
                    _LOGGER.warning(f"第 {attempt + 1} 次尝试失败: {error_msg}")
                    last_error = Exception(error_msg)

                    # 只在验证码错误时重试
                    should_retry = (
                        "验证码错误" in error_msg
                        or "状态码: 1" in error_msg
                        or "验证码" in error_msg
                    )

                    if should_retry and attempt < self._max_retries - 1:
                        _LOGGER.info(f"验证码相关错误，将进行第 {attempt + 2} 次重试")
                        continue
                    else:
                        _LOGGER.info(f"非验证码错误或已达最大重试次数，停止重试")
                        break

            except Exception as e:
                _LOGGER.warning(f"第 {attempt + 1} 次尝试出现异常: {e}")
                last_error = e

                # 网络超时等异常可以重试
                should_retry = (
                    "timeout" in str(e).lower()
                    or "connection" in str(e).lower()
                    or "network" in str(e).lower()
                )

                if should_retry and attempt < self._max_retries - 1:
                    _LOGGER.info(f"网络相关异常，将进行第 {attempt + 2} 次重试")
                    continue
                else:
                    _LOGGER.info(f"非网络异常或已达最大重试次数，停止重试")
                    break

        # 所有重试都失败了
        error_msg = f"经过 {self._max_retries} 次重试后仍然失败"
        if last_error:
            error_msg += f": {last_error}"

        _LOGGER.error(error_msg)
        return {"success": False, "error": error_msg}

    async def _visit_main_page(self):
        """访问主页面建立会话"""
        try:
            async with self._session.get(WATERBILL_URL) as response:
                if response.status != 200:
                    raise Exception(f"访问主页面失败: {response.status}")
                _LOGGER.debug("成功访问主页面")
        except Exception as e:
            _LOGGER.error(f"访问主页面失败: {e}")
            raise

    async def _get_captcha(self) -> tuple:
        """获取并识别验证码

        Returns:
            (验证码文本, 置信度)
        """
        # 生成随机值
        random_value = str(random.random())
        captcha_url = RECORD_URL_TEMPLATE.format(random_value=random_value)

        try:
            async with self._session.get(captcha_url) as response:
                if response.status != 200:
                    raise Exception(f"获取验证码失败: {response.status}")

                image_data = await response.read()

                # 识别验证码
                if self._captcha_recognizer and self._captcha_recognizer.is_available():
                    captcha_text, confidence = await self._captcha_recognizer.recognize(
                        image_data
                    )
                else:
                    raise Exception("没有可用的验证码识别方法")

                _LOGGER.debug(
                    f"验证码识别成功: {captcha_text}, 置信度: {confidence:.3f}"
                )
                return captcha_text, confidence

        except Exception as e:
            _LOGGER.error(f"获取验证码失败: {e}")
            raise

    async def _submit_query(self, user_id: str, captcha_text: str) -> str:
        """提交查询请求"""
        # 生成随机值
        random_value = str(random.random())
        api_url = API_URL_TEMPLATE.format(random_value=random_value)

        # 构建查询参数
        params = {"method": "getwaterbillsign", "kh": user_id, "yzm": captcha_text}

        # 更新请求头
        headers = {
            "Referer": WATERBILL_URL,
            "Accept": "text/plain, */*; q=0.01",
        }

        try:
            async with self._session.get(
                api_url, params=params, headers=headers
            ) as response:
                if response.status != 200:
                    raise Exception(f"查询请求失败: {response.status}")

                response_text = await response.text()
                _LOGGER.debug(f"查询响应: {response_text[:200]}...")
                return response_text

        except Exception as e:
            _LOGGER.error(f"提交查询失败: {e}")
            raise

    def _parse_response(self, response_text: str) -> Dict:
        """解析响应数据"""
        try:
            _LOGGER.debug(f"开始解析响应数据，响应长度: {len(response_text)}")
            # 检查响应状态
            parts = response_text.split("w|f")

            if len(parts) == 0:
                raise Exception("响应格式错误：无法分割响应")

            status_code = parts[0]

            if status_code != "1":
                error_msg = parts[1] if len(parts) > 1 else "未知错误"
                raise Exception(f"查询失败，状态码: {status_code}, 原因: {error_msg}")

            # 提取HTML部分
            html_part = response_text.split("w|f")[-1]

            # 解析HTML
            parser = CdwaterHTMLParser()
            parser.feed(html_part)

            _LOGGER.debug(f"解析到 {len(parser.tables)} 个表格")

            water_bills = self._parse_water_bills(parser.tables)
            garbage_fees = self._parse_garbage_fees(parser.tables)
            water_arrears = self._parse_water_arrears(parser.tables)
            garbage_arrears = self._parse_garbage_arrears(parser.tables)

            _LOGGER.info(
                f"解析结果: 水费账单 {len(water_bills)} 条, 垃圾费 {len(garbage_fees)} 条, 水费欠费 {len(water_arrears)} 条, 垃圾费欠费 {len(garbage_arrears)} 条"
            )

            return {
                "water_bills": water_bills,
                "garbage_fees": garbage_fees,
                "water_arrears": water_arrears,
                "garbage_arrears": garbage_arrears,
                "success": True,
            }

        except Exception as e:
            _LOGGER.error(f"解析响应数据失败: {e}")
            _LOGGER.debug(f"失败的响应文本: {response_text}")
            return {"success": False, "error": str(e)}

    def _parse_water_bills(self, tables: List[List[List[str]]]) -> List[Dict]:
        """解析水费账单数据"""
        bills = []

        if not tables:
            return bills

        # 第一个表格是水费数据
        water_table = tables[0]
        _LOGGER.debug(f"水费表格有 {len(water_table)} 行")

        if len(water_table) < 2:
            return bills

        # 跳过表头，解析数据行
        for row in water_table[1:]:
            if len(row) >= 14:
                bill = {
                    "user_id": self._clean_text(row[0]),
                    "meter_date": self._clean_text(row[1]),
                    "previous_reading": self._safe_float(row[2]),
                    "current_reading": self._safe_float(row[3]),
                    "usage": self._safe_float(row[4]),
                    "unit_price": self._safe_float(row[5]),
                    "amount_due": self._safe_float(row[6]),
                    "amount_paid": self._safe_float(row[7]),
                    "previous_balance": self._safe_float(row[8]),
                    "current_balance": self._safe_float(row[9]),
                    "penalty_due": self._safe_float(row[10]),
                    "penalty_paid": self._safe_float(row[11]),
                    "payment_date": self._clean_text(row[12]),
                    "payment_status": self._clean_text(row[13]),
                }
                bills.append(bill)

        return bills

    def _parse_garbage_fees(self, tables: List[List[List[str]]]) -> List[Dict]:
        """解析垃圾处理费数据"""
        fees = []

        if len(tables) < 2:
            return fees

        # 第二个表格是垃圾处理费数据
        garbage_table = tables[1]

        if len(garbage_table) < 2:
            return fees

        # 跳过表头，解析数据行
        for row in garbage_table[1:]:
            if len(row) >= 8:
                fee = {
                    "user_id": self._clean_text(row[0]),
                    "bill_date": self._clean_text(row[1]),
                    "unit_price": self._safe_float(row[2]),
                    "period_months": self._safe_int(row[3]),
                    "amount_due": self._safe_float(row[4]),
                    "amount_paid": self._safe_float(row[5]),
                    "payment_date": self._clean_text(row[6]),
                    "payment_status": self._clean_text(row[7]),
                }
                fees.append(fee)

        return fees

    def _parse_water_arrears(self, tables: List[List[List[str]]]) -> List[Dict]:
        """解析水费欠费数据"""
        # 查找水费欠费表格（通常为空）
        return []

    def _parse_garbage_arrears(self, tables: List[List[List[str]]]) -> List[Dict]:
        """解析垃圾处理费欠费数据"""
        arrears = []

        if len(tables) < 4:
            return arrears

        # 第四个表格是垃圾处理费欠费数据
        arrears_table = tables[3]

        if len(arrears_table) < 2:
            return arrears

        # 跳过表头，解析数据行
        for row in arrears_table[1:]:
            if len(row) >= 7:
                arrear = {
                    "user_id": self._clean_text(row[0]),
                    "bill_date": self._clean_text(row[1]),
                    "unit_price": self._safe_float(row[2]),
                    "period_months": self._safe_int(row[3]),
                    "amount_due": self._safe_float(row[4]),
                    "amount_paid": self._safe_float(row[5]),
                    "payment_status": self._clean_text(row[6]),
                }
                arrears.append(arrear)

        return arrears

    def _clean_text(self, text: str) -> str:
        """清理文本内容"""
        if not text:
            return ""
        return text.replace("\xa0", "").replace("&nbsp;", "").strip()

    def _safe_float(self, text: str) -> float:
        """安全转换为浮点数"""
        try:
            cleaned = self._clean_text(text)
            return float(cleaned) if cleaned else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _safe_int(self, text: str) -> int:
        """安全转换为整数"""
        try:
            cleaned = self._clean_text(text)
            return int(cleaned) if cleaned else 0
        except (ValueError, TypeError):
            return 0
