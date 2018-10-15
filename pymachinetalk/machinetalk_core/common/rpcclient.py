# coding=utf-8
import zmq
import threading
import uuid
from google.protobuf.message import DecodeError
from fysom import Fysom

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class RpcClient(object):
    def __init__(self, debuglevel=0, debugname='RPC Client'):
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
        # pipe for outgoing messages
        self._pipe = context.socket(zmq.PUSH)
        self._pipe_uri = b'inproc://pipe-%s' % str(uuid.uuid4()).encode()
        self._pipe.bind(self._pipe_uri)
        self._thread = None  # socket worker tread
        self._tx_lock = threading.Lock()  # lock for outgoing messages

        # Socket
        self.socket_uri = ''
        # more efficient to reuse protobuf messages
        self._socket_rx = Container()
        self._socket_tx = Container()

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
                    {'name': 'any_msg_received', 'src': 'trying', 'dst': 'up'},
                    {'name': 'heartbeat_timeout', 'src': 'trying', 'dst': 'trying'},
                    {'name': 'heartbeat_tick', 'src': 'trying', 'dst': 'trying'},
                    {'name': 'any_msg_sent', 'src': 'trying', 'dst': 'trying'},
                    {'name': 'stop', 'src': 'trying', 'dst': 'down'},
                    {'name': 'heartbeat_timeout', 'src': 'up', 'dst': 'trying'},
                    {'name': 'heartbeat_tick', 'src': 'up', 'dst': 'up'},
                    {'name': 'any_msg_received', 'src': 'up', 'dst': 'up'},
                    {'name': 'any_msg_sent', 'src': 'up', 'dst': 'up'},
                    {'name': 'stop', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterstart = self._on_fsm_start
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onafterany_msg_received = self._on_fsm_any_msg_received
        self._fsm.onafterheartbeat_timeout = self._on_fsm_heartbeat_timeout
        self._fsm.onafterheartbeat_tick = self._on_fsm_heartbeat_tick
        self._fsm.onafterany_msg_sent = self._on_fsm_any_msg_sent
        self._fsm.onafterstop = self._on_fsm_stop
        self._fsm.onup = self._on_fsm_up

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
        self.reset_heartbeat_liveness()
        self.send_ping()
        self.start_heartbeat_timer()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_any_msg_received(self, _):
        if self.debuglevel > 0:
            print('[%s]: event ANY MSG RECEIVED' % self.debugname)
        self.reset_heartbeat_liveness()
        self.reset_heartbeat_timer()
        return True

    def _on_fsm_heartbeat_timeout(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HEARTBEAT TIMEOUT' % self.debugname)
        self.stop_socket()
        self.start_socket()
        self.reset_heartbeat_liveness()
        self.send_ping()
        return True

    def _on_fsm_heartbeat_tick(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HEARTBEAT TICK' % self.debugname)
        self.send_ping()
        return True

    def _on_fsm_any_msg_sent(self, _):
        if self.debuglevel > 0:
            print('[%s]: event ANY MSG SENT' % self.debugname)
        self.reset_heartbeat_timer()
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

    def _socket_worker(self, context, uri):
        poll = zmq.Poller()
        socket = context.socket(zmq.DEALER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(uri)
        poll.register(socket, zmq.POLLIN)

        shutdown = context.socket(zmq.PULL)
        shutdown.connect(self._shutdown_uri)
        poll.register(shutdown, zmq.POLLIN)
        pipe = context.socket(zmq.PULL)
        pipe.connect(self._pipe_uri)
        poll.register(pipe, zmq.POLLIN)

        while True:
            s = dict(poll.poll())
            if shutdown in s:
                shutdown.recv()
                return  # shutdown signal
            if pipe in s:
                socket.send(pipe.recv(), zmq.NOBLOCK)
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
            elif self._fsm.isstate('trying'):
                self._fsm.heartbeat_timeout()
            return

        if self._fsm.isstate('up'):
            self._fsm.heartbeat_tick()
        elif self._fsm.isstate('trying'):
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
        msg = socket.recv()

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
        if self._fsm.isstate('trying'):
            self._fsm.any_msg_received()
        elif self._fsm.isstate('up'):
            self._fsm.any_msg_received()

        # react to ping acknowledge message
        if rx.type == pb.MT_PING_ACKNOWLEDGE:
            return  # ping acknowledge is uninteresting

        for cb in self.on_socket_message_received:
            cb(rx)

    def send_socket_message(self, msg_type, tx):
        with self._tx_lock:
            tx.type = msg_type
            if self.debuglevel > 0:
                print('[%s] sending message: %s' % (self.debugname, msg_type))
                if self.debuglevel > 1:
                    print(str(tx))

            self._pipe.send(tx.SerializeToString())
            tx.Clear()

        if self._fsm.isstate('up'):
            self._fsm.any_msg_sent()
        elif self._fsm.isstate('trying'):
            self._fsm.any_msg_sent()

    def send_ping(self):
        tx = self._socket_tx
        self.send_socket_message(pb.MT_PING, tx)
