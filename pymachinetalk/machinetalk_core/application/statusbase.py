# coding=utf-8
from fysom import Fysom
from ..application.statussubscribe import StatusSubscribe

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class StatusBase(object):
    def __init__(self, debuglevel=0, debugname='Status Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Status
        self._status_channel = StatusSubscribe(debuglevel=debuglevel)
        self._status_channel.debugname = '%s - %s' % (self.debugname, 'status')
        self._status_channel.on_state_changed.append(self._status_channel_state_changed)
        self._status_channel.on_socket_message_received.append(
            self._status_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._status_rx = Container()

        # callbacks
        self.on_status_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'trying'},
                    {'name': 'status_up', 'src': 'trying', 'dst': 'syncing'},
                    {'name': 'disconnect', 'src': 'trying', 'dst': 'down'},
                    {'name': 'channels_synced', 'src': 'syncing', 'dst': 'up'},
                    {'name': 'status_trying', 'src': 'syncing', 'dst': 'trying'},
                    {'name': 'disconnect', 'src': 'syncing', 'dst': 'down'},
                    {'name': 'status_trying', 'src': 'up', 'dst': 'trying'},
                    {'name': 'disconnect', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onafterstatus_up = self._on_fsm_status_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect
        self._fsm.onsyncing = self._on_fsm_syncing
        self._fsm.onafterchannels_synced = self._on_fsm_channels_synced
        self._fsm.onafterstatus_trying = self._on_fsm_status_trying
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
        self.start_status_channel()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_status_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event STATUS UP' % self.debugname)
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_status_channel()
        return True

    def _on_fsm_syncing(self, _):
        if self.debuglevel > 0:
            print('[%s]: state SYNCING' % self.debugname)
        for cb in self.on_state_changed:
            cb('syncing')
        return True

    def _on_fsm_channels_synced(self, _):
        if self.debuglevel > 0:
            print('[%s]: event CHANNELS SYNCED' % self.debugname)
        return True

    def _on_fsm_status_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: event STATUS TRYING' % self.debugname)
        return True

    def _on_fsm_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP entry' % self.debugname)
        self.sync_status()
        if self.debuglevel > 0:
            print('[%s]: state UP' % self.debugname)
        for cb in self.on_state_changed:
            cb('up')
        return True

    def _on_fsm_up_exit(self, _):
        if self.debuglevel > 0:
            print('[%s]: state UP exit' % self.debugname)
        self.unsync_status()
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
    def status_uri(self):
        return self._status_channel.socket_uri

    @status_uri.setter
    def status_uri(self, value):
        self._status_channel.socket_uri = value

    def sync_status(self):
        print('WARNING: slot sync status unimplemented')

    def unsync_status(self):
        print('WARNING: slot unsync status unimplemented')

    def update_topics(self):
        print('WARNING: slot update topics unimplemented')

    def start(self):
        if self._fsm.isstate('down'):
            self._fsm.connect()

    def stop(self):
        if self._fsm.isstate('trying'):
            self._fsm.disconnect()
        elif self._fsm.isstate('up'):
            self._fsm.disconnect()

    def channels_synced(self):
        if self._fsm.isstate('syncing'):
            self._fsm.channels_synced()

    def add_status_topic(self, name):
        self._status_channel.add_socket_topic(name)

    def remove_status_topic(self, name):
        self._status_channel.remove_socket_topic(name)

    def clear_status_topics(self):
        self._status_channel.clear_socket_topics()

    def start_status_channel(self):
        self._status_channel.start()

    def stop_status_channel(self):
        self._status_channel.stop()

    # process all messages received on status
    def _status_channel_message_received(self, identity, rx):

        # react to emcstat full update message
        if rx.type == pb.MT_EMCSTAT_FULL_UPDATE:
            self.emcstat_full_update_received(identity, rx)

        # react to emcstat incremental update message
        elif rx.type == pb.MT_EMCSTAT_INCREMENTAL_UPDATE:
            self.emcstat_incremental_update_received(identity, rx)

        for cb in self.on_status_message_received:
            cb(identity, rx)

    def emcstat_full_update_received(self, identity, rx):
        print('SLOT emcstat full update unimplemented')

    def emcstat_incremental_update_received(self, identity, rx):
        print('SLOT emcstat incremental update unimplemented')

    def _status_channel_state_changed(self, state):

        if state == 'trying':
            if self._fsm.isstate('up'):
                self._fsm.status_trying()

        elif state == 'trying':
            if self._fsm.isstate('syncing'):
                self._fsm.status_trying()

        elif state == 'up':
            if self._fsm.isstate('trying'):
                self._fsm.status_up()
