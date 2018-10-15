#!/usr/bin/env python
import sys
import os
import time
import threading
import curses

from machinekit import config
from pymachinetalk.dns_sd import ServiceDiscovery, ServiceDiscoveryFilter
from pymachinetalk.application import ApplicationStatus
from pymachinetalk.application import ApplicationCommand
from pymachinetalk.application import ApplicationError
from pymachinetalk.application import ApplicationFile
import pymachinetalk.application as application
import pymachinetalk.halremote as halremote

if sys.version_info >= (3, 0):
    import configparser
else:
    import ConfigParser as configparser


class TerminalUI(object):
    def __init__(self, uuid, use_curses, debug=False):
        sd_filter = ServiceDiscoveryFilter(txt_records={'uuid': uuid})
        self.sd = ServiceDiscovery(filter_=sd_filter)

        halrcomp = halremote.component('test')
        halrcomp.debug = debug
        halrcomp.newpin("coolant-iocontrol", halremote.HAL_BIT, halremote.HAL_IN)
        halrcomp.newpin("coolant", halremote.HAL_BIT, halremote.HAL_OUT)
        self.halrcomp = halrcomp
        self.sd.register(halrcomp)

        halrcomp2 = halremote.RemoteComponent(name='test2', debug=debug)
        halrcomp2.newpin("coolant-iocontrol", halremote.HAL_BIT, halremote.HAL_IN)
        halrcomp2.newpin("coolant", halremote.HAL_BIT, halremote.HAL_OUT)
        self.halrcomp2 = halrcomp2
        self.sd.register(halrcomp2)

        self.status = ApplicationStatus(debug=debug)
        self.status.on_synced_changed.append(self._on_status_synced)
        self.sd.register(self.status)
        self.command = ApplicationCommand(debug=debug)
        self.sd.register(self.command)
        self.error = ApplicationError(debug=debug)
        self.sd.register(self.error)
        self.fileservice = ApplicationFile(debug=debug)
        self.fileservice.local_file_path = 'test.ngc'
        self.fileservice.local_path = './ngc/'
        self.fileservice.remote_path = '/home/xy/'
        self.fileservice.remote_file_path = '/home/xy/test.ngc'
        self.fileservice.on_ready_changed.append(self._on_fileservice_ready)
        self.sd.register(self.fileservice)

        self.timer = None
        self.timer_interval = 0.1

        self.use_curses = use_curses
        if not self.use_curses:
            return

        self.messages = []

        self.screen = curses.initscr()
        self.screen.keypad(True)
        self.dro_window = curses.newwin(10, 40, 1, 2)
        self.status_window = curses.newwin(10, 40, 1, 44)
        self.command_window = curses.newwin(10, 40, 1, 86)
        self.connection_window = curses.newwin(10, 80, 12, 2)
        self.error_window = curses.newwin(20, 120, 12, 84)
        self.file_window = curses.newwin(10, 80, 1, 108)
        curses.noecho()
        curses.cbreak()

    def _on_status_synced(self, synced):
        if synced:
            self.timer = threading.Timer(self.timer_interval, self.status_timer_tick)
            self.timer.start()
        else:
            if self.timer:
                self.timer.cancel()
                self.timer = None

    def _on_fileservice_ready(self, ready):
        if ready:
            print('fileservice ready')
            self.fileservice.refresh_files()
            self.fileservice.wait_completed()
            print(self.fileservice.file_list)
            self.fileservice.remove_file('test.ngc')
            self.fileservice.wait_completed()

    def status_timer_tick(self):
        # if self.status.synced:
        # print('flood %s' % self.status.io.flood)
        if self.use_curses:
            self.update_screen()
        self.timer = threading.Timer(self.timer_interval, self.status_timer_tick)
        self.timer.start()

    def toggle_pin(self):
        self.halrcomp['coolant'] = not self.halrcomp['coolant']
        return True

    def update_screen(self):
        con = self.connection_window
        con.clear()
        con.border(0)
        con.addstr(1, 2, 'Connection')
        con.addstr(
            3, 4, 'Status: %s %s' % (str(self.status.synced), self.status.status_uri)
        )
        con.addstr(
            4,
            4,
            'Command: %s %s' % (str(self.command.connected), self.command.command_uri),
        )
        con.addstr(
            5, 4, 'Error: %s %s' % (str(self.error.connected), self.error.error_uri)
        )
        con.refresh()

        if not self.status.synced or not self.command.connected:
            return

        dro = self.dro_window
        dro.clear()
        dro.border(0)
        dro.addstr(1, 2, "DRO")
        for i, n in enumerate(['x', 'y', 'z']):  # range(self.status.config.axes):
            pos = str(getattr(self.status.motion.position, n))
            dro.addstr(3 + i, 4, '%s: %s' % (n, pos))
        dro.refresh()

        status = self.status_window
        status.clear()
        status.border(0)
        status.addstr(1, 2, 'Status')
        status.addstr(
            3,
            4,
            'Estop: %s'
            % str(self.status.task.task_state == application.EMC_TASK_STATE_ESTOP),
        )
        status.addstr(
            4,
            4,
            'Power: %s'
            % str(self.status.task.task_state == application.EMC_TASK_STATE_ON),
        )
        status.refresh()

        cmd = self.command_window
        cmd.clear()
        cmd.border(0)
        cmd.addstr(1, 2, 'Command')
        cmd.addstr(3, 4, 'Estop - F1')
        cmd.addstr(4, 4, 'Power - F2')
        cmd.refresh()

        error = self.error_window
        error.clear()
        error.border(0)
        error.addstr(1, 2, 'Notifications')
        self.messages += self.error.get_messages()
        pos = 0
        for message in self.messages:
            # msg_type = str(message['type'])
            for note in message['notes']:
                error.addstr(3 + pos, 4, str(note))
                pos += 1
        error.refresh()

        win = self.file_window
        win.clear()
        win.border(0)
        win.addstr(1, 2, 'File')
        win.addstr(3, 4, 'Status: %s' % self.fileservice.transfer_state)
        win.addstr(4, 4, 'Progress: %f' % self.fileservice.progress)
        win.refresh()

        self.screen.nodelay(True)
        c = self.screen.getch()
        if c == curses.KEY_F1:
            if self.status.task.task_state == application.EMC_TASK_STATE_ESTOP:
                ticket = self.command.set_task_state(
                    application.EMC_TASK_STATE_ESTOP_RESET
                )
                self.command.wait_completed(ticket=ticket, timeout=0.2)
            else:
                self.command.set_task_state(application.EMC_TASK_STATE_ESTOP)
                self.command.wait_completed(timeout=0.2)
        elif c == curses.KEY_F2:
            if self.status.task.task_state == application.EMC_TASK_STATE_ON:
                self.command.set_task_state(application.EMC_TASK_STATE_OFF)
            else:
                self.command.set_task_state(application.EMC_TASK_STATE_ON)
        elif c == curses.KEY_F3:
            self.fileservice.start_upload()

    def start(self):
        self.sd.start()

    def stop(self):
        self.sd.stop()

        if self.timer:
            self.timer.cancel()

        if self.use_curses:
            curses.endwin()


def main():
    mkconfig = config.Config()
    mkini = os.getenv("MACHINEKIT_INI")
    if mkini is None:
        mkini = mkconfig.MACHINEKIT_INI
    if not os.path.isfile(mkini):
        sys.stderr.write("MACHINEKIT_INI " + mkini + " does not exist\n")
        sys.exit(1)

    mki = configparser.ConfigParser()
    mki.read(mkini)
    uuid = mki.get("MACHINEKIT", "MKUUID")

    ui = TerminalUI(uuid=uuid, use_curses=True)
    ui.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print("stopping threads")
    ui.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.5)

    print("threads stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
