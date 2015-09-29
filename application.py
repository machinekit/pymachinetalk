import time
import uuid
import platform

import zmq.green as zmq
import gevent
import gevent.event
from gevent import greenlet

# protobuf
from message_pb2 import Container
from types_pb2 import *
from status_pb2 import *


class ApplicationStatus():
    def __init__(self, debug=False):
        self.threads = []
        self.debug = debug
        self.is_ready = False

        self.synced = False
        self.connected = False
        self.state = 'Disconnected'
        self.status_state = 'Down'
        self.channels = set(['motion', 'config', 'io', 'task', 'interp'])
        self.running = False

        # status containers, also used to expose data
        self.config = EmcStatusConfig()
        self.io = EmcStatusIo()
        self.config = EmcStatusConfig()
        self.motion = EmcStatusMotion()
        self.task = EmcStatusTask()
        self.interp = EmcStatusInterp()

        self.status_uri = ''
        self.status_period = 0
        self.status_timestamp = 0
        self.subscriptions = set()
        self.synced_channels = set()

        # more efficient to reuse a protobuf message
        self.rx = Container()

        # ZeroMQ
        context = zmq.Context()
        context.linger = 0
        self.context = context
        self.status_socket = self.context.socket(zmq.SUB)
        self.sockets_connected = False

    def status_worker(self):
        try:
            while True:
                (topic, msg) = self.status_socket.recv_multipart()
                self.rx.ParseFromString(msg)

                if self.debug:
                    print('[status] received message: %s' % topic)
                    print(self.rx)

                if self.rx.type == MT_EMCSTAT_FULL_UPDATE \
                   or self.rx.type == MT_EMCSTAT_INCREMENTAL_UPDATE:

                    if topic == 'motion' and self.rx.HasField('emc_status_motion'):
                        self.update_motion(self.rx.emc_status_motion)
                        if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                            self.update_sync('motion')

                    if topic == 'config' and self.rx.HasField('emc_status_config'):
                        self.update_config(self.rx.emc_status_config)
                        if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                            self.update_sync('config')

                    if topic == 'io' and self.rx.HasField('emc_status_io'):
                        self.update_io(self.rx.emc_status_io)
                        if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                            self.update_sync('io')

                    if topic == 'task' and self.rx.HasField('emc_status_task'):
                        self.update_task(self.rx.emc_status_task)
                        if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                            self.update_sync('task')

                    if topic == 'interp' and self.rx.HasField('emc_status_interp'):
                        self.update_interp(self.rx.emc_status_interp)
                        if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                            self.update_sync('interp')

                    if self.rx.type == MT_EMCSTAT_FULL_UPDATE:
                        if not self.status_state == 'Up':
                            self.status_state = 'Up'
                            self.update_state('Connected')

                        if self.rx.HasField('pparams'):
                            interval = self.rx.pparams.keepalive_timer
                            self.status_period = interval * 2  # wait double the hearbeat intverval
                            self.refresh_status_heartbeat()

                elif self.rx.type == MT_PING:
                    if self.status_state == 'Up':
                        self.refresh_status_heartbeat()
                    else:
                        self.update_state('Connecting')
                        self.unsubscribe()  # clean up previous subscription
                        self.subscribe()  # trigger a fresh subscribe -> full update
                else:
                    print('[status] received unrecognized message type')

        except greenlet.GreenletExit:
            pass

    def update_motion(self, data):
        self.motion.MergeFrom(data)

    def update_config(self, data):
        self.config.MergeFrom(data)

    def update_io(self, data):
        self.io.MergeFrom(data)

    def update_task(self, data):
        self.task.MergeFrom(data)

    def update_interp(self, data):
        self.interp.MergeFrom(data)

    def update_sync(self, channel):
        self.synced_channels.add(channel)

        if self.synced_channels == self.channels:
            self.synced = True

    def clear_sync(self):
        self.synced = False
        self.synced_channels.clear()

    def status_timer_tick(self):
        try:
            while True:
                period = self.status_period
                if period > 0:
                    timestamp = time.time() * 1000
                    timediff = timestamp - self.status_timestamp
                    if timediff > period:
                        self.status_state = 'Down'
                        self.update_state('Timeout')
                        self.status_period = 0  # will be refreshed by full update
                gevent.sleep(0.1)
        except greenlet.GreenletExit:
            pass

    def refresh_status_heartbeat(self):
        self.status_timestamp = time.time() * 1000

    def update_state(self, state):
        if state != self.state:
            self.state = state
            if state == 'Connected':
                self.connected = True
                print('[status] connected')
            elif self.connected:
                self.connected = False
                self.clear_sync()
                # stop heartbeat ?
                if not state == 'Timeout':  # clear in case we have no timeout
                    self.motion.Clear()
                    self.config.Clear()
                    self.io.Clear()
                    self.task.Clear()
                    self.interp.Clear()
                print('[status] disconnected')

    def subscribe(self):
        self.status_state = 'Trying'

        for channel in self.channels:
            self.status_socket.setsockopt(zmq.SUBSCRIBE, channel)
            self.subscriptions.add(channel)

    def unsubscribe(self):
        self.status_state = 'Down'

        for subscription in self.subscriptions:
            self.status_socket.setsockopt(zmq.UNSUBSCRIBE, subscription)
            if subscription == 'motion':
                self.motion.Clear()
            elif subscription == 'config':
                self.config.Clear()
            elif subscription == 'io':
                self.io.Clear()
            elif subscription == 'task':
                self.task.Clear()
            elif subscription == 'interp':
                self.interp.Clear()

        self.subscriptions.clear()

    def update_running(self):
        running = (self.task.task_mode == EMC_TASK_MODE_AUTO \
                   or self.task.task_mode == EMC_TASK_MODE_MDI) \
                   and self.interp.interp_state == EMC_TASK_INTERP_IDLE

        self.running = running

    def start(self):
        self.status_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            self.threads.append(gevent.spawn(self.status_worker))
            self.threads.append(gevent.spawn(self.status_timer_tick))
            self.subscribe()

    def stop(self):
        self.is_ready = False
        gevent.killall(self.threads, block=True)
        self.threads = []
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        if self.connected:
            self.unsubscribe()
        self.disconnect_sockets()

    def connect_sockets(self):
        self.sockets_connected = True
        self.status_socket.connect(self.status_uri)

        return True

    def disconnect_sockets(self):
        if self.sockets_connected:
            self.status_socket.disconnect(self.status_uri)
            self.sockets_connected = False

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()


