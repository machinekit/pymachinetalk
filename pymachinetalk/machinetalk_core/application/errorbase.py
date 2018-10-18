# coding=utf-8
from fysom import Fysom
from ..application.errorsubscribe import ErrorSubscribe

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class ErrorBase(object):
    def __init__(self, debuglevel=0, debugname='Error Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Error
        self._error_channel = ErrorSubscribe(debuglevel=debuglevel)
        self._error_channel.debugname = '%s - %s' % (self.debugname, 'error')
        self._error_channel.on_state_changed.append(self._error_channel_state_changed)
        self._error_channel.on_socket_message_received.append(
            self._error_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._error_rx = Container()

        # callbacks
        self.on_error_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'trying'},
                    {'name': 'error_up', 'src': 'trying', 'dst': 'up'},
                    {'name': 'disconnect', 'src': 'trying', 'dst': 'down'},
                    {'name': 'error_trying', 'src': 'up', 'dst': 'trying'},
                    {'name': 'disconnect', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onaftererror_up = self._on_fsm_error_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect
        self._fsm.onup = self._on_fsm_up
        self._fsm.onaftererror_trying = self._on_fsm_error_trying
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
        self.start_error_channel()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_error_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event ERROR UP' % self.debugname)
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_error_channel()
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

    def _on_fsm_error_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: event ERROR TRYING' % self.debugname)
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
    def error_uri(self):
        return self._error_channel.socket_uri

    @error_uri.setter
    def error_uri(self, value):
        self._error_channel.socket_uri = value

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

    def add_error_topic(self, name):
        self._error_channel.add_socket_topic(name)

    def remove_error_topic(self, name):
        self._error_channel.remove_socket_topic(name)

    def clear_error_topics(self):
        self._error_channel.clear_socket_topics()

    def start_error_channel(self):
        self._error_channel.start()

    def stop_error_channel(self):
        self._error_channel.stop()

    # process all messages received on error
    def _error_channel_message_received(self, identity, rx):

        # react to emc nml error message
        if rx.type == pb.MT_EMC_NML_ERROR:
            self.emc_nml_error_received(identity, rx)

        # react to emc nml text message
        elif rx.type == pb.MT_EMC_NML_TEXT:
            self.emc_nml_text_received(identity, rx)

        # react to emc nml display message
        elif rx.type == pb.MT_EMC_NML_DISPLAY:
            self.emc_nml_display_received(identity, rx)

        # react to emc operator text message
        elif rx.type == pb.MT_EMC_OPERATOR_TEXT:
            self.emc_operator_text_received(identity, rx)

        # react to emc operator error message
        elif rx.type == pb.MT_EMC_OPERATOR_ERROR:
            self.emc_operator_error_received(identity, rx)

        # react to emc operator display message
        elif rx.type == pb.MT_EMC_OPERATOR_DISPLAY:
            self.emc_operator_display_received(identity, rx)

        for cb in self.on_error_message_received:
            cb(identity, rx)

    def emc_nml_error_received(self, identity, rx):
        print('SLOT emc nml error unimplemented')

    def emc_nml_text_received(self, identity, rx):
        print('SLOT emc nml text unimplemented')

    def emc_nml_display_received(self, identity, rx):
        print('SLOT emc nml display unimplemented')

    def emc_operator_text_received(self, identity, rx):
        print('SLOT emc operator text unimplemented')

    def emc_operator_error_received(self, identity, rx):
        print('SLOT emc operator error unimplemented')

    def emc_operator_display_received(self, identity, rx):
        print('SLOT emc operator display unimplemented')

    def _error_channel_state_changed(self, state):

        if state == 'trying':
            if self._fsm.isstate('up'):
                self._fsm.error_trying()

        elif state == 'up':
            if self._fsm.isstate('trying'):
                self._fsm.error_up()
