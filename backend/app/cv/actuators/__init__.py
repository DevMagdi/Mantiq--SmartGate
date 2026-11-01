"""Barrier actuators: simulator, HTTP webhook, MQTT and GPIO/relay."""

from app.cv.actuators.base import (
    BARRIER_ACTIONS,
    ActuatorResult,
    BarrierAction,
    BarrierActuator,
)
from app.cv.actuators.gpio import GpioActuator
from app.cv.actuators.journal import CommandJournal, CommandRecord, command_journal
from app.cv.actuators.mqtt import MqttActuator
from app.cv.actuators.registry import ActuatorRegistry, actuator_registry, build_actuator
from app.cv.actuators.simulator import SimulatedActuator
from app.cv.actuators.webhook import WebhookActuator, sign_payload

__all__ = [
    "ActuatorRegistry",
    "ActuatorResult",
    "BARRIER_ACTIONS",
    "BarrierAction",
    "BarrierActuator",
    "CommandJournal",
    "CommandRecord",
    "GpioActuator",
    "MqttActuator",
    "SimulatedActuator",
    "WebhookActuator",
    "actuator_registry",
    "build_actuator",
    "command_journal",
    "sign_payload",
]
