import uuid
import platform
import os
from urlparse import urlparse
import ftplib

import zmq
import threading

# protobuf
from common import MessageObject, recurse_descriptor, recurse_message
from machinetalk.protobuf.message_pb2 import Container
import machinetalk.protobuf.types_pb2 as types
#from machinetalk.protobuf.status_pb2 import *
from machinetalk_core.application.statusbase import StatusBase
from machinetalk_core.application.commandbase import CommandBase
from machinetalk_core.application.errorbase import ErrorBase

ORIGIN_G54 = types.ORIGIN_G54
ORIGIN_G55 = types.ORIGIN_G55
ORIGIN_G56 = types.ORIGIN_G56
ORIGIN_G57 = types.ORIGIN_G57
ORIGIN_G58 = types.ORIGIN_G58
ORIGIN_G59 = types.ORIGIN_G59
ORIGIN_G59_1 = types.ORIGIN_G59_1
ORIGIN_G59_2 = types.ORIGIN_G59_2
ORIGIN_G59_3 = types.ORIGIN_G59_2

FREE_MODE = types.EMC_TRAJ_MODE_FREE
COORDINATED_MODE = types.EMC_TRAJ_MODE_COORD
TELEOP_MODE = types.EMC_TRAJ_MODE_TELEOP

MOTION_UNINITIALIZED = types.UNINITIALIZED_STATUS
MOTION_DONE = types.RCS_DONE
MOTION_EXEC = types.RCS_EXEC
MOTION_ERROR = types.RCS_ERROR
MOTION_RECEIVED = types.RCS_RECEIVED

NONE_TYPE = types._EMC_MOTION_TYPE_NONE
TRAVERSE_TYPE = types._EMC_MOTION_TYPE_TRAVERSE
FEED_TYPE = types._EMC_MOTION_TYPE_FEED
ARC_TYPE = types._EMC_MOTION_TYPE_ARC
TOOLCHANGE_TYPE = types._EMC_MOTION_TYPE_TOOLCHANGE
PROBING_TYPE = types._EMC_MOTION_TYPE_PROBING
INDEX_ROTARY_TYPE = types._EMC_MOTION_TYPE_INDEXROTARY

LINEAR_AXIS = types.EMC_AXIS_LINEAR
ANGULAR_AXIS = types.EMC_AXIS_ANGULAR

IDENTITY_KINEMATICS = types.KINEMATICS_IDENTITY
FORWARD_ONLY_KINEMATICS = types.KINEMATICS_FORWARD_ONLY
INVERSE_ONLY_KINEMATICS = types.KINEMATICS_INVERSE_ONLY
BOTH_KINEMATICS = types.KINEMATICS_BOTH

CANON_UNITS_INCH = types.CANON_UNITS_INCH
CANON_UNITS_MM = types.CANON_UNITS_MM
CANON_UNITS_CM = types.CANON_UNITS_CM

TIME_UNITS_MINUTE = types.TIME_UNITS_MINUTE
TIME_UNITS_SECOND = types.TIME_UNITS_SECOND

TASK_ERROR = types.EMC_TASK_EXEC_ERROR
TASK_DONE = types.EMC_TASK_EXEC_DONE
TASK_WAITING_FOR_MOTION = types.EMC_TASK_EXEC_WAITING_FOR_MOTION
TASK_WAITING_FOR_MOTION_QUEUE = types.EMC_TASK_EXEC_WAITING_FOR_MOTION_QUEUE
TASK_WAITING_FOR_IO = types.EMC_TASK_EXEC_WAITING_FOR_IO
TASK_WAITING_FOR_MOTION_AND_IO = types.EMC_TASK_EXEC_WAITING_FOR_MOTION_AND_IO
TASK_WAITING_FOR_DELAY = types.EMC_TASK_EXEC_WAITING_FOR_DELAY
TASK_WAITING_FOR_SYSTEM_CMD = types.EMC_TASK_EXEC_WAITING_FOR_SYSTEM_CMD
TASK_WAITING_FOR_SPINDLE_ORIENTED = types.EMC_TASK_EXEC_WAITING_FOR_SPINDLE_ORIENTED

TASK_MODE_MANUAL = types.EMC_TASK_MODE_MANUAL
TASK_MODE_AUTO = types.EMC_TASK_MODE_AUTO
TASK_MODE_MDI = types.EMC_TASK_MODE_MDI

