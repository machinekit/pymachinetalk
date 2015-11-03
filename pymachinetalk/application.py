import uuid
import platform
import os
from urlparse import urlparse
import ftplib

import zmq
import threading

# protobuf
from common import *
from message_pb2 import Container
from types_pb2 import *
from status_pb2 import *


INTERP_STATE_IDLE = EMC_TASK_INTERP_IDLE
INTERP_STATE_READING = EMC_TASK_INTERP_READING
INTERP_STATE_PAUSED = EMC_TASK_INTERP_PAUSED
INTERP_STATE_WAITING = EMC_TASK_INTERP_WAITING

MOTION_UNINITIALIZED = UNINITIALIZED_STATUS
MOTION_DONE = RCS_DONE
MOTION_EXEC = RCS_EXEC
MOTION_ERROR = RCS_ERROR
MOTION_RECEIVED = RCS_RECEIVED

TASK_ERROR = EMC_TASK_EXEC_ERROR
TASK_DONE = EMC_TASK_EXEC_DONE
TASK_WAITING_FOR_MOTION = EMC_TASK_EXEC_WAITING_FOR_MOTION
TASK_WAITING_FOR_MOTION_QUEUE = EMC_TASK_EXEC_WAITING_FOR_MOTION_QUEUE
TASK_WAITING_FOR_IO = EMC_TASK_EXEC_WAITING_FOR_IO
TASK_WAITING_FOR_MOTION_AND_IO = EMC_TASK_EXEC_WAITING_FOR_MOTION_AND_IO
TASK_WAITING_FOR_DELAY = EMC_TASK_EXEC_WAITING_FOR_DELAY
TASK_WAITING_FOR_SYSTEM_CMD = EMC_TASK_EXEC_WAITING_FOR_SYSTEM_CMD
TASK_WAITING_FOR_SPINDLE_ORIENTED = EMC_TASK_EXEC_WAITING_FOR_SPINDLE_ORIENTED

RELEASE_BRAKE = 0
ENGAGE_BRAKE = 1

JOG_STOP = 0
JOG_CONTINUOUS = 1
JOG_INCREMENT = 2

SPINDLE_FORWARD = 0
SPINDLE_REVERSE = 1
SPINDLE_OFF = 2
SPINDLE_DECREASE = 3
SPINDLE_INCREASE = 4
SPINDLE_CONSTANT = 5

TASK_STATE_ESTOP = EMC_TASK_STATE_ESTOP
TASK_STATE_ESTOP_RESET = EMC_TASK_STATE_ESTOP_RESET
TASK_STATE_OFF = EMC_TASK_STATE_OFF
TASK_STATE_ON = EMC_TASK_STATE_ON

TASK_MODE_MANUAL = EMC_TASK_MODE_MANUAL
TASK_MODE_AUTO = EMC_TASK_MODE_AUTO
TASK_MODE_MDI = EMC_TASK_MODE_MDI

NML_ERROR = MT_EMC_NML_ERROR
NML_TEXT = MT_EMC_NML_TEXT
NML_DISPLAY = MT_EMC_NML_DISPLAY
OPERATOR_ERROR = MT_EMC_OPERATOR_ERROR
OPERATOR_TEXT = MT_EMC_OPERATOR_TEXT
OPERATOR_DISPLAY = MT_EMC_OPERATOR_DISPLAY


