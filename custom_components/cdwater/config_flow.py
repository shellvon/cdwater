"""配置流程"""

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

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

_LOGGER = logging.getLogger(__name__)


class CdwaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """成都自来水配置流程"""

    VERSION = 1

    def __init__(self):
        """初始化配置流程"""
        self._user_input = {}

    async def async_step_user(self, user_input=None) -> FlowResult:
        """处理用户配置步骤"""
        errors = {}

        if user_input is not None:
            # 验证用户号格式
            user_id = user_input[CONF_USER_ID].strip()
            if not user_id:
                errors[CONF_USER_ID] = "invalid_user_id"
            elif not user_id.isdigit():
                errors[CONF_USER_ID] = "invalid_user_id"
            else:
                # 保存用户输入并进入验证码配置步骤
                self._user_input.update(user_input)
                return await self.async_step_captcha()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_captcha(self, user_input=None) -> FlowResult:
        """处理验证码配置步骤"""
        errors = {}

        if user_input is not None:
            captcha_method = user_input[CONF_CAPTCHA_METHOD]
            self._user_input.update(user_input)

            if captcha_method == CAPTCHA_METHOD_CHAOJIYING:
                return await self.async_step_chaojiying()
            else:
                # NCC方法，直接创建条目
                user_id = self._user_input[CONF_USER_ID]
                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"成都自来水 - {user_id}", data=self._user_input
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CAPTCHA_METHOD, default=CAPTCHA_METHOD_NCC): vol.In(
                    {
                        CAPTCHA_METHOD_NCC: CAPTCHA_METHOD_NCC,
                        CAPTCHA_METHOD_CHAOJIYING: CAPTCHA_METHOD_CHAOJIYING,
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="captcha", data_schema=data_schema, errors=errors
        )

    async def async_step_chaojiying(self, user_input=None) -> FlowResult:
        """处理超级鹰配置步骤"""
        errors = {}

        if user_input is not None:
            # 验证超级鹰配置
            username = user_input[CONF_CHAOJIYING_USER].strip()
            password = user_input[CONF_CHAOJIYING_PASS].strip()
            soft_id = user_input[CONF_CHAOJIYING_SOFTID].strip()

            if not username:
                errors[CONF_CHAOJIYING_USER] = "invalid_username"
            if not password:
                errors[CONF_CHAOJIYING_PASS] = "invalid_password"
            if not soft_id:
                errors[CONF_CHAOJIYING_SOFTID] = "invalid_softid"

            if not errors:
                self._user_input.update(user_input)
                user_id = self._user_input[CONF_USER_ID]

                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"成都自来水 - {user_id}", data=self._user_input
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CHAOJIYING_USER): str,
                vol.Required(CONF_CHAOJIYING_PASS): str,
                vol.Required(CONF_CHAOJIYING_SOFTID): str,
            }
        )

        return self.async_show_form(
            step_id="chaojiying", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """获取选项流程"""
        return CdwaterOptionsFlow(config_entry)


class CdwaterOptionsFlow(config_entries.OptionsFlow):
    """成都自来水选项流程"""

    def __init__(self, config_entry):
        """初始化选项流程"""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """处理选项配置初始步骤"""
        return self.async_show_menu(
            step_id="init", menu_options=["update_interval", "captcha_settings"]
        )

    async def async_step_update_interval(self, user_input=None) -> FlowResult:
        """处理更新间隔配置"""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=7)
                ),
            }
        )

        return self.async_show_form(step_id="update_interval", data_schema=data_schema)

    async def async_step_captcha_settings(self, user_input=None) -> FlowResult:
        """处理验证码设置配置"""
        if user_input is not None:
            captcha_method = user_input[CONF_CAPTCHA_METHOD]

            if captcha_method == CAPTCHA_METHOD_CHAOJIYING:
                # 需要配置超级鹰参数
                self._temp_data = user_input
                return await self.async_step_chaojiying_options()
            else:
                # NCC方法，直接保存
                return self.async_create_entry(title="", data=user_input)

        current_method = self.config_entry.data.get(
            CONF_CAPTCHA_METHOD, CAPTCHA_METHOD_NCC
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CAPTCHA_METHOD, default=current_method): vol.In(
                    {
                        CAPTCHA_METHOD_NCC: CAPTCHA_METHOD_NCC,
                        CAPTCHA_METHOD_CHAOJIYING: CAPTCHA_METHOD_CHAOJIYING,
                    }
                ),
            }
        )

        return self.async_show_form(step_id="captcha_settings", data_schema=data_schema)

    async def async_step_chaojiying_options(self, user_input=None) -> FlowResult:
        """处理超级鹰选项配置"""
        if user_input is not None:
            # 合并数据
            final_data = {**self._temp_data, **user_input}
            return self.async_create_entry(title="", data=final_data)

        current_user = self.config_entry.data.get(CONF_CHAOJIYING_USER, "")
        current_pass = self.config_entry.data.get(CONF_CHAOJIYING_PASS, "")
        current_softid = self.config_entry.data.get(CONF_CHAOJIYING_SOFTID, "")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CHAOJIYING_USER, default=current_user): str,
                vol.Required(CONF_CHAOJIYING_PASS, default=current_pass): str,
                vol.Required(CONF_CHAOJIYING_SOFTID, default=current_softid): str,
            }
        )

        return self.async_show_form(
            step_id="chaojiying_options", data_schema=data_schema
        )