TASK_STATE_ESTOP = types.EMC_TASK_STATE_ESTOP
TASK_STATE_ESTOP_RESET = types.EMC_TASK_STATE_ESTOP_RESET
TASK_STATE_OFF = types.EMC_TASK_STATE_OFF
TASK_STATE_ON = types.EMC_TASK_STATE_ON

INTERP_STATE_IDLE = types.EMC_TASK_INTERP_IDLE
INTERP_STATE_READING = types.EMC_TASK_INTERP_READING
INTERP_STATE_PAUSED = types.EMC_TASK_INTERP_PAUSED
INTERP_STATE_WAITING = types.EMC_TASK_INTERP_WAITING

INTERPRETER_EXIT_OK = types.EMC_INTERP_EXIT_OK
INTERPRETER_EXIT_EXIT = types.EMC_INTERP_EXIT_EXIT
INTERPRETER_EXIT_EXECUTE_FINISH = types.EMC_INTERP_EXIT_EXECUTE_FINISH
INTERPRETER_EXIT_ENDFILE = types.EMC_INTERP_EXIT_ENDFILE
INTERPRETER_EXIT_FILE_NOT_OPEN = types.EMC_INTERP_EXIT_FILE_NOT_OPEN
INTERPRETER_EXIT_ERROR = types.EMC_INTERP_EXIT_ERROR

RELATIVE_POSITION_OFFSET = types.EMC_CONFIG_RELATIVE_OFFSET
MACHINE_POSITION_OFFSET = types.EMC_CONFIG_MACHINE_OFFSET

ACTUAL_POSITION_FEEDBACK = types.EMC_CONFIG_ACTUAL_FEEDBACK
COMMANDED_POSITION_FEEDBACK = types.EMC_CONFIG_COMMANDED_FEEDBACK

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

NML_ERROR = types.MT_EMC_NML_ERROR
NML_TEXT = types.MT_EMC_NML_TEXT
NML_DISPLAY = types.MT_EMC_NML_DISPLAY
OPERATOR_ERROR = types.MT_EMC_OPERATOR_ERROR
OPERATOR_TEXT = types.MT_EMC_OPERATOR_TEXT
OPERATOR_DISPLAY = types.MT_EMC_OPERATOR_DISPLAY