class ApplicationStatus():

    def __init__(self, debug=False):
        self.threads = []
        self.shutdown = threading.Event()
        self.timer_lock = threading.Lock()
        self.config_condition = threading.Condition(threading.Lock())
        self.io_condition = threading.Condition(threading.Lock())
        self.motion_condition = threading.Condition(threading.Lock())
        self.task_condition = threading.Condition(threading.Lock())
        self.interp_condition = threading.Condition(threading.Lock())
        self.connected_condition = threading.Condition(threading.Lock())
        self.synced_condition = threading.Condition(threading.Lock())
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_synced_changed = []
        self.on_connected_changed = []

        self.synced = False
        self.connected = False
        self.state = 'Disconnected'
        self.status_state = 'Down'
        self.channels = set(['motion', 'config', 'io', 'task', 'interp'])
        self.running = False

        # more efficient to reuse a protobuf message
        self.rx = Container()

        # status containers, also used to expose data
        self.io_data = None
        self.config_data = None
        self.motion_data = None
        self.task_data = None
        self.interp_data = None
        self.initialize_object('io')
        self.initialize_object('config')
        self.initialize_object('motion')
        self.initialize_object('task')
        self.initialize_object('interp')

        self.status_uri = ''
        self.status_period = 0
        self.status_timer = None
        self.subscriptions = set()
        self.synced_channels = set()

        # ZeroMQ
        context = zmq.Context()
        context.linger = 0
        self.context = context
        self.status_socket = self.context.socket(zmq.SUB)
        self.sockets_connected = False

    # make sure locks are used when accessing properties
    # should we return a copy instead of the reference?
    @property
    def io(self):
        with self.io_condition:
            return self.io_data

    @property
    def config(self):
        with self.config_condition:
            return self.config_data

    @property
    def motion(self):
        with self.motion_condition:
            return self.motion_data

    @property
    def task(self):
        with self.task_condition:
            return self.task_data

    @property
    def interp(self):
        with self.interp_condition:
            return self.interp_data

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def wait_synced(self, timeout=None):
        with self.synced_condition:
            if self.synced:
                return True
            self.synced_condition.wait(timeout=timeout)
            return self.synced

    def wait_config_updated(self, timeout=None):
        with self.config_condition:
            self.config_condition.wait(timeout=timeout)

    def wait_io_updated(self, timeout=None):
        with self.io_condition:
            self.io_condition.wait(timeout=timeout)

    def wait_motion_updated(self, timeout=None):
        with self.motion_condition:
            self.motion_condition.wait(timeout=timeout)

    def wait_task_updated(self, timeout=None):
        with self.task_condition:
            self.task_condition.wait(timeout=timeout)

    def wait_interp_updated(self, timeout=None):
        with self.interp_condition:
            self.interp_condition.wait(timeout=timeout)

    def socket_worker(self):
        poll = zmq.Poller()
        poll.register(self.status_socket, zmq.POLLIN)

        while not self.shutdown.is_set():
            s = dict(poll.poll(200))
            if self.status_socket in s and s[self.status_socket] == zmq.POLLIN:
                self.process_status()

    def process_status(self):
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
                    self.start_status_heartbeat(interval * 2)  # wait double the hearbeat intverval
            else:
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

    def initialize_object(self, channel):
        if channel == 'io':
            self.io_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_io.DESCRIPTOR, self.io_data)
        elif channel == 'config':
            self.config_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_config.DESCRIPTOR, self.config_data)
        elif channel == 'motion':
            self.motion_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_motion.DESCRIPTOR, self.motion_data)
        elif channel == 'task':
            self.task_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_task.DESCRIPTOR, self.task_data)
        elif channel == 'interp':
            self.interp_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_interp.DESCRIPTOR, self.interp_data)

    def update_motion(self, data):
        with self.motion_condition:
            recurse_message(data, self.motion_data)
            self.motion_condition.notify()

    def update_config(self, data):
        with self.config_condition:
            recurse_message(data, self.config_data)
            self.config_condition.notify()

    def update_io(self, data):
        with self.io_condition:
            recurse_message(data, self.io_data)
            self.io_condition.notify()

    def update_task(self, data):
        with self.task_condition:
            recurse_message(data, self.task_data)
            self.update_running()
            self.task_condition.notify()

    def update_interp(self, data):
        with self.interp_condition:
            recurse_message(data, self.interp_data)
            self.update_running()
            self.interp_condition.notify()

    def update_sync(self, channel):
        self.synced_channels.add(channel)

        if self.synced_channels == self.channels:
            with self.synced_condition:
                self.synced = True
                self.synced_condition.notify()
            for func in self.on_synced_changed:
                func(True)

    def clear_sync(self):
        with self.synced_condition:
            self.synced = False
            self.synced_condition.notify()
        self.synced_channels.clear()
        for func in self.on_synced_changed:
            func(False)

    def status_timer_tick(self):
        self.status_state = 'Down'
        self.update_state('Timeout')

    def start_status_heartbeat(self, interval):
        self.timer_lock.acquire()
        if self.status_timer:
            self.status_timer.cancel()

        self.status_period = interval
        if interval > 0:
            self.status_timer = threading.Timer(interval / 1000,
                                                self.status_timer_tick)
            self.status_timer.start()
        self.timer_lock.release()

    def refresh_status_heartbeat(self):
        self.timer_lock.acquire()
        if self.status_timer:
            self.status_timer.cancel()
            self.status_timer = threading.Timer(self.status_period / 1000,
                                                self.status_timer_tick)
            self.status_timer.start()
        self.timer_lock.release()

    def stop_status_heartbeat(self):
        self.timer_lock.acquire()
        if self.status_timer:
            self.status_timer.cancel()
            self.status_timer = None
        self.timer_lock.release()

    def update_state(self, state):
        if state != self.state:
            self.state = state
            if state == 'Connected':
                with self.connected_condition:
                    self.connected = True
                    self.connected_condition.notify()
                print('[status] connected')
                for func in self.on_connected_changed:
                    func(True)
            elif self.connected:
                with self.connected_condition:
                    self.connected = False
                    self.connected_condition.notify()
                self.stop_status_heartbeat()
                self.clear_sync()
                self.status_period = 0  # stop heartbeat
                if not state == 'Timeout':  # clear in case we have no timeout
                    with self.motion_condition:
                        self.initialize_object('motion')
                    with self.config_condition:
                        self.initialize_object('config')
                    with self.io_condition:
                        self.initialize_object('io')
                    with self.task_condition:
                        self.initialize_object('task')
                    with self.interp_condition:
                        self.initialize_object('interp')
                print('[status] disconnected')
                for func in self.on_connected_changed:
                    func(False)

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
                with self.motion_condition:
                    self.initialize_object('motion')
            elif subscription == 'config':
                with self.config_condition:
                    self.initialize_object('config')
            elif subscription == 'io':
                with self.io_condition:
                    self.initialize_object('io')
            elif subscription == 'task':
                with self.task_condition:
                    self.initialize_object('lock')
            elif subscription == 'interp':
                with self.interp_condition:
                    self.initialize_object('interp')

        self.subscriptions.clear()

    def update_running(self):
        running = (self.task_data.task_mode == EMC_TASK_MODE_AUTO \
                   or self.task_data.task_mode == EMC_TASK_MODE_MDI) \
                   and self.interp_data.interp_state == EMC_TASK_INTERP_IDLE

        self.running = running

    def start(self):
        self.status_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            self.shutdown.clear()  # in case we already used the component
            self.threads.append(threading.Thread(target=self.socket_worker))
            for thread in self.threads:
                thread.start()
            self.subscribe()

    def stop(self):
        self.is_ready = False
        self.shutdown.set()
        for thread in self.threads:
            thread.join()
        self.threads = []
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        if self.connected:
            self.unsubscribe()
        self.disconnect_sockets()
        self.subscriptions.clear()

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
        self.shutdown_event = threading.Event()
        self.completed_condition = threading.Condition(threading.Lock())
        self.executed_condition = threading.Condition(threading.Lock())
        self.connected_condition = threading.Condition(threading.Lock())
        self.tx_lock = threading.Lock()
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_connected_changed = []

        self.connected = False
        self.state = 'Disconnected'
        self.command_state = 'Down'

        self.command_uri = ''
        self.heartbeat_period = 3000
        self.ping_error_count = 0
        self.ping_error_threshold = 2
        self.heartbeat_timer = None
        self.ticket = 1  # stores the local ticket number
        self.executed_ticket = 0  # last tick number from executed feedback
        self.completed_ticket = 0  # last tick number from executed feedback
        self.executed_updated = False
        self.completed_updated = False

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
        ticket = self.ticket
        self.tx.type = msg_type
        if msg_type != MT_PING:  # no need to add a ticket to a ping
            self.tx.ticket = ticket  # add the ticket serial number
            self.ticket += 1
        if self.debug:
            print('[command] sending message: %s' % msg_type)
            print(str(self.tx))
        self.command_socket.send(self.tx.SerializeToString(), zmq.NOBLOCK)
        self.tx.Clear()
        return ticket

    def socket_worker(self):
        poll = zmq.Poller()
        poll.register(self.command_socket, zmq.POLLIN)

        while not self.shutdown_event.is_set():
            s = dict(poll.poll(200))
            if self.command_socket in s:
                self.process_command()

    def process_command(self):
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

        elif self.rx.type == MT_EMCCMD_EXECUTED:
            with self.executed_condition:
                self.executed_ticket = self.rx.reply_ticket
                self.executed_updated = True
                self.executed_condition.notify()

        elif self.rx.type == MT_EMCCMD_COMPLETED:
            with self.completed_condition:
                self.completed_ticket = self.rx.reply_ticket
                self.completed_updated = True
                self.completed_condition.notify()

        else:
            print('[command] received unsupported message')

    def wait_executed(self, ticket=None, timeout=None):
        with self.executed_condition:
            if ticket and ticket <= self.executed_ticket:  # very likely that we already received the reply
                return True

            while True:
                self.executed_updated = False
                self.executed_condition.wait(timeout=timeout)
                if not self.executed_updated:
                    return False  # timeout
                if ticket is None or ticket == self.executed_ticket:
                    return True

    def wait_completed(self, ticket=None, timeout=None):
        with self.completed_condition:
            if ticket and ticket < self.completed_ticket:  # very likely that we already received the reply
                return True

            while True:
                self.completed_updated = False
                self.completed_condition.wait(timeout=timeout)
                if not self.completed_updated:
                    return False  # timeout
                if ticket is None or ticket == self.completed_ticket:
                    return True

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def start(self):
        self.command_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            self.shutdown_event.clear()  # in case we already used the component
            self.threads.append(threading.Thread(target=self.socket_worker))
            for thread in self.threads:
                thread.start()
            self.start_command_heartbeat()
            with self.tx_lock:
                self.send_command_msg(MT_PING)

    def stop(self):
        self.is_ready = False
        self.shutdown_event.set()
        for thread in self.threads:
            thread.join()
        self.threads = []
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        self.stop_command_heartbeat()
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
                with self.connected_condition:
                    self.connected = True
                    self.connected_condition.notify()
                print('[command] connected')
                for func in self.on_connected_changed:
                    func(True)
            elif self.connected:
                with self.connected_condition:
                    self.connected = False
                    self.connected_condition.notify()
                print('[command] disconnected')
                for func in self.on_connected_changed:
                    func(False)

    def update_error(self, error, description):
        print('[command] error: %s %s' % (error, description))

    def heartbeat_timer_tick(self):
        self.ping_error_count += 1  # increase error count by one, threshold 2 means two timer ticks

        if self.ping_error_count > self.ping_error_threshold:
            self.command_state = 'Trying'
            self.update_state('Timeout')

        with self.tx_lock:
            self.send_command_msg(MT_PING)

        self.heartbeat_timer = threading.Timer(self.heartbeat_period / 1000,
                                             self.heartbeat_timer_tick)
        self.heartbeat_timer.start()  # rearm timer

    def start_command_heartbeat(self):
        if not self.connected:
            return

        self.ping_error_count = 0  # reset heartbeat

        if self.heartbeat_period > 0:
            self.heartbeat_timer = threading.Timer(self.heartbeat_period / 1000,
                                                 self.heartbeat_timer_tick)
            self.heartbeat_timer.start()

    def stop_command_heartbeat(self):
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = None

    def abort(self, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_ABORT)

    def run_program(self, line_number, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.line_number = line_number
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_RUN)

    def pause_program(self, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_PAUSE)

    def step_program(self, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_STEP)

    def resume_program(self, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_RESUME)

    def reset_program(self, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_INIT)

    def set_task_mode(self, mode, interpreter='execute'):
        if not self.connected:
            return

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.task_mode = mode
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_SET_MODE)

    def set_task_state(self, state, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.task_state = state
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_SET_STATE)

    def open_program(self, file_name, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.path = file_name
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_OPEN)

    def execute_mdi(self, command, interpreter='execute'):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.command = command
            self.tx.interp_name = interpreter

            return self.send_command_msg(MT_EMC_TASK_PLAN_EXECUTE)

    def set_spindle_brake(self, brake):
        if not self.connected:
            return None

        with self.tx_lock:
            if brake == ENGAGE_BRAKE:
                return self.send_command_msg(MT_EMC_SPINDLE_BRAKE_ENGAGE)
            elif brake == RELEASE_BRAKE:
                return self.send_command_msg(MT_EMC_SPINDLE_BRAKE_RELEASE)

    def set_debug_level(self, debug_level):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.debug_level = debug_level
            self.tx.interp_name = debug_level

            return self.send_command_msg(MT_EMC_SET_DEBUG)

    def set_feed_override(self, scale):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.scale = scale

            return self.send_command_msg(MT_EMC_TRAJ_SET_SCALE)

    def set_flood_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            if enable:
                return self.send_command_msg(MT_EMC_COOLANT_FLOOD_ON)
            else:
                return self.send_command_msg(MT_EMC_COOLANT_FLOOD_OFF)

    def home_axis(self, index):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = index

            return self.send_command_msg(MT_EMC_AXIS_HOME)

    def jog(self, jog_type, axis, velocity=0.0, distance=0.0):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = axis

            cmd_type = None
            if jog_type == JOG_STOP:
                cmd_type = MT_EMC_AXIS_ABORT
            elif jog_type == JOG_CONTINUOUS:
                cmd_type = MT_EMC_AXIS_JOG
                params.velocity = velocity
            elif jog_type == JOG_INCREMENT:
                cmd_type = MT_EMC_AXIS_INCR_JOG
                params.velocity = velocity
                params.distance = distance
            else:
                self.tx.Clear()
                return None

            return self.send_command_msg(cmd_type)

    def load_tool_table(self):
        if not self.connected:
            return None

        with self.tx_lock:
            return self.send_command_msg(MT_EMC_TOOL_LOAD_TOOL_TABLE)

    def set_maximum_velocity(self, velocity):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.velocity = velocity

            return self.send_command_msg(MT_EMC_TRAJ_SET_MAX_VELOCITY)

    def set_mist_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            if enable:
                return self.send_command_msg(MT_EMC_COOLANT_MIST_ON)
            else:
                return self.send_command_msg(MT_EMC_COOLANT_MIST_OFF)

    def override_limits(self):
        if not self.connected:
            return None

        with self.tx_lock:
            return self.send_command_msg(MT_EMC_AXIS_OVERRIDE_LIMITS)

    def set_adaptive_feed_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_MOTION_ADAPTIVE)

    def set_analog_output(self, index, value):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = index
            params.value = value

            return self.send_command_msg(MT_EMC_MOTION_SET_AOUT)

    def set_block_delete_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TASK_PLAN_SET_BLOCK_DELETE)

    def set_digital_output(self, index, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = index
            params.enable = enable

            return self.send_command_msg(MT_EMC_MOTION_SET_DOUT)

    def set_feed_hold_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TRAJ_SET_FH_ENABLE)

    def set_feed_override_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TRAJ_SET_FO_ENABLE)

    def set_axis_max_position_limit(self, axis, value):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = axis
            params.value = value

            return self.send_command_msg(MT_EMC_AXIS_SET_MAX_POSITION_LIMIT)

    def set_axis_min_position_limit(self, axis, value):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = axis
            params.value = value

            self.send_command_msg(MT_EMC_AXIS_SET_MIN_POSITION_LIMIT)

    def set_optional_stop_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TASK_PLAN_SET_OPTIONAL_STOP)

    def set_spindle_override_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TRAJ_SET_SO_ENABLE)

    def set_spindle(self, mode, velocity=0.0):
        if not self.connected:
            return None

        with self.tx_lock:
            mode_type = None
            params = self.tx.emc_command_params
            if mode == SPINDLE_FORWARD:
                mode_type = MT_EMC_SPINDLE_ON
                params.velocity = velocity
            elif mode == SPINDLE_REVERSE:
                mode_type = MT_EMC_SPINDLE_ON
                params.velocity = velocity * -1.0
            elif mode == SPINDLE_OFF:
                mode_type = MT_EMC_SPINDLE_OFF
            elif mode == SPINDLE_INCREASE:
                mode_type = MT_EMC_SPINDLE_INCREASE
            elif mode == SPINDLE_DECREASE:
                mode_type = MT_EMC_SPINDLE_DECRESE
            elif mode == SPINDLE_CONSTANT:
                mode_type = MT_EMC_SPINDLE_CONSTANT
            else:
                self.tx.Clear()
                return None

            return self.send_command_msg(mode_type)

    def set_spindle_override(self, scale):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.scale = scale

            return self.send_command_msg(MT_EMC_TRAJ_SET_SPINDLE_SCALE)

    def set_teleop_enabled(self, enable):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.enable = enable

            return self.send_command_msg(MT_EMC_TRAJ_SET_TELEOP_ENABLE)

    def set_teleop_vector(self, a, b, c, u, v, w):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            pose = params.pose
            pose.a = a
            pose.b = b
            pose.c = c
            pose.u = u
            pose.v = v
            pose.w = w

            return self.send_command_msg(MT_EMC_TRAJ_SET_TELEOP_VECTOR)

    def set_tool_offset(self, index, zoffset, xoffset, diameter, frontangle, backangle, orientation):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            tooldata = params.tool_data
            tooldata.index = index
            tooldata.zoffset = zoffset
            tooldata.xoffset = xoffset
            tooldata.diameter = diameter
            tooldata.frontangle = frontangle
            tooldata.backangle = backangle
            tooldata.orientation = orientation

            return self.send_command_msg(MT_EMC_TOOL_SET_OFFSET)

    def set_trajectory_mode(self, mode):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.traj_mode = mode

            return self.send_command_msg(MT_EMC_TRAJ_SET_MODE)

    def unhome_axis(self, index):
        if not self.connected:
            return None

        with self.tx_lock:
            params = self.tx.emc_command_params
            params.index = index

            return self.send_command_msg(MT_EMC_AXIS_UNHOME)

    def shutdown(self):
        if not self.connected:
            return None

        with self.tx_lock:
            return self.send_command_msg(MT_SHUTDOWN)


