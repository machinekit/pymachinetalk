# coding=utf-8
import threading
from collections import namedtuple

from ..common import ComponentBase
from ..dns_sd import ServiceContainer, Service
from ..machinetalk_core.application.logbase import LogBase

# noinspection PyUnresolvedReferences
from machinetalk.protobuf.types_pb2 import (
    RTAPI_MSG_ALL,
    RTAPI_MSG_DBG,
    RTAPI_MSG_ERR,
    RTAPI_MSG_INFO,
    RTAPI_MSG_WARN,
    MSG_KERNEL,
    MSG_RTUSER,
    MSG_ULAPI,
)


ApplicationLogMessage = namedtuple(
    'ApplicationLogMessage', 'level origin tag pid text timestamp'
)


class ApplicationLog(ComponentBase, LogBase, ServiceContainer):
    def __init__(self, debug=False):
        LogBase.__init__(self, debuglevel=int(debug))
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug

        # callbacks
        self.on_connected_changed = []
        self.on_message_received = []

        self.connected = False
        self.log_level = RTAPI_MSG_ALL

        self._log_service = Service(type_='log')
        self.add_service(self._log_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    # slot
    def update_topics(self):
        self.clear_log_topics()
        self.add_log_topic('log')

    # slot
    def set_connected(self):
        self._update_connected(True)

    # slot
    def clear_connected(self):
        self._update_connected(False)

    # slot
    def log_message_received(self, identity, rx):
        log_message = rx.log_message
        print('received {}'.format(log_message))
        if log_message.level > self.log_level:
            return

        msg = ApplicationLogMessage(
            level=log_message.level,
            origin=log_message.origin,
            pid=log_message.pid,
            tag=log_message.tag,
            text=log_message.text,
            timestamp=self._convert_timestamp(rx.tv_sec, rx.tv_nsec),
        )
        for cb in self.on_message_received:
            cb(msg)

    @staticmethod
    def _convert_timestamp(sec, nsec):
        return sec * 1000 + nsec / 1000000

    def _update_connected(self, connected):
        with self.connected_condition:
            self.connected = connected
            self.connected_condition.notify()
        for cb in self.on_connected_changed:
            cb(connected)

    def _on_services_ready_changed(self, ready):
        self.log_uri = self._log_service.uri
        self.ready = ready
