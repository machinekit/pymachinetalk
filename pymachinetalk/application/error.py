# coding=utf-8
import threading

from ..common import ComponentBase
from ..dns_sd import ServiceContainer, Service
from ..machinetalk_core.application.errorbase import ErrorBase


class ApplicationError(ComponentBase, ErrorBase, ServiceContainer):
    def __init__(self, debug=False):
        ErrorBase.__init__(self, debuglevel=int(debug))
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.message_lock = threading.Lock()
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug

        # callbacks
        self.on_connected_changed = []

        self.connected = False
        self.channels = {'error', 'text', 'display'}
        self.error_list = []

        self._error_service = Service(type_='error')
        self.add_service(self._error_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    def _on_services_ready_changed(self, ready):
        self.error_uri = self._error_service.uri
        self.ready = ready

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def emc_nml_error_received(self, _, rx):
        self._error_message_received(rx)

    def emc_nml_text_received(self, _, rx):
        self._error_message_received(rx)

    def emc_nml_display_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_text_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_display_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_error_received(self, _, rx):
        self._error_message_received(rx)

    def _error_message_received(self, rx):
        error = {'type': rx.type, 'notes': []}
        with self.message_lock:
            for note in rx.note:
                error['notes'].append(note)
                self.error_list.append(error)

    # slot
    def update_topics(self):
        self.clear_error_topics()
        for channel in self.channels:
            self.add_error_topic(channel)

    # slot
    def set_connected(self):
        self._update_connected(True)

    # slot
    def clear_connected(self):
        self._update_connected(False)

    def _update_connected(self, connected):
        with self.connected_condition:
            self.connected = connected
            self.connected_condition.notify()
        for cb in self.on_connected_changed:
            cb(connected)

    # returns all received messages and clears the buffer
    def get_messages(self):
        with self.message_lock:
            messages = list(self.error_list)  # make sure to return a copy
            self.error_list = []
            return messages