class ApplicationStatus(StatusBase):

    def __init__(self, debug=False):
        super(StatusBase, self).__init__(debuglevel=int(debug))
        self.config_condition = threading.Condition(threading.Lock())
        self.io_condition = threading.Condition(threading.Lock())
        self.motion_condition = threading.Condition(threading.Lock())
        self.task_condition = threading.Condition(threading.Lock())
        self.interp_condition = threading.Condition(threading.Lock())
        self.synced_condition = threading.Condition(threading.Lock())
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_synced_changed = []

        self.synced = False

        # status containers, also used to expose data
        self._io_data = None
        self._config_data = None
        self._motion_data = None
        self._task_data = None
        self._interp_data = None
        self._initialize_object('io')
        self._initialize_object('config')
        self._initialize_object('motion')
        self._initialize_object('task')
        self._initialize_object('interp')

        self._synced_channels = set()
        self.channels = set(['motion', 'config', 'task', 'io', 'interp'])

    # make sure locks are used when accessing properties
    # should we return a copy instead of the reference?
    @property
    def io(self):
        with self.io_condition:
            return self._io_data

    @property
    def config(self):
        with self.config_condition:
            return self._config_data

    @property
    def motion(self):
        with self.motion_condition:
            return self._motion_data

    @property
    def task(self):
        with self.task_condition:
            return self._task_data

    @property
    def interp(self):
        with self.interp_condition:
            return self._interp_data

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

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()

    def emcstat_full_update_received(self, topic, rx):
        self._emcstat_update_received(topic, rx)
        self._update_synced_channels(topic)

    def emcstat_incremental_update_received(self, topic, rx):
        self._emcstat_update_received(topic, rx)

    def _emcstat_update_received(self, topic, rx):
        if topic == 'motion' and self.rx.HasField('emc_status_motion'):
            self.update_motion(self.rx.emc_status_motion)
        elif topic == 'config' and self.rx.HasField('emc_status_config'):
            self.update_config(self.rx.emc_status_config)
        elif topic == 'io' and self.rx.HasField('emc_status_io'):
            self.update_io(self.rx.emc_status_io)
        elif topic == 'task' and self.rx.HasField('emc_status_task'):
            self.update_task(self.rx.emc_status_task)
        elif topic == 'interp' and self.rx.HasField('emc_status_interp'):
                self.update_interp(self.rx.emc_status_interp)

    def _update_synced_channels(self, channel):
        self._synced_channels.add(channel)
        if (self._synced_channels == self.channels) and not self.synced:
            self.channels_synced()

    def sync_status(self):
        self._update_synced(True)

    def unsync_status(self):
        self._update_synced(False)

    def _update_synced(self, synced):
        with self.synced_condition:
            self.synced = synced
            self.synced_condition.notify()
        for cb in self.on_synced_changed:
            cb(synced)

    def update_topics(self):
        self.clear_status_topics()
        for channel in  self.channels:
            self.add_status_topic(channel)
            self._initialize_object(channel)

    def _initialize_object(self, channel):
        if channel == 'io':
            self._io_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_io.DESCRIPTOR, self._io_data)
        elif channel == 'config':
            self._config_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_config.DESCRIPTOR, self._config_data)
        elif channel == 'motion':
            self._motion_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_motion.DESCRIPTOR, self._motion_data)
        elif channel == 'task':
            self._task_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_task.DESCRIPTOR, self._task_data)
        elif channel == 'interp':
            self._interp_data = MessageObject()
            recurse_descriptor(self.rx.emc_status_interp.DESCRIPTOR, self._interp_data)

    def _update_motion_object(self, data):
        with self.motion_condition:
            recurse_message(data, self._motion_data)
            self.motion_condition.notify()

    def _update_config_object(self, data):
        with self.config_condition:
            recurse_message(data, self._config_data)
            self.config_condition.notify()

    def _update_io_object(self, data):
        with self.io_condition:
            recurse_message(data, self._io_data)
            self.io_condition.notify()

    def _update_task_object(self, data):
        with self.task_condition:
            recurse_message(data, self._task_data)
            self._update_running()
            self.task_condition.notify()

    def _update_interp_object(self, data):
        with self.interp_condition:
            recurse_message(data, self._interp_data)
            self._update_running()
            self.interp_condition.notify()

    def _update_running(self):
        running = (self._task_data.task_mode == types.EMC_TASK_MODE_AUTO \
                   or self._task_data.task_mode == types.EMC_TASK_MODE_MDI) \
                   and self._interp_data.interp_state == types.EMC_TASK_INTERP_IDLE

        self.running = running


