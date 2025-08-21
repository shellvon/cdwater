"""数据更新协调器"""

import logging
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_USER_ID,
    CONF_UPDATE_INTERVAL,
    CONF_CAPTCHA_METHOD,
    CONF_CHAOJIYING_USER,
    CONF_CHAOJIYING_PASS,
    CONF_CHAOJIYING_SOFTID,
    DEFAULT_UPDATE_INTERVAL,
    CAPTCHA_METHOD_NCC,
    CAPTCHA_METHOD_CHAOJIYING,
)
from .client import CdwaterClient
from .captcha import CaptchaRecognizer

_LOGGER = logging.getLogger(__name__)


class CdwaterDataUpdateCoordinator(DataUpdateCoordinator):
    """成都自来水数据更新协调器"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """初始化协调器"""
        self.entry = entry
        self.user_id = entry.data[CONF_USER_ID]

        # 初始化验证码识别器
        self._captcha_recognizer = self._create_captcha_recognizer()

        # 获取更新间隔
        update_interval_days = entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        update_interval = timedelta(days=update_interval_days)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.user_id}",
            update_interval=update_interval,
        )

    def _create_captcha_recognizer(self):
        """创建验证码识别器"""
        captcha_method = self.entry.data.get(CONF_CAPTCHA_METHOD, CAPTCHA_METHOD_NCC)

        try:
            if captcha_method == CAPTCHA_METHOD_CHAOJIYING:
                username = self.entry.data.get(CONF_CHAOJIYING_USER)
                password = self.entry.data.get(CONF_CHAOJIYING_PASS)
                soft_id = self.entry.data.get(CONF_CHAOJIYING_SOFTID)

                if not all([username, password, soft_id]):
                    _LOGGER.warning("超级鹰配置不完整，回退到NCC方法")
                    return CaptchaRecognizer(method=CAPTCHA_METHOD_NCC)

                return CaptchaRecognizer(
                    method=CAPTCHA_METHOD_CHAOJIYING,
                    username=username,
                    password=password,
                    soft_id=soft_id,
                )
            else:
                return CaptchaRecognizer(method=CAPTCHA_METHOD_NCC)

        except Exception as e:
            _LOGGER.error(f"创建验证码识别器失败: {e}，回退到NCC方法")
            return CaptchaRecognizer(method=CAPTCHA_METHOD_NCC)

    async def _async_update_data(self):
        """更新数据"""
        try:
            # 使用3次重试机制
            async with CdwaterClient(self._captcha_recognizer, max_retries=3) as client:
                data = await client.get_water_bill_data(self.user_id)

                if not data.get("success", False):
                    raise UpdateFailed(f"获取数据失败: {data.get('error', '未知错误')}")

                _LOGGER.debug(f"成功获取用户 {self.user_id} 的数据")
                return data

        except Exception as err:
            _LOGGER.error(f"更新数据失败: {err}")
            raise UpdateFailed(f"更新数据失败: {err}")

    async def async_update_captcha_config(self):
        """更新验证码配置"""
        self._captcha_recognizer = self._create_captcha_recognizer()
        _LOGGER.info("验证码识别器配置已更新")

    async def async_options_updated(self):
        """选项更新时调用"""
        # 重新创建验证码识别器以应用新配置
        old_method = (
            self._captcha_recognizer.get_method()
            if self._captcha_recognizer
            else "unknown"
        )
        self._captcha_recognizer = self._create_captcha_recognizer()
        new_method = (
            self._captcha_recognizer.get_method()
            if self._captcha_recognizer
            else "unknown"
        )

        _LOGGER.info(f"配置已更新，验证码识别方式: {old_method} -> {new_method}")

        # 更新更新间隔
        update_interval_days = self.entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        self.update_interval = timedelta(days=update_interval_days)
        _LOGGER.info(f"更新间隔已更新为: {update_interval_days} 天")

    @property
    def latest_water_bill(self):
        """获取最新的水费账单"""
        if not self.data or not self.data.get("water_bills"):
            return None
        return self.data["water_bills"][0] if self.data["water_bills"] else None

    @property
    def latest_garbage_fee(self):
        """获取最新的垃圾处理费"""
        if not self.data or not self.data.get("garbage_fees"):
            return None
        return self.data["garbage_fees"][0] if self.data["garbage_fees"] else None

    @property
    def total_arrears(self):
        """获取总欠费金额"""
        if not self.data:
            return 0

        water_arrears = sum(
            item.get("amount_due", 0) - item.get("amount_paid", 0)
            for item in self.data.get("water_arrears", [])
        )

        garbage_arrears = sum(
            item.get("amount_due", 0) - item.get("amount_paid", 0)
            for item in self.data.get("garbage_arrears", [])
        )

        return water_arrears + garbage_arrears
