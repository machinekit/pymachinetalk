#!/usr/bin/env python
# coding=utf-8
from pymachinetalk.application import ApplicationCommand, EMC_TASK_STATE_ESTOP_RESET, EMC_TASK_STATE_OFF

from pymachinetalk.dns_sd import ServiceDiscovery

MAX_WAIT_CONNECTED = 5.0
COMMAND_TIMEOUT = 0.5
DEBUG = False


def print_state(state):
    print('command state: {}'.format(state))


def get_out_of_estop():
    sd = ServiceDiscovery()
    command = ApplicationCommand(debug=DEBUG)
    if DEBUG:
        command.on_state_changed.append(print_state)
    sd.register(command)
    sd.start()

    connected = command.wait_connected(timeout=MAX_WAIT_CONNECTED)
    if not connected:
        raise RuntimeError('Could not connect')
    else:
        print('connected')

    print('executing ESTOP reset')
    ticket = command.set_task_state(EMC_TASK_STATE_ESTOP_RESET)
    if not command.wait_completed(ticket=ticket, timeout=COMMAND_TIMEOUT):
        raise RuntimeError('Task did not complete')
    else:
        print('done')

    print('executing TASK STATE ON')
    command.set_task_state(EMC_TASK_STATE_OFF)
    if not command.wait_completed(timeout=COMMAND_TIMEOUT):
        raise RuntimeError('Task did not complete')
    else:
        print('done')


if __name__ == '__main__':
    get_out_of_estop()
