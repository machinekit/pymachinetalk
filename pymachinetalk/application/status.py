# coding=utf-8
import threading

from machinetalk.protobuf.message_pb2 import Container
from machinetalk.protobuf.status_pb2 import (
    EMC_TASK_MODE_AUTO,
    EMC_TASK_MODE_MDI,
    EMC_TASK_INTERP_IDLE,
)
from ..common import ComponentBase, MessageObject, recurse_descriptor, recurse_message
from ..dns_sd import ServiceContainer, Service
from ..machinetalk_core.application.statusbase import StatusBase


class ApplicationStatus(ComponentBase, StatusBase, ServiceContainer):
    def __init__(self, debug=False):
        StatusBase.__init__(self, debuglevel=int(debug))
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.config_condition = threading.Condition(threading.Lock())
        self.io_condition = threading.Condition(threading.Lock())
        self.motion_condition = threading.Condition(threading.Lock())
        self.task_condition = threading.Condition(threading.Lock())
        self.interp_condition = threading.Condition(threading.Lock())
        self.synced_condition = threading.Condition(threading.Lock())
        self.debug = debug

        # callbacks
        self.on_synced_changed = []

        self.synced = False

        # status containers, also used to expose data
        self._io_data = None
        self._motion_data = None
        self._config_data = None
        self._task_data = None
        self._interp_data = None
        # required for object initialization
        self._container = Container()
        self._initialize_object('io')
        self._initialize_object('config')
        self._initialize_object('motion')
        self._initialize_object('task')
        self._initialize_object('interp')

        self._synced_channels = set()
        self.channels = {'motion', 'config', 'task', 'io', 'interp'}

        self._status_service = Service(type_='status')
        self.add_service(self._status_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    def _on_services_ready_changed(self, ready):
        self.status_uri = self._status_service.uri
        self.ready = ready

    # make sure locks are used when accessing properties
    # should we return a copy instead of the reference?
    @property
    def io(self):
        with self.io_condition:
            return self._io_data

    @property
    def config(self):
        with self.config_condition:
            return self._config_data

    @property
    def motion(self):
        with self.motion_condition:
            return self._motion_data

    @property
    def task(self):
        with self.task_condition:
            return self._task_data

    @property
    def interp(self):
        with self.interp_condition:
            return self._interp_data

    def wait_synced(self, timeout=None):
        with self.synced_condition:
            if self.synced:
                return True
            self.synced_condition.wait(timeout=timeout)
            return self.synced

    def wait_config_updated(self, timeout=None):
        with self.config_condition:
            self.config_condition.wait(timeout=timeout)

    def wait_io_updated(self, timeout=None):
        with self.io_condition:
            self.io_condition.wait(timeout=timeout)

    def wait_motion_updated(self, timeout=None):
        with self.motion_condition:
            self.motion_condition.wait(timeout=timeout)

    def wait_task_updated(self, timeout=None):
        with self.task_condition:
            self.task_condition.wait(timeout=timeout)

    def wait_interp_updated(self, timeout=None):
        with self.interp_condition:
            self.interp_condition.wait(timeout=timeout)

    def emcstat_full_update_received(self, topic, rx):
        self._emcstat_update_received(topic, rx)
        self._update_synced_channels(topic)

    def emcstat_incremental_update_received(self, topic, rx):
        self._emcstat_update_received(topic, rx)

    def _emcstat_update_received(self, topic, rx):
        if topic == 'motion' and rx.HasField('emc_status_motion'):
            self._update_motion_object(rx.emc_status_motion)
        elif topic == 'config' and rx.HasField('emc_status_config'):
            self._update_config_object(rx.emc_status_config)
        elif topic == 'io' and rx.HasField('emc_status_io'):
            self._update_io_object(rx.emc_status_io)
        elif topic == 'task' and rx.HasField('emc_status_task'):
            self._update_task_object(rx.emc_status_task)
        elif topic == 'interp' and rx.HasField('emc_status_interp'):
            self._update_interp_object(rx.emc_status_interp)

    def _update_synced_channels(self, channel):
        self._synced_channels.add(channel)
        if (self._synced_channels == self.channels) and not self.synced:
            self.channels_synced()

    # slot
    def sync_status(self):
        self._update_synced(True)

    # slot
    def unsync_status(self):
        self._synced_channels.clear()
        self._update_synced(False)

    def _update_synced(self, synced):
        with self.synced_condition:
            self.synced = synced
            self.synced_condition.notify()
        for cb in self.on_synced_changed:
            cb(synced)

    # slot
    def update_topics(self):
        self.clear_status_topics()
        for channel in self.channels:
            self.add_status_topic(channel)
            self._initialize_object(channel)

    def _initialize_object(self, channel):
        if channel == 'io':
            self._io_data = MessageObject()
            recurse_descriptor(self._container.emc_status_io.DESCRIPTOR, self._io_data)
        elif channel == 'config':
            self._config_data = MessageObject()
            recurse_descriptor(
                self._container.emc_status_config.DESCRIPTOR, self._config_data
            )
        elif channel == 'motion':
            self._motion_data = MessageObject()
            recurse_descriptor(
                self._container.emc_status_motion.DESCRIPTOR, self._motion_data
            )
        elif channel == 'task':
            self._task_data = MessageObject()
            recurse_descriptor(
                self._container.emc_status_task.DESCRIPTOR, self._task_data
            )
        elif channel == 'interp':
            self._interp_data = MessageObject()
            recurse_descriptor(
                self._container.emc_status_interp.DESCRIPTOR, self._interp_data
            )

    def _update_motion_object(self, data):
        with self.motion_condition:
            recurse_message(data, self._motion_data)
            self.motion_condition.notify()

    def _update_config_object(self, data):
        with self.config_condition:
            recurse_message(data, self._config_data)
            self.config_condition.notify()

    def _update_io_object(self, data):
        with self.io_condition:
            recurse_message(data, self._io_data)
            self.io_condition.notify()

    def _update_task_object(self, data):
        with self.task_condition:
            recurse_message(data, self._task_data)
            self._update_running()
            self.task_condition.notify()

    def _update_interp_object(self, data):
        with self.interp_condition:
            recurse_message(data, self._interp_data)
            self._update_running()
            self.interp_condition.notify()

    def _update_running(self):
        running = (
            self._task_data.task_mode == EMC_TASK_MODE_AUTO
            or self._task_data.task_mode == EMC_TASK_MODE_MDI
        ) and self._interp_data.interp_state == EMC_TASK_INTERP_IDLE

        self.running = running