class ApplicationError():

    def __init__(self, debug=False):
        self.threads = []
        self.shutdown = threading.Event()
        self.message_lock = threading.Lock()
        self.timer_lock = threading.Lock()
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_connected_changed = []

        self.connected = False
        self.state = 'Disconnected'
        self.socket_state = 'Down'
        self.channels = set(['error', 'text', 'display'])
        self.error_list = []

        self.error_uri = ''
        self.heartbeat_period = 0
        self.heartbeat_timer = None
        self.subscriptions = set()

        # more efficient to reuse protobuf message
        self.rx = Container()

        # ZeroMQ
        context = zmq.Context()
        context.linger = 0
        self.context = context
        self.socket = self.context.socket(zmq.SUB)
        self.sockets_connected = False

    def socket_worker(self):
        poll = zmq.Poller()
        poll.register(self.socket, zmq.POLLIN)

        while not self.shutdown.is_set():
            s = dict(poll.poll(200))
            if self.socket in s:
                self.process_error()

    def process_error(self):
        (topic, msg) = self.socket.recv_multipart()
        self.rx.ParseFromString(msg)

        if self.debug:
            print('[error] received message: %s' % topic)
            print(self.rx)

        if self.rx.type == MT_EMC_NML_ERROR \
           or self.rx.type == MT_EMC_NML_TEXT \
           or self.rx.type == MT_EMC_NML_DISPLAY \
           or self.rx.type == MT_EMC_OPERATOR_TEXT \
           or self.rx.type == MT_EMC_OPERATOR_ERROR \
           or self.rx.type == MT_EMC_OPERATOR_DISPLAY:

            error = {'type': self.rx.type, 'notes': []}
            with self.message_lock:
                for note in self.rx.note:
                    error['notes'].append(note)
                    self.error_list.append(error)
            self.refresh_error_heartbeat()

        elif self.rx.type == MT_PING:
            if self.socket_state == 'Up':
                self.refresh_error_heartbeat()
            else:
                if self.state == 'Timeout':  # waiting for the ping
                    self.update_state('Connecting')
                    self.unsubscribe()  # clean up previous subscription
                    self.subscribe()  # trigger a fresh subscribe -> full update
                else:  # ping as result from subscription received
                    self.socket_state = 'Up'
                    self.update_state('Connected')

            if self.rx.HasField('pparams'):
                interval = self.rx.pparams.keepalive_timer
                self.start_error_heartbeat(interval * 2)  # wait double the hearbeat intverval
        else:
            print('[status] received unrecognized message type')

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    # returns all received messages and clears the buffer
    def get_messages(self):
        with self.message_lock:
            messages = list(self.error_list)  # make sure to return a copy
            self.error_list = []
            return messages

    def heartbeat_timer_tick(self):
        self.socket_state = 'Down'
        self.update_state('Timeout')

    def start_error_heartbeat(self, interval):
        self.timer_lock.acquire()
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()

        self.heartbeat_period = interval
        if interval > 0:
            self.heartbeat_timer = threading.Timer(interval / 1000,
                                               self.heartbeat_timer_tick)
            self.heartbeat_timer.start()
        self.timer_lock.release()

    def refresh_error_heartbeat(self):
        self.timer_lock.acquire()
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = threading.Timer(self.heartbeat_period / 1000,
                                                   self.heartbeat_timer_tick)
            self.heartbeat_timer.start()
        self.timer_lock.release()

    def stop_error_heartbeat(self):
        self.timer_lock.acquire()
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = None
        self.timer_lock.release()

    def update_state(self, state):
        if state != self.state:
            self.state = state
            if state == 'Connected':
                with self.connected_condition:
                    self.connected = True
                    self.connected_condition.notify()
                print('[error] connected')
                for func in self.on_connected_changed:
                    func(True)
            elif self.connected:
                with self.connected_condition:
                    self.connected = False
                    self.connected_condition.notify()
                self.stop_error_heartbeat()
                print('[error] disconnected')
                for func in self.on_connected_changed:
                    func(False)

    def subscribe(self):
        self.socket_state = 'Trying'

        for channel in self.channels:
            self.socket.setsockopt(zmq.SUBSCRIBE, channel)
            self.subscriptions.add(channel)

    def unsubscribe(self):
        self.socket_state = 'Down'

        for subscription in self.subscriptions:
            self.socket.setsockopt(zmq.UNSUBSCRIBE, subscription)

        self.subscriptions.clear()

    def start(self):
        self.socket_state = 'Trying'
        self.update_state('Connecting')

        if self.connect_sockets():
            self.shutdown.clear()  # in case we already used the component
            self.threads.append(threading.Thread(target=self.socket_worker))
            for thread in self.threads:
                thread.start()
            self.subscribe()

    def stop(self):
        self.is_ready = False
        self.shutdown.set()
        for thread in self.threads:
            thread.join()
        self.threads = []
        self.cleanup()
        self.update_state('Disconnected')

    def cleanup(self):
        if self.connected:
            self.unsubscribe()
        self.disconnect_sockets()
        self.subscriptions.clear()

    def connect_sockets(self):
        self.sockets_connected = True
        self.socket.connect(self.error_uri)

        return True

    def disconnect_sockets(self):
        if self.sockets_connected:
            self.socket.disconnect(self.error_uri)
            self.sockets_connected = False

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()


