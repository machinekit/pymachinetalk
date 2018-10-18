# coding=utf-8
from fysom import Fysom
from ..common.rpcclient import RpcClient

import machinetalk.protobuf.types_pb2 as pb
from machinetalk.protobuf.message_pb2 import Container


class CommandBase(object):
    def __init__(self, debuglevel=0, debugname='Command Base'):
        self.debuglevel = debuglevel
        self.debugname = debugname
        self._error_string = ''
        self.on_error_string_changed = []

        # Command
        self._command_channel = RpcClient(debuglevel=debuglevel)
        self._command_channel.debugname = '%s - %s' % (self.debugname, 'command')
        self._command_channel.on_state_changed.append(
            self._command_channel_state_changed
        )
        self._command_channel.on_socket_message_received.append(
            self._command_channel_message_received
        )
        # more efficient to reuse protobuf messages
        self._command_rx = Container()
        self._command_tx = Container()

        # callbacks
        self.on_command_message_received = []
        self.on_state_changed = []

        # fsm
        self._fsm = Fysom(
            {
                'initial': 'down',
                'events': [
                    {'name': 'connect', 'src': 'down', 'dst': 'trying'},
                    {'name': 'command_up', 'src': 'trying', 'dst': 'up'},
                    {'name': 'disconnect', 'src': 'trying', 'dst': 'down'},
                    {'name': 'command_trying', 'src': 'up', 'dst': 'trying'},
                    {'name': 'disconnect', 'src': 'up', 'dst': 'down'},
                ],
            }
        )

        self._fsm.ondown = self._on_fsm_down
        self._fsm.onafterconnect = self._on_fsm_connect
        self._fsm.ontrying = self._on_fsm_trying
        self._fsm.onaftercommand_up = self._on_fsm_command_up
        self._fsm.onafterdisconnect = self._on_fsm_disconnect
        self._fsm.onup = self._on_fsm_up
        self._fsm.onaftercommand_trying = self._on_fsm_command_trying
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
        self.start_command_channel()
        return True

    def _on_fsm_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: state TRYING' % self.debugname)
        for cb in self.on_state_changed:
            cb('trying')
        return True

    def _on_fsm_command_up(self, _):
        if self.debuglevel > 0:
            print('[%s]: event COMMAND UP' % self.debugname)
        return True

    def _on_fsm_disconnect(self, _):
        if self.debuglevel > 0:
            print('[%s]: event DISCONNECT' % self.debugname)
        self.stop_command_channel()
        self.clear_connected()
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

    def _on_fsm_command_trying(self, _):
        if self.debuglevel > 0:
            print('[%s]: event COMMAND TRYING' % self.debugname)
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
    def command_uri(self):
        return self._command_channel.socket_uri

    @command_uri.setter
    def command_uri(self, value):
        self._command_channel.socket_uri = value

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

    def start_command_channel(self):
        self._command_channel.start()

    def stop_command_channel(self):
        self._command_channel.stop()

    # process all messages received on command
    def _command_channel_message_received(self, rx):

        # react to emccmd executed message
        if rx.type == pb.MT_EMCCMD_EXECUTED:
            self.emccmd_executed_received(rx)

        # react to emccmd completed message
        elif rx.type == pb.MT_EMCCMD_COMPLETED:
            self.emccmd_completed_received(rx)

        # react to error message
        elif rx.type == pb.MT_ERROR:
            # update error string with note
            self.error_string = ''
            for note in rx.note:
                self.error_string += note + '\n'

        for cb in self.on_command_message_received:
            cb(rx)

    def emccmd_executed_received(self, rx):
        print('SLOT emccmd executed unimplemented')

    def emccmd_completed_received(self, rx):
        print('SLOT emccmd completed unimplemented')

    def send_command_message(self, msg_type, tx):
        self._command_channel.send_socket_message(msg_type, tx)

    def send_emc_task_abort(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_ABORT, tx)

    def send_emc_task_plan_run(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_RUN, tx)

    def send_emc_task_plan_pause(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_PAUSE, tx)

    def send_emc_task_plan_step(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_STEP, tx)

    def send_emc_task_plan_resume(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_RESUME, tx)

    def send_emc_set_debug(self, tx):
        self.send_command_message(pb.MT_EMC_SET_DEBUG, tx)

    def send_emc_coolant_flood_on(self, tx):
        self.send_command_message(pb.MT_EMC_COOLANT_FLOOD_ON, tx)

    def send_emc_coolant_flood_off(self, tx):
        self.send_command_message(pb.MT_EMC_COOLANT_FLOOD_OFF, tx)

    def send_emc_axis_home(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_HOME, tx)

    def send_emc_axis_jog(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_JOG, tx)

    def send_emc_axis_abort(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_ABORT, tx)

    def send_emc_axis_incr_jog(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_INCR_JOG, tx)

    def send_emc_tool_load_tool_table(self, tx):
        self.send_command_message(pb.MT_EMC_TOOL_LOAD_TOOL_TABLE, tx)

    def send_emc_tool_update_tool_table(self, tx):
        self.send_command_message(pb.MT_EMC_TOOL_UPDATE_TOOL_TABLE, tx)

    def send_emc_task_plan_execute(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_EXECUTE, tx)

    def send_emc_coolant_mist_on(self, tx):
        self.send_command_message(pb.MT_EMC_COOLANT_MIST_ON, tx)

    def send_emc_coolant_mist_off(self, tx):
        self.send_command_message(pb.MT_EMC_COOLANT_MIST_OFF, tx)

    def send_emc_task_plan_init(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_INIT, tx)

    def send_emc_task_plan_open(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_OPEN, tx)

    def send_emc_task_plan_set_optional_stop(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_SET_OPTIONAL_STOP, tx)

    def send_emc_task_plan_set_block_delete(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_PLAN_SET_BLOCK_DELETE, tx)

    def send_emc_task_set_mode(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_SET_MODE, tx)

    def send_emc_task_set_state(self, tx):
        self.send_command_message(pb.MT_EMC_TASK_SET_STATE, tx)

    def send_emc_traj_set_so_enable(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_SO_ENABLE, tx)

    def send_emc_traj_set_fh_enable(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_FH_ENABLE, tx)

    def send_emc_traj_set_fo_enable(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_FO_ENABLE, tx)

    def send_emc_traj_set_max_velocity(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_MAX_VELOCITY, tx)

    def send_emc_traj_set_mode(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_MODE, tx)

    def send_emc_traj_set_scale(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_SCALE, tx)

    def send_emc_traj_set_rapid_scale(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_RAPID_SCALE, tx)

    def send_emc_traj_set_spindle_scale(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_SPINDLE_SCALE, tx)

    def send_emc_traj_set_teleop_enable(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_TELEOP_ENABLE, tx)

    def send_emc_traj_set_teleop_vector(self, tx):
        self.send_command_message(pb.MT_EMC_TRAJ_SET_TELEOP_VECTOR, tx)

    def send_emc_tool_set_offset(self, tx):
        self.send_command_message(pb.MT_EMC_TOOL_SET_OFFSET, tx)

    def send_emc_axis_override_limits(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_OVERRIDE_LIMITS, tx)

    def send_emc_spindle_constant(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_CONSTANT, tx)

    def send_emc_spindle_decrease(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_DECREASE, tx)

    def send_emc_spindle_increase(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_INCREASE, tx)

    def send_emc_spindle_off(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_OFF, tx)

    def send_emc_spindle_on(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_ON, tx)

    def send_emc_spindle_brake_engage(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_BRAKE_ENGAGE, tx)

    def send_emc_spindle_brake_release(self, tx):
        self.send_command_message(pb.MT_EMC_SPINDLE_BRAKE_RELEASE, tx)

    def send_emc_motion_set_aout(self, tx):
        self.send_command_message(pb.MT_EMC_MOTION_SET_AOUT, tx)

    def send_emc_motion_set_dout(self, tx):
        self.send_command_message(pb.MT_EMC_MOTION_SET_DOUT, tx)

    def send_emc_motion_adaptive(self, tx):
        self.send_command_message(pb.MT_EMC_MOTION_ADAPTIVE, tx)

    def send_emc_axis_set_max_position_limit(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_SET_MAX_POSITION_LIMIT, tx)

    def send_emc_axis_set_min_position_limit(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_SET_MIN_POSITION_LIMIT, tx)

    def send_emc_axis_unhome(self, tx):
        self.send_command_message(pb.MT_EMC_AXIS_UNHOME, tx)

    def send_shutdown(self, tx):
        self.send_command_message(pb.MT_SHUTDOWN, tx)

    def _command_channel_state_changed(self, state):

        if state == 'trying':
            if self._fsm.isstate('up'):
                self._fsm.command_trying()

        elif state == 'up':
            if self._fsm.isstate('trying'):
                self._fsm.command_up()
