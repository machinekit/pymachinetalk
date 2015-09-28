#!/usr/bin/env python
import sys
import os
import time
import signal
import gobject
import gevent.monkey; gevent.monkey.patch_all()
import threading

from machinekit import config
from dns_sd import ServiceDiscovery
from application import ApplicationStatus
import halremote

if sys.version_info >= (3, 0):
    import configparser
else:
    import ConfigParser as configparser


def idle(loop):
    try:
        gevent.sleep(0.1)
    except:
        loop.quit()
        #gtk.main_quit()
        #gevent.hub.MAIN.throw(*sys.exc_info())
    return True


shutdown = False


def _exitHandler(signum, frame):
    del signum
    del frame
    global shutdown
    shutdown = True
    print("handled")


# register exit signal handlers
def register_exit_handler():
    signal.signal(signal.SIGINT, _exitHandler)
    signal.signal(signal.SIGTERM, _exitHandler)


def check_exit():
    global shutdown
    return shutdown


class TestClass():
    def __init__(self, uuid):
        self.halrcmdReady = False
        self.halrcompReady = False

        halrcomp = halremote.HalRemoteComponent(name='test')
        halrcomp.newpin("coolant-iocontrol", halremote.HAL_BIT, halremote.HAL_IN)
        halrcomp.newpin("coolant", halremote.HAL_BIT, halremote.HAL_OUT)
        self.halrcomp = halrcomp

        halrcomp2 = halremote.HalRemoteComponent(name='test2')
        halrcomp2.newpin("coolant-iocontrol", halremote.HAL_BIT, halremote.HAL_IN)
        halrcomp2.newpin("coolant", halremote.HAL_BIT, halremote.HAL_OUT)
        self.halrcomp2 = halrcomp2

        self.status = ApplicationStatus()

        halrcmd_sd = ServiceDiscovery(service_type="_halrcmd._sub._machinekit._tcp", uuid=uuid)
        halrcmd_sd.discovered_callback = self.halrcmd_discovered
        halrcmd_sd.start()
        #halrcmd_sd.disappered_callback = disappeared
        self.halrcmd_sd = halrcmd_sd

        halrcomp_sd = ServiceDiscovery(service_type="_halrcomp._sub._machinekit._tcp", uuid=uuid)
        halrcomp_sd.discovered_callback = self.halrcomp_discovered
        halrcomp_sd.start()
        self.harcomp_sd = halrcomp_sd

        status_sd = ServiceDiscovery(service_type="_status._sub._machinekit._tcp", uuid=uuid)
        status_sd.discovered_callback = self.status_discovered
        status_sd.disappeared_callback = self.status_disappeared
        status_sd.start()
        self.status_sd = status_sd

    def start_halrcomp(self):
        print('connecting rcomp %s' % self.halrcomp.name)
        self.halrcomp.ready()
        self.halrcomp2.ready()
        #gevent.spawn(self.start_timer)

    def halrcmd_discovered(self, name, dsn):
        print("discovered %s %s" % (name, dsn))
        self.halrcomp.halrcmdUri = dsn
        self.halrcomp2.halrcmdUri = dsn
        self.halrcmdReady = True
        if self.halrcompReady:
            self.start_halrcomp()

    def halrcomp_discovered(self, name, dsn):
        print("discovered %s %s" % (name, dsn))
        self.halrcomp.halrcompUri = dsn
        self.halrcomp2.halrcompUri = dsn
        self.halrcompReady = True
        if self.halrcmdReady:
            self.start_halrcomp()

    def status_discovered(self, name, dsn):
        print('discovered %s %s' % (name, dsn))
        self.status.status_uri = dsn
        self.status.ready()
        gevent.spawn(self.status_timer)

    def status_disappeared(self, name):
        print('%s disappeared' % name)
        self.status.stop()

    def start_timer(self):
        while True:
            gevent.sleep(1.0)
            self.toggle_pin()
        #glib.timeout_add(1000, self.toggle_pin)

    def status_timer(self):
        while True:
            if self.status.synced:
                print('flood %s' % self.status.io.flood)
            gevent.sleep(1.0)

    def toggle_pin(self):
        self.halrcomp['coolant'] = not self.halrcomp['coolant']
        return True

    def stop(self):
        if self.halrcomp is not None:
            self.halrcomp.stop()
        if self.halrcomp2 is not None:
            self.halrcomp2.stop()
        if self.status is not None:
            self.status.stop()


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
    # remote = mki.getint("MACHINEKIT", "REMOTE")

    #register_exit_handler()
    test = TestClass(uuid=uuid)
    loop = gobject.MainLoop()
    gobject.idle_add(idle, loop)
    try:
        loop.run()
    except:
        loop.quit()

    # while dns_sd.running and not check_exit():
    #     time.sleep(1)

    print("stopping threads")
    test.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
