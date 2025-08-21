"""传感器实体"""

import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CdwaterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置传感器实体"""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CdwaterUsageSensor(coordinator, entry),
        CdwaterCurrentReadingSensor(coordinator, entry),
        CdwaterPreviousReadingSensor(coordinator, entry),
        CdwaterAmountDueSensor(coordinator, entry),
        CdwaterAmountPaidSensor(coordinator, entry),
        CdwaterPaymentStatusSensor(coordinator, entry),
        CdwaterGarbageFeeSensor(coordinator, entry),
        CdwaterTotalArrearsSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class CdwaterBaseSensor(CoordinatorEntity, SensorEntity):
    """成都自来水基础传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        """初始化传感器"""
        super().__init__(coordinator)
        self._entry = entry
        self._user_id = entry.data["user_id"]

    @property
    def device_info(self):
        """设备信息"""
        return {
            "identifiers": {(DOMAIN, self._user_id)},
            "name": f"成都自来水 {self._user_id}",
            "manufacturer": "成都自来水公司",
            "model": "水费查询",
        }


class CdwaterUsageSensor(CdwaterBaseSensor):
    """用水量传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_usage"
        self._attr_name = f"成都自来水 {self._user_id} 用水量"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_icon = "mdi:water"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("usage") if bill else None

    @property
    def extra_state_attributes(self):
        """额外属性"""
        bill = self.coordinator.latest_water_bill
        if not bill:
            return {}

        return {
            "meter_date": bill.get("meter_date"),
            "unit_price": bill.get("unit_price"),
            "previous_reading": bill.get("previous_reading"),
            "current_reading": bill.get("current_reading"),
        }


class CdwaterCurrentReadingSensor(CdwaterBaseSensor):
    """当前读数传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_current_reading"
        self._attr_name = f"成都自来水 {self._user_id} 当前读数"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("current_reading") if bill else None


class CdwaterPreviousReadingSensor(CdwaterBaseSensor):
    """上次读数传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_previous_reading"
        self._attr_name = f"成都自来水 {self._user_id} 上次读数"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("previous_reading") if bill else None


class CdwaterAmountDueSensor(CdwaterBaseSensor):
    """应缴费用传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_amount_due"
        self._attr_name = f"成都自来水 {self._user_id} 应缴费用"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "CNY"
        self._attr_icon = "mdi:currency-cny"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("amount_due") if bill else None


class CdwaterAmountPaidSensor(CdwaterBaseSensor):
    """实缴费用传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_amount_paid"
        self._attr_name = f"成都自来水 {self._user_id} 实缴费用"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "CNY"
        self._attr_icon = "mdi:currency-cny"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("amount_paid") if bill else None


class CdwaterPaymentStatusSensor(CdwaterBaseSensor):
    """缴费状态传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_payment_status"
        self._attr_name = f"成都自来水 {self._user_id} 缴费状态"
        self._attr_icon = "mdi:check-circle"

    @property
    def native_value(self):
        """传感器值"""
        bill = self.coordinator.latest_water_bill
        return bill.get("payment_status") if bill else None

    @property
    def extra_state_attributes(self):
        """额外属性"""
        bill = self.coordinator.latest_water_bill
        if not bill:
            return {}

        return {
            "payment_date": bill.get("payment_date"),
            "meter_date": bill.get("meter_date"),
        }


class CdwaterGarbageFeeSensor(CdwaterBaseSensor):
    """垃圾处理费传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_garbage_fee"
        self._attr_name = f"成都自来水 {self._user_id} 垃圾处理费"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "CNY"
        self._attr_icon = "mdi:delete"

    @property
    def native_value(self):
        """传感器值"""
        fee = self.coordinator.latest_garbage_fee
        return fee.get("amount_due") if fee else None

    @property
    def extra_state_attributes(self):
        """额外属性"""
        fee = self.coordinator.latest_garbage_fee
        if not fee:
            return {}

        return {
            "bill_date": fee.get("bill_date"),
            "amount_paid": fee.get("amount_paid"),
            "payment_status": fee.get("payment_status"),
            "payment_date": fee.get("payment_date"),
        }


class CdwaterTotalArrearsSensor(CdwaterBaseSensor):
    """总欠费传感器"""

    def __init__(self, coordinator: CdwaterDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{self._user_id}_total_arrears"
        self._attr_name = f"成都自来水 {self._user_id} 总欠费"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "CNY"
        self._attr_icon = "mdi:alert-circle"

    @property
    def native_value(self):
        """传感器值"""
        return self.coordinator.total_arrears