class ApplicationFile():

    def __init__(self, debug=True):
        self.debug = debug
        self.state_condition = threading.Condition(threading.Lock())
        self.file_list_lock = threading.Lock()

        self.uri = ''
        self.local_file_path = ''
        self.remote_file_path = ''
        self.local_path = ''
        self.remote_path = ''
        self.transfer_state = 'NoTransfer'
        self.bytes_sent = 0.0
        self.bytes_total = 0.0
        self.progress = 0.0
        self.file = None

        self._file_list = []

    @property
    def file_list(self):
        with self.file_list_lock:
            return self._file_list

    def upload_worker(self):
        o = urlparse(self.uri)
        # test o.scheme

        filename = os.path.basename(self.local_file_path)
        self.remote_file_path = os.path.join(self.remote_path, filename)

        self.update_state('UploadRunning')  # lets start the upload
        if self.debug:
            print('[file] starting upload of %s' % filename)

        try:
            self.bytes_sent = 0.0
            self.bytes_total = os.path.getsize(self.local_file_path)
            f = open(self.local_file_path, 'r')
        except OSError as e:
            self.update_state('Error')
            self.update_error('file', str(e))
            return

        try:
            self.progress = 0.0
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.storbinary('STOR %s' % filename, f, blocksize=8192,
                           callback=self.progress_callback)
            ftp.close()
            f.close()
        except Exception as e:
            self.update_state('Error')
            self.update_error('ftp', str(e))
            return

        self.update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] upload of %s finished' % filename)

    def download_worker(self):
        o = urlparse(self.uri)
        # test o.scheme

        filename = self.remote_file_path[len(self.remote_path):]  # mid
        self.local_file_path = os.path.join(self.local_path, filename)

        self.update_state('DownloadRunning')  # lets start the upload
        if self.debug:
            print('[file] starting download of %s' % filename)

        try:
            local_path = os.path.dirname(os.path.abspath(self.local_file_path))
            if not os.path.exists(local_path):
                os.makedirs(local_path)
            self.file = open(self.local_file_path, 'w')
        except Exception as e:
            self.update_state('Error')
            self.update_error('file', str(e))
            return

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.sendcmd("TYPE i")  # Switch to Binary mode
            self.progress = 0.0
            self.bytes_sent = 0.0
            self.bytes_total = ftp.size(filename)
            ftp.retrbinary('RETR %s' % filename, self.progress_callback)
            ftp.close()
            self.file.close()
            self.file = None
        except Exception as e:
            self.update_state('Error')
            self.update_error('ftp', str(e))
            return

        self.update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] download of %s finished' % filename)

    def refresh_files_worker(self):
        o = urlparse(self.uri)
        # test o.scheme

        self.update_state('RefreshRunning')  # lets start the upload
        if self.debug:
            print('[file] starting file list refresh')

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            with self.file_list_lock:
                self._file_list = ftp.nlst()
            ftp.close()
        except Exception as e:
            self.update_state('Error')
            self.update_error('ftp', str(e))
            return

        self.update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] file refresh finished')

    def remove_file_worker(self, filename):
        o = urlparse(self.uri)
        # test o.scheme

        self.update_state('RemoveRunning')  # lets start the upload
        if self.debug:
            print('[file] removing %s' % filename)

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.delete(filename)
            ftp.close()
        except Exception as e:
            self.update_state('Error')
            self.update_error('ftp', str(e))
            return

        self.update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] removing %s completed' % filename)

    def progress_callback(self, data):
        if self.file is not None:
            self.file.write(data)
        self.bytes_sent += 8192
        self.progress = self.bytes_sent / self.bytes_total

    def start_upload(self):
        with self.state_condition:
            if self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self.upload_worker)
        thread.start()

    def start_download(self):
        with self.state_condition:
            if self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self.download_worker)
        thread.start()

    def refresh_files(self):
        with self.state_condition:
            if self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self.refresh_files_worker)
        thread.start()

    def remove_file(self, name):
        with self.state_condition:
            if self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self.remove_file_worker, args=(name, ))
        thread.start()

    def abort(self):
        pass

    def wait_completed(self, timeout=None):
        with self.state_condition:
            if self.transfer_state == 'NoTransfer':
                return True
            if self.transfer_state == 'Error':
                return False
            self.state_condition.wait(timeout=timeout)
            return self.transfer_state == 'NoTransfer'

    def update_state(self, state):
        with self.state_condition:
            if self.transfer_state != state:
                self.transfer_state = state
                self.state_condition.notify()

    def update_error(self, error, description):
        print('[file] error: %s %s' % (error, description))

    def clear_error(self):
        pass
