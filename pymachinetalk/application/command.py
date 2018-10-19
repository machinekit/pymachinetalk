# coding=utf-8
import threading

from machinetalk.protobuf.message_pb2 import Container
from .constants import (
    ENGAGE_BRAKE,
    RELEASE_BRAKE,
    JOG_STOP,
    JOG_CONTINUOUS,
    JOG_INCREMENT,
    SPINDLE_FORWARD,
    SPINDLE_REVERSE,
    SPINDLE_OFF,
    SPINDLE_INCREASE,
    SPINDLE_DECREASE,
    SPINDLE_CONSTANT,
)
from ..common import ComponentBase
from ..dns_sd import ServiceContainer, Service
from ..machinetalk_core.application.commandbase import CommandBase


class ApplicationCommand(ComponentBase, CommandBase, ServiceContainer):
    def __init__(self, debug=False):
        CommandBase.__init__(self, debuglevel=int(debug))
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.completed_condition = threading.Condition(threading.Lock())
        self.executed_condition = threading.Condition(threading.Lock())
        self.connected_condition = threading.Condition(threading.Lock())
        self.debug = debug

        # callbacks
        self.on_connected_changed = []

        self.connected = False

        self.ticket = 0  # stores the local ticket number
        self.executed_ticket = 0  # last tick number from executed feedback
        self.completed_ticket = 0  # last tick number from executed feedback
        self._executed_updated = False
        self._completed_updated = False

        # more efficient to reuse a protobuf message
        self._tx = Container()

        self._command_service = Service(type_='command')
        self.add_service(self._command_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    def _on_services_ready_changed(self, ready):
        self.command_uri = self._command_service.uri
        self.ready = ready

    def emccmd_executed_received(self, rx):
        with self.executed_condition:
            self.executed_ticket = rx.reply_ticket
            self._executed_updated = True
            self.executed_condition.notify()

    def emccmd_completed_received(self, rx):
        with self.completed_condition:
            self.completed_ticket = rx.reply_ticket
            self._completed_updated = True
            self.completed_condition.notify()

    def wait_executed(self, ticket=None, timeout=None):
        with self.executed_condition:
            if ticket is None:
                ticket = self.ticket
            if (
                ticket and ticket <= self.executed_ticket
            ):  # very likely that we already received the reply
                return True

            while True:
                self._executed_updated = False
                self.executed_condition.wait(timeout=timeout)
                if not self._executed_updated:
                    return False  # timeout
                if ticket == self.executed_ticket:
                    return True

    def wait_completed(self, ticket=None, timeout=None):
        with self.completed_condition:
            if ticket is None:
                ticket = self.ticket
            if (
                ticket and ticket < self.completed_ticket
            ):  # very likely that we already received the reply
                return True

            while True:
                self._completed_updated = False
                self.completed_condition.wait(timeout=timeout)
                if not self._completed_updated:
                    return False  # timeout
                if ticket == self.completed_ticket:
                    return True

    def wait_connected(self, timeout=None):
        with self.connected_condition:
            if self.connected:
                return True
            self.connected_condition.wait(timeout=timeout)
            return self.connected

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

    def _take_ticket(self):
        self.ticket += 1
        self._tx.ticket = self.ticket
        return self.ticket

    def abort(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_abort(self._tx)
        return ticket

    def run_program(self, line_number, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.line_number = line_number
        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_run(self._tx)
        return ticket

    def pause_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_pause(self._tx)
        return ticket

    def step_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_step(self._tx)
        return ticket

    def resume_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_resume(self._tx)
        return ticket

    def set_task_mode(self, mode, interpreter='execute'):
        if not self.connected:
            return

        params = self._tx.emc_command_params
        params.task_mode = mode
        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_set_mode(self._tx)
        return ticket

    def set_task_state(self, state, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.task_state = state
        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_set_state(self._tx)
        return ticket

    def open_program(self, file_name, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.path = file_name
        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_open(self._tx)
        return ticket

    def reset_program(self, interpreter='execute'):
        if not self.connected:
            return None

        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_init(self._tx)
        return ticket

    def execute_mdi(self, command, interpreter='execute'):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.command = command
        self._tx.interp_name = interpreter

        ticket = self._take_ticket()
        self.send_emc_task_plan_execute(self._tx)
        return ticket

    def set_spindle_brake(self, brake):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        if brake == ENGAGE_BRAKE:
            self.send_emc_spindle_brake_engage(self._tx)
        elif brake == RELEASE_BRAKE:
            self.send_emc_spindle_brake_release(self._tx)
        return ticket

    def set_debug_level(self, debug_level):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.debug_level = debug_level
        self._tx.interp_name = debug_level

        ticket = self._take_ticket()
        self.send_emc_set_debug(self._tx)
        return ticket

    def set_feed_override(self, scale):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.scale = scale

        ticket = self._take_ticket()
        self.send_emc_traj_set_scale(self._tx)
        return ticket

    def set_flood_enabled(self, enable):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        if enable:
            self.send_emc_coolant_flood_on(self._tx)
        else:
            self.send_emc_coolant_flood_off(self._tx)
        return ticket

    def home_axis(self, index):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index

        ticket = self._take_ticket()
        self.send_emc_axis_home(self._tx)
        return ticket

    def jog(self, jog_type, axis, velocity=0.0, distance=0.0):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis

        if jog_type == JOG_STOP:
            ticket = self._take_ticket()
            self.send_emc_axis_abort(self._tx)
        elif jog_type == JOG_CONTINUOUS:
            params.velocity = velocity
            ticket = self._take_ticket()
            self.send_emc_axis_jog(self._tx)
        elif jog_type == JOG_INCREMENT:
            params.velocity = velocity
            params.distance = distance
            ticket = self._take_ticket()
            self.send_emc_axis_incr_jog(self._tx)
        else:
            self._tx.Clear()
            return None

        return ticket

    def load_tool_table(self):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        self.send_emc_tool_load_tool_table(self._tx)
        return ticket

    def update_tool_table(self, tool_table):
        pass  # TODO

    def set_maximum_velocity(self, velocity):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.velocity = velocity

        ticket = self._take_ticket()
        self.send_emc_traj_set_max_velocity(self._tx)
        return ticket

    def set_mist_enabled(self, enable):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        if enable:
            self.send_emc_coolant_mist_on(self._tx)
        else:
            self.send_emc_coolant_mist_off(self._tx)
        return ticket

    def override_limits(self):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        self.send_emc_axis_override_limits(self._tx)
        return ticket

    def set_adaptive_feed_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_motion_adaptive(self._tx)
        return ticket

    def set_analog_output(self, index, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index
        params.value = value

        ticket = self._take_ticket()
        self.send_emc_motion_set_aout(self._tx)
        return ticket

    def set_block_delete_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_task_plan_set_block_delete(self._tx)
        return ticket

    def set_digital_output(self, index, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_motion_set_dout(self._tx)
        return ticket

    def set_feed_hold_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_traj_set_fh_enable(self._tx)
        return ticket

    def set_feed_override_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_traj_set_fo_enable(self._tx)
        return ticket

    def set_axis_max_position_limit(self, axis, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis
        params.value = value

        ticket = self._take_ticket()
        self.send_emc_axis_set_max_position_limit(self._tx)
        return ticket

    def set_axis_min_position_limit(self, axis, value):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = axis
        params.value = value

        ticket = self._take_ticket()
        self.send_emc_axis_set_min_position_limit(self._tx)
        return ticket

    def set_optional_stop_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_task_plan_set_optional_stop(self._tx)
        return ticket

    def set_spindle_override_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_traj_set_so_enable(self._tx)
        return ticket

    def set_spindle(self, mode, velocity=0.0):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        if mode == SPINDLE_FORWARD:
            params.velocity = velocity
            ticket = self._take_ticket()
            self.send_emc_spindle_on(self._tx)
        elif mode == SPINDLE_REVERSE:
            params.velocity = velocity * -1.0
            ticket = self._take_ticket()
            self.send_emc_spindle_on(self._tx)
        elif mode == SPINDLE_OFF:
            ticket = self._take_ticket()
            self.send_emc_spindle_off(self._tx)
        elif mode == SPINDLE_INCREASE:
            ticket = self._take_ticket()
            self.send_emc_spindle_increase(self._tx)
        elif mode == SPINDLE_DECREASE:
            ticket = self._take_ticket()
            self.send_emc_spindle_decrease(self._tx)
        elif mode == SPINDLE_CONSTANT:
            ticket = self._take_ticket()
            self.send_emc_spindle_constant(self._tx)
        else:
            self._tx.Clear()
            return None

        return ticket

    def set_spindle_override(self, scale):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.scale = scale

        ticket = self._take_ticket()
        self.send_emc_traj_set_spindle_scale(self._tx)
        return ticket

    def set_teleop_enabled(self, enable):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.enable = enable

        ticket = self._take_ticket()
        self.send_emc_traj_set_teleop_enable(self._tx)
        return ticket

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

        ticket = self._take_ticket()
        self.send_emc_traj_set_teleop_vector(self._tx)
        return ticket

    def set_tool_offset(
        self, index, zoffset, xoffset, diameter, frontangle, backangle, orientation
    ):
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

        ticket = self._take_ticket()
        self.send_emc_tool_set_offset(self._tx)
        return ticket

    def set_trajectory_mode(self, mode):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.traj_mode = mode

        ticket = self._take_ticket()
        self.send_emc_traj_set_mode(self._tx)
        return ticket

    def unhome_axis(self, index):
        if not self.connected:
            return None

        params = self._tx.emc_command_params
        params.index = index

        ticket = self._take_ticket()
        self.send_emc_axis_unhome(self._tx)
        return ticket

    def shutdown(self):
        if not self.connected:
            return None

        ticket = self._take_ticket()
        self.send_shutdown(self._tx)
        return ticket
