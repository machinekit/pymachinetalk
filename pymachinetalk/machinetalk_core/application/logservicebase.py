# coding=utf-8
from fysom import Fysom
from ..common.publish import Publish

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class LogServiceBase(object):
    def __init__(self, debuglevel=0, debugname='Log Service Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Log
        self._log_channel = Publish(debuglevel=debuglevel)
        self._log_channel.debugname = '%s - %s' % (self.debugname, 'log')
        # more efficient to reuse protobuf messages
        self._log_tx = Container()

        # callbacks
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'up'},
                    {'name': 'disconnect', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.onup = self._on_fsm_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect

    def _on_fsm_down(self, _):
        if self.debuglevel > 0:
            print('[%s]: state DOWN' % self.debugname)
        for cb in self.on_state_changed:
            cb('down')
        return True

    def _on_fsm_connect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event CONNECT' % self.debugname)
        self.start_log_channel()
        return True

    def _on_fsm_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP' % self.debugname)
        for cb in self.on_state_changed:
            cb('up')
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_log_channel()
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

    @property
    def log_uri(self):
        return self._log_channel.socket_uri

    @log_uri.setter
    def log_uri(self, value):
        self._log_channel.socket_uri = value

    @property
    def log_port(self):
        return self._log_channel.socket_port

    @property
    def log_dsn(self):
        return self._log_channel.socket_dsn

    def start(self):
        if self._fsm.isstate('down'):
            self._fsm.connect()

    def stop(self):
        if self._fsm.isstate('up'):
            self._fsm.disconnect()

    def add_log_topic(self, name):
        self._log_channel.add_socket_topic(name)

    def remove_log_topic(self, name):
        self._log_channel.remove_socket_topic(name)

    def clear_log_topics(self):
        self._log_channel.clear_socket_topics()

    def start_log_channel(self):
        self._log_channel.start()

    def stop_log_channel(self):
        self._log_channel.stop()

    def send_log_message(self, identity, msg_type, tx):
        self._log_channel.send_socket_message(identity, msg_type, tx)

    def send_log_message(self, identity, tx):
        ids = [identity]
        for receiver in ids:
            self.send_log_message(receiver, pb.MT_LOG_MESSAGE, tx)
