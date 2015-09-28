import os
import gobject

import zmq.green as zmq
import threading
import platform
import glib

import gevent

# protobuf
from message_pb2 import Container
from types_pb2 import *


class HalPin():
    def __init__(self):
        self.name = ''
        self.pintype = HAL_BIT
        self.direction = HAL_IN
        self.synced = False
        self.value = None
        self.synced = False
        self.handle = 0  # stores handle received on bind
        self.parent = None

    def set(self, value):
        self.value = value
        self.synced = False
        if self.parent:
            self.parent.pin_change(self)

    def get(self):
        return self.value


class HalRemoteComponent():
    def __init__(self, name, debug=False):
        self.shutdown = threading.Event()
        self.running = False
        self.debug = debug

        self.name = name
        self.pinsbyname = {}
        self.pinsbyhandle = {}
        self.synced = False
        self.is_ready = False
        self.no_create = False

        self.halrcmdUri = ''
        self.halrcompUri = ''
        self.halrcmd_socket = None
        self.halrcomp_socket = None
        self.connected = False
        self.period = 3000
        self.ping_outstanding = False
        self.state = 'Disconnected'
        self.halrcmd_state = 'Down'
        self.halrcomp_state = 'Down'
        self.halrcmd_timer_id = None
        self.halrcomp_timer_id = None

        # more efficient to reuse a protobuf message
        self.tx = Container()
        self.rx = Container()

        client_id = '%s-%s' % (platform.node(), os.getpid())
        context = zmq.Context()
        context.linger = 0
        self.context = context
        self.halrcmd_socket = self.context.socket(zmq.DEALER)
        self.halrcmd_socket.setsockopt(zmq.LINGER, 0)
        self.halrcmd_socket.setsockopt(zmq.IDENTITY, client_id)
        self.halrcomp_socket = self.context.socket(zmq.SUB)

        zmq_fd = self.halrcmd_socket.getsockopt(zmq.FD)
        gobject.io_add_watch(zmq_fd, gobject.IO_IN, self.halrcmd_callback, self.halrcmd_socket)
        zmq_fd2 = self.halrcomp_socket.getsockopt(zmq.FD)
        gobject.io_add_watch(zmq_fd2, gobject.IO_IN, self.halrcomp_callback, self.halrcomp_socket)

    def halrcmd_callback(self, fd, condition, socket):
        del fd
        del condition
        print(bool(socket.getsockopt(zmq.EVENTS) & zmq.POLLOUT))
        while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
            msg = socket.recv()
            self.rx.ParseFromString(msg)
            if self.debug:
                print('[%s] received message on halrcmd:' % self.name)
                print(self.rx)

            if self.rx.type == MT_PING_ACKNOWLEDGE:
                self.ping_outstanding = False
                if self.halrcmd_state == 'Trying':
                    self.update_state('Connecting')
                    self.bind()

            elif self.rx.type == MT_HALRCOMP_BIND_CONFIRM:
                self.halrcmd_state = 'Up'
                self.unsubscribe()  # clear previous subscription
                self.subscribe()  # trigger full update

            elif self.rx.type == MT_HALRCOMP_BIND_REJECT \
            or self.rx.type == MT_HALRCOMP_SET_REJECT:
                self.halrcmd_state = 'Down'
                updateState('Error')
                if self.rx.type == MT_HALRCOMP_BIND_REJECT:
                    self.update_error('Bind', self.rx.note)
                else:
                    self.update_error('Pinchange', self.rx.note)
            else:
                print('Warning: halrcmd receiced unsupported message')

        return True

    def halrcomp_callback(self, fd, condition, socket):
        del fd
        del condition
        while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
            (topic, msg) = socket.recv_multipart()
            self.rx.ParseFromString(msg)

            if topic != self.name:  # ignore uninteresting messages
                continue

            if self.debug:
                print('[%s] received message on halrcmd: topic %s' % (self.name, topic))
                print(self.rx)

            if self.rx.type == MT_HALRCOMP_INCREMENTAL_UPDATE:
                for rpin in self.rx.pin:
                    lpin = self.pinsbyhandle[rpin.handle]
                    self.pin_update(rpin, lpin)
                self.refresh_halrcomp_heartbeat()

            elif self.rx.type == MT_HALRCOMP_FULL_UPDATE:
                comp = self.rx.comp[0]
                for rpin in comp.pin:
                    name = rpin.name.split('.')[1]
                    lpin = self.pinsbyname[name]
                    lpin.handle = rpin.handle
                    self.pinsbyhandle[rpin.handle] = lpin
                    self.pin_update(rpin, lpin)

                    if self.halrcomp_state != 'Up':  # will be executed only once
                        self.halrcomp_state = 'Up'
                        self.update_state('Connected')

                if self.rx.HasField('pparams'):
                    interval = self.rx.pparams.keepalive_timer
                    self.start_halrcomp_heartbeat(interval * 2)  # wait double the hearbeat intverval

            elif self.rx.type == MT_PING:
                if self.halrcomp_state == 'Up':
                    self.refresh_halrcomp_heartbeat()
                else:
                    self.update_state('Connecting')
                    self.unsubscribe()  # clean up previous subscription
                    self.subscribe()  # trigger a fresh subscribe -> full update

            elif self.rx.type == MT_HALRCOMMAND_ERROR:
                self.halrcomp_state = 'Down'
                self.update_state('Error')
                self.update_error('halrcomp', self.rx.note)
        return True

    def start(self):
        self.halrcmd_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            # add pins
            self.start_halrcmd_heartbeat()
            #self.send_cmd(MT_PING, self.tx) cannot send at startupsince this will not work

    def stop(self):
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        if self.connected:
            self.unsubscribe()
        self.stop_halrcmd_heartbeat()
        self.disconnect_sockets()

    def connect_sockets(self):
        self.halrcmd_socket.connect(self.halrcmdUri)
        self.halrcomp_socket.connect(self.halrcompUri)

        return True

    def disconnect_sockets(self):
        self.halrcmd_socket.disconnect(self.halrcmdUri)
        self.halrcomp_socket.disconnect(self.halrcompUri)

    def start_halrcmd_heartbeat(self):
        timeout = self.period
        if not self.halrcmd_timer_id:
            import random
            timeout = 10
        self.halrcmd_timer_id = glib.timeout_add(timeout, self.halrcmd_timer_tick)

    def stop_halrcmd_heartbeat(self):
        self.halrcmd_timer_id = None

    def start_halrcomp_heartbeat(self, interval):
        self.halrcomp_timer_id = None
        if interval > 0:
            self.halrcomp_timer_id = glib.timeout_add(interval, self.halrcomp_timer_tick)

    def stop_halrcomp_heartbeat(self):
        self.halrcomp_timer_id = None

    def send_cmd(self, msg_type):
        self.tx.type = msg_type
        if self.debug:
            print('[%s] sending message: %s' % (self.name, msg_type))
            print(str(self.tx))
        self.halrcmd_socket.send(self.tx.SerializeToString(), zmq.NOBLOCK)
        self.tx.Clear()

    def halrcmd_timer_tick(self):
        if not self.halrcmd_timer_id:
            return False  # remove timer

        if self.ping_outstanding:
            self.halrcmd_state = 'Trying'
            self.update_state('Timeout')

        self.send_cmd(MT_PING)
        self.tx.Clear()
        self.ping_outstanding = True

        self.halrcomp_timer_id = glib.timeout_add(self.period, self.halrcmd_timer_tick) # rearm timer
        return False

    def halrcomp_timer_tick(self):
        pass

    def refresh_halrcomp_heartbeat(self):
        pass # TODO

    def add_remote_component(self, rcomp):
        self.rcomps.append(rcomp)
        rcomp.haltalkclient = self

    def update_state(self, state):
        if state != self.state:
            self.state = state
            if state == 'Connected':
                self.connected = True
                print('[%s] connected' % self.name)
            elif self.connected:
                self.connected = False
                print('[%s] disconnected' % self.name)

    def update_error(self, error, description):
        print('error: %s %s' % (error, description))

    # create a new HAL pin
    def newpin(self, name, pintype, direction):
        pin = HalPin()
        pin.name = name
        pin.pintype = pintype
        pin.direction = direction
        pin.parent = self
        self.pinsbyname[name] = pin
        return pin

    def unsync_pins(self):
        for pin in self.pinsbyname:
            pin.synced = False

    def getpin(self, name):
        return self.pinsbyname[name]

    def ready(self):
        self.is_ready = True

    def pin_update(self, rpin, lpin):
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

        if self.state != 'Connected':  # accept only when connected
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
        p = self.tx.pin.add()
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
        self.send_cmd(MT_HALRCOMP_SET)

    def bind(self):
        c = self.tx.comp.add()
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
        self.send_cmd(MT_HALRCOMP_BIND)

    def subscribe(self):
        self.halrcomp_state = 'Trying'
        self.halrcomp_socket.setsockopt(zmq.SUBSCRIBE, self.name)

    def unsubscribe(self):
        self.halrcomp_state = 'Down'
        self.halrcomp_socket.setsockopt(zmq.UNSUBSCRIBE, self.name)

    def __getitem__(self, k):
        return self.pinsbyname[k].get()

    def __setitem__(self, k, v):
        self.pinsbyname[k].set(v)
