#!/usr/bin/python

import sys
import os
import signal
import gobject
from machinekit import config
from dns_sd import ServiceDiscovery

if sys.version_info >= (3, 0):
    import configparser
else:
    import ConfigParser as configparser

import time
import zmq
import threading
import platform
import glib

# protobuf
from message_pb2 import Container
from types_pb2 import *


def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.iteritems())
    enums['reverse_mapping'] = reverse
    return type('Enum', (), enums)


class HalPin():
    def __init__(self):
        self.name = ''
        self.pintype = HAL_BIT
        self.direction = HAL_IN
        self.synced = False
        self.value = None
        self.synced = False
        self.handle = 0
        self.parent = None

    def set(self, value):
        self.value = value
        self.synced = False
        if self.parent:
            self.parent.pin_change(self)

    def get(self):
        return self.value


class HalRemoteComponent():
    def __init__(self, context, name, debug=True):
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
        self.halrcmdSocket = None
        self.halrcompSocekt = None
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
        self.context = context
        self.halrcmdSocket = self.context.socket(zmq.DEALER)
        self.halrcmdSocket.setsockopt(zmq.LINGER, 0)
        self.halrcmdSocket.setsockopt(zmq.IDENTITY, client_id)
        self.halrcomp_socket = self.context.socket(zmq.SUB)

        zmq_fd = self.halrcmdSocket.getsockopt(zmq.FD)
        gobject.io_add_watch(zmq_fd, gobject.IO_IN, self.halrcmd_callback, self.halrcmdSocket)
        zmq_fd2 = self.halrcomp_socket.getsockopt(zmq.FD)
        gobject.io_add_watch(zmq_fd2, gobject.IO_IN, self.halrcomp_callback, self.halrcomp_socket)

    def halrcmd_callback(self, fd, condition, socket):
        del fd
        del condition
        print('halrcmd callback')
        while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
            msg = socket.recv()
            self.rx.ParseFromString(msg)
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
                print('unsupported message')
        return True

    def halrcomp_callback(self, fd, condition, socket):
        del fd
        del condition
        while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
            (topic, msg) = socket.recv_multipart()
            self.rx.ParseFromString(msg)

            if topic != self.name:  # ignore uninteresting messages
                continue

            print("topic %s" % topic)
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
            #self.send_cmd(MT_PING, self.tx)

    def stop(self):
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        if self.connected:
            self.unsubscribe()
        self.stop_halrcmd_heartbeat()
        self.disconnect_sockets()

    def connect_sockets(self):
        self.halrcmdSocket.connect(self.halrcmdUri)
        self.halrcomp_socket.connect(self.halrcompUri)

        return True

    def disconnect_sockets(self):
        self.halrcmdSocket.disconnect()
        self.halrcomp_socket.disconnect()

    def start_halrcmd_heartbeat(self):
        timeout = self.period
        if not self.halrcmd_timer_id:
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
        print("sending message:")
        self.tx.type = msg_type
        print(str(self.tx))
        self.halrcmdSocket.send(self.tx.SerializeToString())
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
            else:
                self.connected = False

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
            print("pin change %s" % pin.name)

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
            print('bind: %s' % self.name)
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


shutdown = False


def _exitHandler(signum, frame):
    del signum
    del frame
    global shutdown
    shutdown = True
    print("handled")


# register exit signal handlers
def register_exit_handler():
    signal.signal(signal.SIGINT, _exitHandler)
    signal.signal(signal.SIGTERM, _exitHandler)


def check_exit():
    global shutdown
    return shutdown

haltalkclient = None
halrcmdReady = False
halrcompReady = False


def halrcmd_discovered(name, dsn):
    global halrcmdReady
    print("discovered %s %s" % (name, dsn))
    haltalkclient.halrcmdUri = dsn
    halrcmdReady = True
    if halrcompReady:
        haltalkclient.start()
        start_timer()


def halrcomp_discovered(name, dsn):
    global halrcompReady
    print("discovered %s %s" % (name, dsn))
    haltalkclient.halrcompUri = dsn
    halrcompReady = True
    if halrcmdReady:
        haltalkclient.start()
        start_timer()


def start_timer():
    glib.timeout_add(1000, toggle_pin)


def toggle_pin():
    haltalkclient['coolant'] = not haltalkclient['coolant']
    return True


def main():
    mkconfig = config.Config()
    mkini = os.getenv("MACHINEKIT_INI")
    if mkini is None:
        mkini = mkconfig.MACHINEKIT_INI
    if not os.path.isfile(mkini):
        sys.stderr.write("MACHINEKIT_INI " + mkini + " does not exist\n")
        sys.exit(1)

    mki = configparser.ConfigParser()
    mki.read(mkini)
    uuid = mki.get("MACHINEKIT", "MKUUID")
    # remote = mki.getint("MACHINEKIT", "REMOTE")

    #register_exit_handler()
    global haltalkclient
    context = zmq.Context()
    context.linger = 0
    haltalkclient = HalRemoteComponent(context=context, name='test')
    haltalkclient.newpin("coolant-iocontrol", HAL_BIT, HAL_IN)
    haltalkclient.newpin("coolant", HAL_BIT, HAL_OUT)
    haltalkclient.ready()

    halrcmd_sd = ServiceDiscovery(service_type="_halrcmd._sub._machinekit._tcp", uuid=uuid)
    halrcmd_sd.discovered_callback = halrcmd_discovered
    halrcmd_sd.start()
    #halrcmd_sd.disappered_callback = disappeared

    harcomp_sd = ServiceDiscovery(service_type="_halrcomp._sub._machinekit._tcp", uuid=uuid)
    harcomp_sd.discovered_callback = halrcomp_discovered
    harcomp_sd.start()

    loop = gobject.MainLoop()
    try:
        loop.run()
    except:
        loop.quit()

    # while dns_sd.running and not check_exit():
    #     time.sleep(1)

    print("stopping threads")
    if haltalkclient is not None:
        haltalkclient.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
