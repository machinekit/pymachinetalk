# coding=utf-8
from fysom import Fysom
from ..common.rpcclient import RpcClient
from ..halremote.halrcompsubscribe import HalrcompSubscribe

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class RemoteComponentBase(object):
    def __init__(self, debuglevel=0, debugname='Remote Component Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Halrcmd
        self._halrcmd_channel = RpcClient(debuglevel=debuglevel)
        self._halrcmd_channel.debugname = '%s - %s' % (self.debugname, 'halrcmd')
        self._halrcmd_channel.on_state_changed.append(
            self._halrcmd_channel_state_changed
        )
        self._halrcmd_channel.on_socket_message_received.append(
            self._halrcmd_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._halrcmd_rx = Container()
        self._halrcmd_tx = Container()

        # Halrcomp
        self._halrcomp_channel = HalrcompSubscribe(debuglevel=debuglevel)
        self._halrcomp_channel.debugname = '%s - %s' % (self.debugname, 'halrcomp')
        self._halrcomp_channel.on_state_changed.append(
            self._halrcomp_channel_state_changed
        )
        self._halrcomp_channel.on_socket_message_received.append(
            self._halrcomp_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._halrcomp_rx = Container()

        # callbacks
        self.on_halrcmd_message_received = []
        self.on_halrcomp_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'trying'},
                    {'name': 'halrcmd_up', 'src': 'trying', 'dst': 'bind'},
                    {'name': 'disconnect', 'src': 'trying', 'dst': 'down'},
                    {'name': 'halrcomp_bind_msg_sent', 'src': 'bind', 'dst': 'binding'},
                    {'name': 'no_bind', 'src': 'bind', 'dst': 'syncing'},
                    {'name': 'bind_confirmed', 'src': 'binding', 'dst': 'syncing'},
                    {'name': 'bind_rejected', 'src': 'binding', 'dst': 'error'},
                    {'name': 'halrcmd_trying', 'src': 'binding', 'dst': 'trying'},
                    {'name': 'disconnect', 'src': 'binding', 'dst': 'down'},
                    {'name': 'halrcmd_trying', 'src': 'syncing', 'dst': 'trying'},
                    {'name': 'halrcomp_up', 'src': 'syncing', 'dst': 'sync'},
                    {'name': 'sync_failed', 'src': 'syncing', 'dst': 'error'},
                    {'name': 'disconnect', 'src': 'syncing', 'dst': 'down'},
                    {'name': 'pins_synced', 'src': 'sync', 'dst': 'synced'},
                    {'name': 'halrcomp_trying', 'src': 'synced', 'dst': 'syncing'},
                    {'name': 'halrcmd_trying', 'src': 'synced', 'dst': 'trying'},
                    {'name': 'set_rejected', 'src': 'synced', 'dst': 'error'},
                    {'name': 'halrcomp_set_msg_sent', 'src': 'synced', 'dst': 'synced'},
                    {'name': 'disconnect', 'src': 'synced', 'dst': 'down'},
                    {'name': 'disconnect', 'src': 'error', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.onleavedown = self._on_fsm_down_exit
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onafterhalrcmd_up = self._on_fsm_halrcmd_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect
        self._fsm.onbind = self._on_fsm_bind
        self._fsm.onafterhalrcomp_bind_msg_sent = self._on_fsm_halrcomp_bind_msg_sent
        self._fsm.onafterno_bind = self._on_fsm_no_bind
        self._fsm.onbinding = self._on_fsm_binding
        self._fsm.onafterbind_confirmed = self._on_fsm_bind_confirmed
        self._fsm.onafterbind_rejected = self._on_fsm_bind_rejected
        self._fsm.onafterhalrcmd_trying = self._on_fsm_halrcmd_trying
        self._fsm.onsyncing = self._on_fsm_syncing
        self._fsm.onafterhalrcomp_up = self._on_fsm_halrcomp_up
        self._fsm.onaftersync_failed = self._on_fsm_sync_failed
        self._fsm.onsync = self._on_fsm_sync
        self._fsm.onafterpins_synced = self._on_fsm_pins_synced
        self._fsm.onsynced = self._on_fsm_synced
        self._fsm.onafterhalrcomp_trying = self._on_fsm_halrcomp_trying
        self._fsm.onafterset_rejected = self._on_fsm_set_rejected
        self._fsm.onafterhalrcomp_set_msg_sent = self._on_fsm_halrcomp_set_msg_sent
        self._fsm.onerror = self._on_fsm_error

    def _on_fsm_down(self, _):
        if self.debuglevel > 0:
            print('[%s]: state DOWN entry' % self.debugname)
        self.set_disconnected()
        if self.debuglevel > 0:
            print('[%s]: state DOWN' % self.debugname)
        for cb in self.on_state_changed:
            cb('down')
        return True

    def _on_fsm_connect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event CONNECT' % self.debugname)
        self.add_pins()
        self.start_halrcmd_channel()
        return True

    def _on_fsm_down_exit(self, _):
        if self.debuglevel > 0:
            print('[%s]: state DOWN exit' % self.debugname)
        self.set_connecting()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_halrcmd_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCMD UP' % self.debugname)
        self.bind_component()
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_halrcmd_channel()
        self.stop_halrcomp_channel()
        self.remove_pins()
        return True

    def _on_fsm_bind(self, _):
        if self.debuglevel > 0:
            print('[%s]: state BIND' % self.debugname)
        for cb in self.on_state_changed:
            cb('bind')
        return True

    def _on_fsm_halrcomp_bind_msg_sent(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCOMP BIND MSG SENT' % self.debugname)
        return True

    def _on_fsm_no_bind(self, _):
        if self.debuglevel > 0:
            print('[%s]: event NO BIND' % self.debugname)
        self.start_halrcomp_channel()
        return True

    def _on_fsm_binding(self, _):
        if self.debuglevel > 0:
            print('[%s]: state BINDING' % self.debugname)
        for cb in self.on_state_changed:
            cb('binding')
        return True

    def _on_fsm_bind_confirmed(self, _):
        if self.debuglevel > 0:
            print('[%s]: event BIND CONFIRMED' % self.debugname)
        self.start_halrcomp_channel()
        return True

    def _on_fsm_bind_rejected(self, _):
        if self.debuglevel > 0:
            print('[%s]: event BIND REJECTED' % self.debugname)
        self.stop_halrcmd_channel()
        return True

    def _on_fsm_halrcmd_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCMD TRYING' % self.debugname)
        return True

    def _on_fsm_syncing(self, _):
        if self.debuglevel > 0:
            print('[%s]: state SYNCING' % self.debugname)
        for cb in self.on_state_changed:
            cb('syncing')
        return True

    def _on_fsm_halrcomp_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCOMP UP' % self.debugname)
        return True

    def _on_fsm_sync_failed(self, _):
        if self.debuglevel > 0:
            print('[%s]: event SYNC FAILED' % self.debugname)
        self.stop_halrcomp_channel()
        self.stop_halrcmd_channel()
        return True

    def _on_fsm_sync(self, _):
        if self.debuglevel > 0:
            print('[%s]: state SYNC' % self.debugname)
        for cb in self.on_state_changed:
            cb('sync')
        return True

    def _on_fsm_pins_synced(self, _):
        if self.debuglevel > 0:
            print('[%s]: event PINS SYNCED' % self.debugname)
        return True

    def _on_fsm_synced(self, _):
        if self.debuglevel > 0:
            print('[%s]: state SYNCED entry' % self.debugname)
        self.set_connected()
        if self.debuglevel > 0:
            print('[%s]: state SYNCED' % self.debugname)
        for cb in self.on_state_changed:
            cb('synced')
        return True

    def _on_fsm_halrcomp_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCOMP TRYING' % self.debugname)
        self.unsync_pins()
        self.set_timeout()
        return True

    def _on_fsm_set_rejected(self, _):
        if self.debuglevel > 0:
            print('[%s]: event SET REJECTED' % self.debugname)
        self.stop_halrcomp_channel()
        self.stop_halrcmd_channel()
        return True

    def _on_fsm_halrcomp_set_msg_sent(self, _):
        if self.debuglevel > 0:
            print('[%s]: event HALRCOMP SET MSG SENT' % self.debugname)
        return True

    def _on_fsm_error(self, _):
        if self.debuglevel > 0:
            print('[%s]: state ERROR entry' % self.debugname)
        self.set_error()
        if self.debuglevel > 0:
            print('[%s]: state ERROR' % self.debugname)
        for cb in self.on_state_changed:
            cb('error')
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
    def halrcmd_uri(self):
        return self._halrcmd_channel.socket_uri

    @halrcmd_uri.setter
    def halrcmd_uri(self, value):
        self._halrcmd_channel.socket_uri = value

    @property
    def halrcomp_uri(self):
        return self._halrcomp_channel.socket_uri

    @halrcomp_uri.setter
    def halrcomp_uri(self, value):
        self._halrcomp_channel.socket_uri = value

    def bind_component(self):
        print('WARNING: slot bind component unimplemented')

    def add_pins(self):
        print('WARNING: slot add pins unimplemented')

    def remove_pins(self):
        print('WARNING: slot remove pins unimplemented')

    def unsync_pins(self):
        print('WARNING: slot unsync pins unimplemented')

    def set_connected(self):
        print('WARNING: slot set connected unimplemented')

    def set_error(self):
        print('WARNING: slot set error unimplemented')

    def set_disconnected(self):
        print('WARNING: slot set disconnected unimplemented')

    def set_connecting(self):
        print('WARNING: slot set connecting unimplemented')

    def set_timeout(self):
        print('WARNING: slot set timeout unimplemented')

    def no_bind(self):
        if self._fsm.isstate('bind'):
            self._fsm.no_bind()

    def pins_synced(self):
        if self._fsm.isstate('sync'):
            self._fsm.pins_synced()

    def start(self):
        if self._fsm.isstate('down'):
            self._fsm.connect()

    def stop(self):
        if self._fsm.isstate('trying'):
            self._fsm.disconnect()
        elif self._fsm.isstate('binding'):
            self._fsm.disconnect()
        elif self._fsm.isstate('syncing'):
            self._fsm.disconnect()
        elif self._fsm.isstate('synced'):
            self._fsm.disconnect()
        elif self._fsm.isstate('error'):
            self._fsm.disconnect()

    def add_halrcomp_topic(self, name):
        self._halrcomp_channel.add_socket_topic(name)

    def remove_halrcomp_topic(self, name):
        self._halrcomp_channel.remove_socket_topic(name)

    def clear_halrcomp_topics(self):
        self._halrcomp_channel.clear_socket_topics()

    def start_halrcmd_channel(self):
        self._halrcmd_channel.start()

    def stop_halrcmd_channel(self):
        self._halrcmd_channel.stop()

    def start_halrcomp_channel(self):
        self._halrcomp_channel.start()

    def stop_halrcomp_channel(self):
        self._halrcomp_channel.stop()

    # process all messages received on halrcmd
    def _halrcmd_channel_message_received(self, rx):

        # react to halrcomp bind confirm message
        if rx.type == pb.MT_HALRCOMP_BIND_CONFIRM:
            if self._fsm.isstate('binding'):
                self._fsm.bind_confirmed()

        # react to halrcomp bind reject message
        elif rx.type == pb.MT_HALRCOMP_BIND_REJECT:
            # update error string with note
            self.error_string = ''
            for note in rx.note:
                self.error_string += note + '\n'
            if self._fsm.isstate('binding'):
                self._fsm.bind_rejected()

        # react to halrcomp set reject message
        elif rx.type == pb.MT_HALRCOMP_SET_REJECT:
            # update error string with note
            self.error_string = ''
            for note in rx.note:
                self.error_string += note + '\n'
            if self._fsm.isstate('synced'):
                self._fsm.set_rejected()

        for cb in self.on_halrcmd_message_received:
            cb(rx)

    # process all messages received on halrcomp
    def _halrcomp_channel_message_received(self, identity, rx):

        # react to halrcomp full update message
        if rx.type == pb.MT_HALRCOMP_FULL_UPDATE:
            self.halrcomp_full_update_received(identity, rx)

        # react to halrcomp incremental update message
        elif rx.type == pb.MT_HALRCOMP_INCREMENTAL_UPDATE:
            self.halrcomp_incremental_update_received(identity, rx)

        # react to halrcomp error message
        elif rx.type == pb.MT_HALRCOMP_ERROR:
            # update error string with note
            self.error_string = ''
            for note in rx.note:
                self.error_string += note + '\n'
            if self._fsm.isstate('syncing'):
                self._fsm.sync_failed()
            self.halrcomp_error_received(identity, rx)

        for cb in self.on_halrcomp_message_received:
            cb(identity, rx)

    def halrcomp_full_update_received(self, identity, rx):
        print('SLOT halrcomp full update unimplemented')

    def halrcomp_incremental_update_received(self, identity, rx):
        print('SLOT halrcomp incremental update unimplemented')

    def halrcomp_error_received(self, identity, rx):
        print('SLOT halrcomp error unimplemented')

    def send_halrcmd_message(self, msg_type, tx):
        self._halrcmd_channel.send_socket_message(msg_type, tx)

        if msg_type == pb.MT_HALRCOMP_BIND:
            if self._fsm.isstate('bind'):
                self._fsm.halrcomp_bind_msg_sent()

        elif msg_type == pb.MT_HALRCOMP_SET:
            if self._fsm.isstate('synced'):
                self._fsm.halrcomp_set_msg_sent()

    def send_halrcomp_bind(self, tx):
        self.send_halrcmd_message(pb.MT_HALRCOMP_BIND, tx)

    def send_halrcomp_set(self, tx):
        self.send_halrcmd_message(pb.MT_HALRCOMP_SET, tx)

    def _halrcmd_channel_state_changed(self, state):

        if state == 'trying':
            if self._fsm.isstate('syncing'):
                self._fsm.halrcmd_trying()
            elif self._fsm.isstate('synced'):
                self._fsm.halrcmd_trying()
            elif self._fsm.isstate('binding'):
                self._fsm.halrcmd_trying()

        elif state == 'up':
            if self._fsm.isstate('trying'):
                self._fsm.halrcmd_up()

    def _halrcomp_channel_state_changed(self, state):

        if state == 'trying':
            if self._fsm.isstate('synced'):
                self._fsm.halrcomp_trying()

        elif state == 'up':
            if self._fsm.isstate('syncing'):
                self._fsm.halrcomp_up()