class ApplicationCommand():
    def __init__(self, debug=False):
        self.threads = []
        self.debug = debug
        self.is_ready = False

        self.connected = False
        self.state = 'Disconnected'
        self.command_state = 'Down'

        self.command_uri = ''
        self.heartbeat_period = 3000
        self.ping_error_count = 0
        self.ping_error_threshold = 2

        # more efficient to reuse a protobuf message
        self.rx = Container()
        self.tx = Container()

        # ZeroMQ
        client_id = '%s-%s' % (platform.node(), uuid.uuid4())  # must be unique
        context = zmq.Context()
        context.linger = 0
        self.context = context
        self.command_socket = self.context.socket(zmq.DEALER)
        self.command_socket.setsockopt(zmq.LINGER, 0)
        self.command_socket.setsockopt(zmq.IDENTITY, client_id)
        self.sockets_connected = False

    def send_command_msg(self, msg_type):
        self.tx.type = msg_type
        if self.debug:
            print('[command] sending message: %s' % msg_type)
            print(str(self.tx))
        self.command_socket.send(self.tx.SerializeToString(), zmq.NOBLOCK)
        self.tx.Clear()

    def command_worker(self):
        try:
            while True:
                msg = self.command_socket.recv()
                self.rx.ParseFromString(msg)
                if self.debug:
                    print('[command] received message')
                    print(self.rx)

                if self.rx.type == MT_PING_ACKNOWLEDGE:
                    self.ping_error_count = 0

                    if not self.command_state == 'Up':
                        self.command_state = 'Up'
                        self.update_state('Connected')

                elif self.rx.type == MT_ERROR:
                    self.update_error('Service', self.rx.note)
                    # should we disconnect here?

                else:
                    print('[command] received unsupported message')

        except greenlet.GreenletExit:
            pass  # gracefully dying

    def start(self):
        self.command_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            self.ping_error_count = 0  # reset heartbeat
            self.threads.append(gevent.spawn(self.command_worker))
            self.threads.append(gevent.spawn(self.heartbeat_timer_tick))

    def stop(self):
        self.is_ready = False
        gevent.killall(self.threads, block=True)
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        # stop heartbeat
        self.disconnect_sockets()

    def connect_sockets(self):
        self.sockets_connected = True
        self.command_socket.connect(self.command_uri)

        return True

    def disconnect_sockets(self):
        if self.sockets_connected:
            self.command_socket.disconnect(self.command_uri)
            self.sockets_connected = False

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()

    def update_state(self, state):
        if state != self.state:
            self.state = state
            if state == 'Connected':
                self.connected = True
                print('[command] connected')
            elif self.connected:
                self.connected = False
                print('[command] disconnected')

    def update_error(self, error, description):
        print('[command] error: %s %s' % (error, description))

    def heartbeat_timer_tick(self):
        try:
            while True:
                self.ping_error_count += 1  # increase error count by one, threshold 2 means two timer ticks

                if self.ping_error_count > self.ping_error_threshold:
                    self.command_state = 'Trying'
                    self.update_state('Timeout')

                self.send_command_msg(MT_PING)

                if self.heartbeat_period > 0:
                    gevent.sleep(self.heartbeat_period / 1000)
                else:
                    return
        except greenlet.GreenletExit:
            pass

