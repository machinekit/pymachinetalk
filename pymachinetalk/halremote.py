# coding=utf-8
import threading
from .dns_sd import ServiceContainer, Service
from .common import ComponentBase

# protobuf
from machinetalk.protobuf.message_pb2 import Container

# noinspection PyUnresolvedReferences
from machinetalk.protobuf.types_pb2 import (
    HAL_FLOAT,
    HAL_BIT,
    HAL_S32,
    HAL_U32,
    HAL_IN,
    HAL_IO,
    HAL_OUT,
)
from .machinetalk_core.halremote.remotecomponentbase import RemoteComponentBase


class Pin(object):
    def __init__(self):
        self.name = ''
        self.pintype = HAL_BIT
        self.direction = HAL_IN
        self._synced = False
        self._value = None
        self.handle = 0  # stores handle received on bind
        self.parent = None
        self.synced_condition = threading.Condition(threading.Lock())
        self.value_condition = threading.Condition(threading.Lock())

        # callbacks
        self.on_synced_changed = []
        self.on_value_changed = []

    def wait_synced(self, timeout=None):
        with self.synced_condition:
            if self.synced:
                return True
            self.synced_condition.wait(timeout=timeout)
            return self.synced

    def wait_value(self, timeout=None):
        with self.value_condition:
            if self.value:
                return True
            self.value_condition.wait(timeout=timeout)
            return self.value

    @property
    def value(self):
        with self.value_condition:
            return self._value

    @value.setter
    def value(self, value):
        with self.value_condition:
            if self._value != value:
                self._value = value
                self.value_condition.notify()
                for func in self.on_value_changed:
                    func(value)

    @property
    def synced(self):
        with self.synced_condition:
            return self._synced

    @synced.setter
    def synced(self, value):
        with self.synced_condition:
            if value != self._synced:
                self._synced = value
                self.synced_condition.notify()
                for func in self.on_synced_changed:
                    func(value)

    def set(self, value):
        if self.value != value:
            self.value = value
            self.synced = False
            if self.parent:
                self.parent.pin_change(self)

    def get(self):
        return self.value


class RemoteComponent(ComponentBase, RemoteComponentBase, ServiceContainer):
    def __init__(self, name, debug=False):
        RemoteComponentBase.__init__(self, debuglevel=int(debug))
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug

        # callbacks
        self.on_connected_changed = []

        self.name = name
        self.pinsbyname = {}
        self.pinsbyhandle = {}
        self.no_create = False
        self.no_bind = False

        self.connected = False

        # more efficient to reuse a protobuf message
        self._tx = Container()

        self._halrcomp_service = Service(type_='halrcomp')
        self._halrcmd_service = Service(type_='halrcmd')
        self.add_service(self._halrcomp_service)
        self.add_service(self._halrcmd_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    def _on_services_ready_changed(self, ready):
        self.halrcomp_uri = self._halrcomp_service.uri
        self.halrcmd_uri = self._halrcmd_service.uri
        self.ready = ready

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def set_connected(self):
        with self.connected_condition:
            self.connected = True
            self.connected_condition.notify()
        for cb in self.on_connected_changed:
            cb(self.connected)

    def set_error(self):
        self._check_disconnected()

    def set_disconnected(self):
        self._check_disconnected()

    def set_connecting(self):
        self._check_disconnected()

    def set_timeout(self):
        self._check_disconnected()

    def _check_disconnected(self):
        changed = False
        with self.connected_condition:
            if self.connected:
                self.connected = False
                self.connected_condition.notify()
                changed = True
        if changed:
            for cb in self.on_connected_changed:
                cb(self.connected)

    def halrcomp_incremental_update_received(self, _, rx):
        for rpin in rx.pin:
            lpin = self.pinsbyhandle[rpin.handle]
            self.pin_update(rpin, lpin)

    def halrcomp_full_update_received(self, _, rx):
        if len(rx.comp) == 0:  # empty message
            return

        comp = rx.comp[0]
        for rpin in comp.pin:
            name = '.'.join(rpin.name.split('.')[1:])
            lpin = self.pinsbyname[name]
            lpin.handle = rpin.handle
            self.pinsbyhandle[rpin.handle] = lpin
            self.pin_update(rpin, lpin)

        self.pins_synced()  # accept that pins have been synced

    def halrcomp_error_received(self, _, rx):
        pass

    # create a new HAL pin
    def newpin(self, name, pintype, direction):
        pin = Pin()
        pin.name = name
        pin.pintype = pintype
        pin.direction = direction
        pin.parent = self
        self.pinsbyname[name] = pin

        if pintype == HAL_FLOAT:
            pin.value = 0.0
        elif pintype == HAL_BIT:
            pin.value = False
        elif pintype == HAL_S32:
            pin.value = 0
        elif pintype == HAL_U32:
            pin.value = 0

        return pin

    def unsync_pins(self):
        for name in self.pinsbyname:
            self.pinsbyname[name].synced = False

    def getpin(self, name):
        return self.pinsbyname[name]

    @staticmethod
    def pin_update(rpin, lpin):
        if rpin.HasField('halfloat'):
            lpin.value = float(rpin.halfloat)
            lpin.synced = True
        elif rpin.HasField('halbit'):
            lpin.value = bool(rpin.halbit)
            lpin.synced = True
        elif rpin.HasField('hals32'):
            lpin.value = int(rpin.hals32)
            lpin.synced = True
        elif rpin.HasField('halu32'):
            lpin.value = int(rpin.halu32)
            lpin.synced = True

    def pin_change(self, pin):
        if self.debug:
            print('[%s] pin change %s' % (self.name, pin.name))

        if not self.connected:  # accept only when connected
            return
        if pin.direction == HAL_IN:  # only update out and IO pins
            return

        # This message MUST carry a Pin message for each pin which has
        # changed value since the last message of this type.
        # Each Pin message MUST carry the handle field.
        # Each Pin message MAY carry the name field.
        # Each Pin message MUST carry the type field
        # Each Pin message MUST - depending on pin type - carry a halbit,
        # halfloat, hals32, or halu32 field.
        p = self._tx.pin.add()
        p.handle = pin.handle
        p.type = pin.pintype
        if p.type == HAL_FLOAT:
            p.halfloat = float(pin.value)
        elif p.type == HAL_BIT:
            p.halbit = bool(pin.value)
        elif p.type == HAL_S32:
            p.hals32 = int(pin.value)
        elif p.type == HAL_U32:
            p.halu32 = int(pin.value)
        self.send_halrcomp_set(self._tx)

    def bind_component(self):
        c = self._tx.comp.add()
        c.name = self.name
        c.no_create = self.no_create  # for now we create the component
        for name, pin in self.pinsbyname.iteritems():
            p = c.pin.add()
            p.name = '%s.%s' % (self.name, name)
            p.type = pin.pintype
            p.dir = pin.direction
            if p.type == HAL_FLOAT:
                p.halfloat = float(pin.value)
            elif p.type == HAL_BIT:
                p.halbit = bool(pin.value)
            elif p.type == HAL_S32:
                p.hals32 = int(pin.value)
            elif p.type == HAL_U32:
                p.halu32 = int(pin.value)
        if self.debug:
            print('[%s] bind' % self.name)
        self.send_halrcomp_bind(self._tx)

    def add_pins(self):
        self.clear_halrcomp_topics()
        self.add_halrcomp_topic(self.name)

    def remove_pins(self):
        self.pinsbyhandle = {}

    def __getitem__(self, k):
        return self.pinsbyname[k].get()

    def __setitem__(self, k, v):
        self.pinsbyname[k].set(v)


def component(name):
    return RemoteComponent(name)