class ApplicationCommand(CommandBase):

    def __init__(self, debug=False):
        self.completed_condition = threading.Condition(threading.Lock())
        self.executed_condition = threading.Condition(threading.Lock())
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_connected_changed = []

        self.connected = False

        self.ticket = 1  # stores the local ticket number
        self.executed_ticket = 0  # last tick number from executed feedback
        self.completed_ticket = 0  # last tick number from executed feedback
        self._executed_updated = False
        self._completed_updated = False

        # more efficient to reuse a protobuf message
        self._tx = Container()

    def emccmd_executed_received(self, rx):
        with self.executed_condition:
            self.executed_ticket = rx.reply_ticket
            self._executed_updated = True
            self.executed_condition.notify()

    def emccmd_completed_received(self, rx):
        with self.completed_condition:
            self.completed_ticket = self.rx.reply_ticket
            self._completed_updated = True
            self.completed_condition.notify()

    def wait_executed(self, ticket=None, timeout=None):
        with self.executed_condition:
            if ticket and ticket <= self.executed_ticket:  # very likely that we already received the reply
                return True

            while True:
                self._executed_updated = False
                self.executed_condition.wait(timeout=timeout)
                if not self._executed_updated:
                    return False  # timeout
                if ticket is None or ticket == self.executed_ticket:
                    return True

    def wait_completed(self, ticket=None, timeout=None):
        with self.completed_condition:
            if ticket and ticket < self.completed_ticket:  # very likely that we already received the reply
                return True

            while True:
                self._completed_updated = False
                self.completed_condition.wait(timeout=timeout)
                if not self._completed_updated:
                    return False  # timeout
                if ticket is None or ticket == self.completed_ticket:
                    return True

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()

    def set_connected(self):
        self._update_connected(True)

    def clear_connected(self):
        self._update_connected(False)

    def _update_connected(self, connected):
        with self.connected_condition:
            self.connected = connected
            self.connected_condition.notify()
        for cb in self.on_connected_changed:
            cb(connected)

    def _take_ticket(self):
        self.ticket += 1
        return self.ticket

    def abort(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter
        self.send_emc_task_abort(self._tx)
        return self._take_ticket()

    def run_program(self, line_number, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.line_number = line_number
        self._tx.interp_name = interpreter

        self.send_emc_task_plan_run(self._tx)
        return self._take_ticket()

    def pause_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        self.send_emc_task_plan_pause(self._tx)
        return self._take_ticket()

    def step_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        self.send_emc_task_plan_step(self._tx)
        return self._tacke_ticket()

    def resume_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        self.send_emc_task_plan_resume(self._tx)
        return self._tacke_ticket()

    def set_task_mode(self, mode, interpreter='execute'):
        if not self.connected:
            return

        params = self._tx.emc_command_params
        params.task_mode = mode
        self._tx.interp_name = interpreter

        self.send_emc_task_set_mode(self._tx)
        return self._tacke_ticket()

    def set_task_state(self, state, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.task_state = state
        self._tx.interp_name = interpreter

        self.send_emc_task_set_state(self._tx)
        return self._tacke_ticket()

    def open_program(self, file_name, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.path = file_name
        self._tx.interp_name = interpreter

        self.send_emc_task_plan_open(self._tx)
        return self._tacke_ticket()

    def reset_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        self.send_emc_task_plan_init(self._tx)
        return self._tacke_ticket()

    def execute_mdi(self, command, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.command = command
        self._tx.interp_name = interpreter

        self.send_emc_task_plan_execute(self._tx)
        return self._tacke_ticket()

    def set_spindle_brake(self, brake):
        if not self.connected:
            return None

        if brake == ENGAGE_BRAKE:
            self.send_emc_spindle_brake_engage()
        elif brake == RELEASE_BRAKE:
            self.send_emc_spindle_brake_release()
        return self._tacke_ticket()

    def set_debug_level(self, debug_level):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.debug_level = debug_level
        self._tx.interp_name = debug_level

        self.send_emc_set_debug(self._tx)
        return self._tacke_ticket()

    def set_feed_override(self, scale):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.scale = scale

        self.send_emc_traj_set_scale(self._tx)
        return self._tacke_ticket()

    def set_flood_enabled(self, enable):
        if not self.connected:
            return None

        if enable:
            self.send_emc_coolant_flood_on(self._tx)
        else:
            self.send_emc_coolant_flood_off(self._tx)
        return self._tacke_ticket()

    def home_axis(self, index):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index

        self.send_emc_axis_home(self._tx)
        return self._tacke_ticket()

    def jog(self, jog_type, axis, velocity=0.0, distance=0.0):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis

        if jog_type == JOG_STOP:
            self.send_emc_axis_abort(self._tx)
        elif jog_type == JOG_CONTINUOUS:
            params.velocity = velocity
            self.send_send_emc_axis_jog(self._tx)
        elif jog_type == JOG_INCREMENT:
            params.velocity = velocity
            params.distance = distance
            self.send_emc_axis_incr_jog(self._tx)
        else:
            self._tx.Clear()
            return None

        return self._tacke_ticket()

    def load_tool_table(self):
        if not self.connected:
            return None

        self.send_emc_tool_load_tool_table(self._tx)
        return self._tacke_ticket()

    def update_tool_table(self, tool_table):
        pass  # TODO

    def set_maximum_velocity(self, velocity):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.velocity = velocity

        self.send_emc_traj_set_max_velocity(self._tx)
        return self._tacke_ticket()

    def set_mist_enabled(self, enable):
        if not self.connected:
            return None

        if enable:
            self.send_emc_coolant_mist_on(self._tx)
        else:
            self.send_emc_coolant_mist_off(self._tx)
        return self._tacke_ticket()

    def override_limits(self):
        if not self.connected:
            return None

        self.send_emc_axis_override_limits(self._tx)
        return self._tacke_ticket()

    def set_adaptive_feed_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_motion_adaptive(self._tx)
        return self._tacke_ticket()

    def set_analog_output(self, index, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index
        params.value = value

        self.send_emc_motion_set_aout(self._tx)
        return self._tacke_ticket()

    def set_block_delete_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_task_plan_block_delete(self._tx)
        return self._tacke_ticket()

    def set_digital_output(self, index, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index
        params.enable = enable

        self.send_emc_motion_set_dout(self._tx)
        return self._tacke_ticket()

    def set_feed_hold_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_traj_set_fh_enable(self._tx)
        return self._tacke_ticket()

    def set_feed_override_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_traj_set_fo_enable(self._tx)
        return self._tacke_ticket()

    def set_axis_max_position_limit(self, axis, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis
        params.value = value

        self.send_emc_axis_set_max_position_limit(self._tx)
        return self._tacke_ticket()

    def set_axis_min_position_limit(self, axis, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis
        params.value = value

        self.send_emc_axis_set_min_position_limit(self._tx)
        return self._tacke_ticket()

    def set_optional_stop_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_task_plan_set_optional_stop(self._tx)
        return self._tacke_ticket()

    def set_spindle_override_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_traj_set_so_enable(self._tx)
        return self._tacke_ticket()

    def set_spindle(self, mode, velocity=0.0):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        if mode == SPINDLE_FORWARD:
            params.velocity = velocity
            self.send_emc_spindle_on(self._tx)
        elif mode == SPINDLE_REVERSE:
            params.velocity = velocity * -1.0
            self.send_emc_spindle_on(self._tx)
        elif mode == SPINDLE_OFF:
            self.send_emc_spindle_off(self._tx)
        elif mode == SPINDLE_INCREASE:
            self.send_emc_spindle_increase(self._tx)
        elif mode == SPINDLE_DECREASE:
            self.send_emc_spindle_decrease(self._tx)
        elif mode == SPINDLE_CONSTANT:
            self.send_emc_spindle_constant(self._tx)
        else:
            self._tx.Clear()
            return None

        return self._tacke_ticket()

    def set_spindle_override(self, scale):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.scale = scale

        self.send_emc_traj_set_spindle_scale(self._tx)
        return self._tacke_ticket()

    def set_teleop_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        self.send_emc_traj_set_teleop_enable(self._tx)
        return self._tacke_ticket()

    def set_teleop_vector(self, a, b, c, u, v, w):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        pose = params.pose
        pose.a = a
        pose.b = b
        pose.c = c
        pose.u = u
        pose.v = v
        pose.w = w

        self.send_emc_traj_set_teleop_vector(self._tx)
        return self._tacke_ticket()

    def set_tool_offset(self, index, zoffset, xoffset, diameter, frontangle, backangle, orientation):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        tooldata = params.tool_data
        tooldata.index = index
        tooldata.zoffset = zoffset
        tooldata.xoffset = xoffset
        tooldata.diameter = diameter
        tooldata.frontangle = frontangle
        tooldata.backangle = backangle
        tooldata.orientation = orientation

        self.send_emc_tool_set_offset(self._tx)
        return self._tacke_ticket()

    def set_trajectory_mode(self, mode):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.traj_mode = mode

        self.send_emc_traj_set_mode(self._tx)
        return self._tacke_ticket()

    def unhome_axis(self, index):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index

        self.send_emc_axis_unhome(self._tx)
        return self._tacke_ticket()

    def shutdown(self):
        if not self.connected:
            return None

        self.send_shutdown(self._tx)
        return self._tacke_ticket()


class ApplicationError(ErrorBase):
    def __init__(self, debug=False):
        super(ErrorBase, self).__init__(debuglevel=int(debug))
        self.message_lock = threading.Lock()
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug
        self.is_ready = False

        # callbacks
        self.on_connected_changed = []

        self.connected = False
        self.channels = set(['error', 'text', 'display'])
        self.error_list = []

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()

    def emc_nml_error_received(self, _, rx):
        self._error_message_received(rx)

    def emc_nml_text_received(self, _, rx):
        self._error_message_received(rx)

    def emc_nml_display_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_text_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_display_received(self, _, rx):
        self._error_message_received(rx)

    def emc_operator_error_received(self, _, rx):
        self._error_message_received(rx)

    def _error_message_received(self, rx):
        error = {'type': rx.type, 'notes': []}
        with self.message_lock:
            for note in rx.note:
                error['notes'].append(note)
                self.error_list.append(error)

    # slot
    def update_topics(self):
        self.clear_error_topics()
        for channel in self.channels:
            self.add_error_channel(channel)

    # slot
    def set_connected(self):
        self._update_connected(True)

    # slot
    def clear_connected(self):
        self._update_connected(False)

    def _update_connected(self, connected):
        with self.connected_condition:
            self.connected = connected
            self.connected_condition.notify()
        for cb in self.on_connected_changed:
            cb(connected)

    # returns all received messages and clears the buffer
    def get_messages(self):
        with self.message_lock:
            messages = list(self.error_list)  # make sure to return a copy
            self.error_list = []
            return messages


class ApplicationFile(object):

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
