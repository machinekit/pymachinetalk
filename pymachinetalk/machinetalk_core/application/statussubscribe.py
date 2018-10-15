# coding=utf-8
import zmq
import threading
import uuid
from google.protobuf.message import DecodeError
from fysom import Fysom

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class StatusSubscribe(object):
    def __init__(self, debuglevel=0, debugname='Status Subscribe'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []
        # ZeroMQ
        context = zmq.Context()
        context.linger = 0
        self._context = context
        # pipe to signalize a shutdown
        self._shutdown = context.socket(zmq.PUSH)
        self._shutdown_uri = b'inproc://shutdown-%s' % str(uuid.uuid4()).encode()
        self._shutdown.bind(self._shutdown_uri)
        self._thread = None  # socket worker tread
        self._tx_lock = threading.Lock()  # lock for outgoing messages

        # Socket
        self.socket_uri = ''
        self._socket_topics = set()
        # more efficient to reuse protobuf messages
        self._socket_rx = Container()

        # Heartbeat
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_interval = 2500
        self._heartbeat_timer = None
        self._heartbeat_active = False
        self._heartbeat_liveness = 0
        self._heartbeat_reset_liveness = 5

        # callbacks
        self.on_socket_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'start', 'src': 'down', 'dst': 'trying'},
                    {'name': 'full_update_received', 'src': 'trying', 'dst': 'up'},
                    {'name': 'stop', 'src': 'trying', 'dst': 'down'},
                    {'name': 'heartbeat_timeout', 'src': 'up', 'dst': 'trying'},
                    {'name': 'heartbeat_tick', 'src': 'up', 'dst': 'up'},
                    {'name': 'any_msg_received', 'src': 'up', 'dst': 'up'},
                    {'name': 'stop', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterstart = self._on_fsm_start
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onafterfull_update_received = self._on_fsm_full_update_received
        self._fsm.onafterstop = self._on_fsm_stop
        self._fsm.onup = self._on_fsm_up
        self._fsm.onafterheartbeat_timeout = self._on_fsm_heartbeat_timeout
        self._fsm.onafterheartbeat_tick = self._on_fsm_heartbeat_tick
        self._fsm.onafterany_msg_received = self._on_fsm_any_msg_received

    def _on_fsm_down(self, _):
        if self.debuglevel > 0:
            print('[%s]: state DOWN' % self.debugname)
        for cb in self.on_state_changed:
            cb('down')
        return True

    def _on_fsm_start(self, _):
        if self.debuglevel > 0:
            print('[%s]: event START' % self.debugname)
        self.start_socket()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_full_update_received(self, _):
        if self.debuglevel > 0:
            print('[%s]: event FULL UPDATE RECEIVED' % self.debugname)
        self.reset_heartbeat_liveness()
        self.start_heartbeat_timer()
        return True

    def _on_fsm_stop(self, _):
        if self.debuglevel > 0:
            print('[%s]: event STOP' % self.debugname)
        self.stop_heartbeat_timer()
        self.stop_socket()
        return True

    def _on_fsm_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP' % self.debugname)
        for cb in self.on_state_changed:
            cb('up')
        return True

    def _on_fsm_heartbeat_timeout(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HEARTBEAT TIMEOUT' % self.debugname)
        self.stop_heartbeat_timer()
        self.stop_socket()
        self.start_socket()
        return True

    def _on_fsm_heartbeat_tick(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HEARTBEAT TICK' % self.debugname)
        self.reset_heartbeat_timer()
        return True

    def _on_fsm_any_msg_received(self, _):
        if self.debuglevel > 0:
            print('[%s]: event ANY MSG RECEIVED' % self.debugname)
        self.reset_heartbeat_liveness()
        self.reset_heartbeat_timer()
        return True

    @property
    def error_string(self):
        return self._error_string

    @error_string.setter
    def error_string(self, string):
        if self._error_string is string:
            return
        self._error_string = string
        for cb in self.on_error_string_changed:
            cb(string)

    def start(self):
        if self._fsm.isstate('down'):
            self._fsm.start()

    def stop(self):
        if self._fsm.isstate('trying'):
            self._fsm.stop()
        elif self._fsm.isstate('up'):
            self._fsm.stop()

    def add_socket_topic(self, name):
        self._socket_topics.add(name)

    def remove_socket_topic(self, name):
        self._socket_topics.remove(name)

    def clear_socket_topics(self):
        self._socket_topics.clear()

    def _socket_worker(self, context, uri):
        poll = zmq.Poller()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(uri)
        poll.register(socket, zmq.POLLIN)
        # subscribe is always connected to socket creation
        for topic in self._socket_topics:
            socket.setsockopt(zmq.SUBSCRIBE, topic.encode())

        shutdown = context.socket(zmq.PULL)
        shutdown.connect(self._shutdown_uri)
        poll.register(shutdown, zmq.POLLIN)

        while True:
            s = dict(poll.poll())
            if shutdown in s:
                shutdown.recv()
                return  # shutdown signal
            if socket in s:
                self._socket_message_received(socket)

    def start_socket(self):
        self._thread = threading.Thread(
            target=self._socket_worker, args=(self._context, self.socket_uri)
        )
        self._thread.start()

    def stop_socket(self):
        self._shutdown.send(b' ')  # trigger socket thread shutdown
        self._thread = None

    def _heartbeat_timer_tick(self):
        with self._heartbeat_lock:
            self._heartbeat_timer = None  # timer is dead on tick

        if self.debuglevel > 0:
            print('[%s] heartbeat timer tick' % self.debugname)

        self._heartbeat_liveness -= 1
        if self._heartbeat_liveness == 0:
            if self._fsm.isstate('up'):
                self._fsm.heartbeat_timeout()
            return

        if self._fsm.isstate('up'):
            self._fsm.heartbeat_tick()

    def reset_heartbeat_liveness(self):
        self._heartbeat_liveness = self._heartbeat_reset_liveness

    def reset_heartbeat_timer(self):
        if not self._heartbeat_active:
            return

        self._heartbeat_lock.acquire()
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None

        if self._heartbeat_interval > 0:
            self._heartbeat_timer = threading.Timer(
                self._heartbeat_interval / 1000.0, self._heartbeat_timer_tick
            )
            self._heartbeat_timer.start()
        self._heartbeat_lock.release()
        if self.debuglevel > 0:
            print('[%s] heartbeat timer reset' % self.debugname)

    def start_heartbeat_timer(self):
        self._heartbeat_active = True
        self.reset_heartbeat_timer()

    def stop_heartbeat_timer(self):
        self._heartbeat_active = False
        self._heartbeat_lock.acquire()
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        self._heartbeat_lock.release()

    # process all messages received on socket
    def _socket_message_received(self, socket):
        (identity, msg) = socket.recv_multipart()  # identity is topic

        try:
            self._socket_rx.ParseFromString(msg)
        except DecodeError as e:
            note = 'Protobuf Decode Error: ' + str(e)
            print(note)  # TODO: decode error
            return

        if self.debuglevel > 0:
            print('[%s] received message' % self.debugname)
            if self.debuglevel > 1:
                print(self._socket_rx)
        rx = self._socket_rx

        # react to any incoming message
        if self._fsm.isstate('up'):
            self._fsm.any_msg_received()

        # react to ping message
        if rx.type == pb.MT_PING:
            return  # ping is uninteresting

        # react to emcstat full update message
        elif rx.type == pb.MT_EMCSTAT_FULL_UPDATE:
            if rx.HasField('pparams'):
                interval = rx.pparams.keepalive_timer
                self._heartbeat_interval = interval
            if self._fsm.isstate('trying'):
                self._fsm.full_update_received()

        for cb in self.on_socket_message_received:
            cb(identity, rx)
