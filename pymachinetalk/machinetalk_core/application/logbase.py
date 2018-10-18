# coding=utf-8
from fysom import Fysom
from ..common.simplesubscribe import SimpleSubscribe

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class LogBase(object):
    def __init__(self, debuglevel=0, debugname='Log Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Log
        self._log_channel = SimpleSubscribe(debuglevel=debuglevel)
        self._log_channel.debugname = '%s - %s' % (self.debugname, 'log')
        self._log_channel.on_state_changed.append(self._log_channel_state_changed)
        self._log_channel.on_socket_message_received.append(
            self._log_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._log_rx = Container()

        # callbacks
        self.on_log_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'trying'},
                    {'name': 'log_up', 'src': 'trying', 'dst': 'up'},
                    {'name': 'disconnect', 'src': 'trying', 'dst': 'down'},
                    {'name': 'disconnect', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onafterlog_up = self._on_fsm_log_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect
        self._fsm.onup = self._on_fsm_up
        self._fsm.onleaveup = self._on_fsm_up_exit

    def _on_fsm_down(self, _):
        if self.debuglevel > 0:
            print('[%s]: state DOWN' % self.debugname)
        for cb in self.on_state_changed:
            cb('down')
        return True

    def _on_fsm_connect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event CONNECT' % self.debugname)
        self.update_topics()
        self.start_log_channel()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_log_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event LOG UP' % self.debugname)
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_log_channel()
        return True

    def _on_fsm_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP entry' % self.debugname)
        self.set_connected()
        if self.debuglevel > 0:
            print('[%s]: state UP' % self.debugname)
        for cb in self.on_state_changed:
            cb('up')
        return True

    def _on_fsm_up_exit(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP exit' % self.debugname)
        self.clear_connected()
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

    def update_topics(self):
        print('WARNING: slot update topics unimplemented')

    def set_connected(self):
        print('WARNING: slot set connected unimplemented')

    def clear_connected(self):
        print('WARNING: slot clear connected unimplemented')

    def start(self):
        if self._fsm.isstate('down'):
            self._fsm.connect()

    def stop(self):
        if self._fsm.isstate('trying'):
            self._fsm.disconnect()
        elif self._fsm.isstate('up'):
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

    # process all messages received on log
    def _log_channel_message_received(self, identity, rx):

        # react to log message message
        if rx.type == pb.MT_LOG_MESSAGE:
            self.log_message_received(identity, rx)

        for cb in self.on_log_message_received:
            cb(identity, rx)

    def log_message_received(self, identity, rx):
        print('SLOT log message unimplemented')

    def _log_channel_state_changed(self, state):

        if state == 'up':
            if self._fsm.isstate('trying'):
                self._fsm.log_up()
