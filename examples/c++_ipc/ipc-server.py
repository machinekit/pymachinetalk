#!/usr/bin/env python
import sys
import os
import time
import gobject
import threading
import zmq

# Machinekit specific, can only use on local machine
from machinekit import config
# Machinetalk bindings
from dns_sd import ServiceDiscovery
import application
from application import ApplicationStatus
from application import ApplicationCommand

from ipcmsg_pb2 import *


if sys.version_info >= (3, 0):
    import configparser
else:
    import ConfigParser as configparser


class IPCServer():
    def __init__(self, uuid, debug=True):
        self.debug = debug
        self.threads = []
        self.shutdown = threading.Event()
        self.status = ApplicationStatus()
        self.command = ApplicationCommand()

        status_sd = ServiceDiscovery(service_type="_status._sub._machinekit._tcp", uuid=uuid)
        status_sd.on_discovered.append(self.status_discovered)
        status_sd.on_disappeared.append(self.status_disappeared)
        status_sd.start()
        self.status_sd = status_sd

        command_sd = ServiceDiscovery(service_type="_command._sub._machinekit._tcp", uuid=uuid)
        command_sd.on_discovered.append(self.command_discovered)
        command_sd.on_disappeared.append(self.command_disappeared)
        command_sd.start()

        # create ipc sockets
        context = zmq.Context()
        context.linger = 0
        self.context = context
        # self.pubSocket = context.socket(zmq.PUB)
        # self.pubSocket.bind('ipc://machinetalk-server.ipc')
        # self.pubDsname = self.pubSocket.get_string(zmq.LAST_ENDPOINT, encoding='utf-8')
        # if self.debug:
        #     print('bound PUB socket to %s' % self.pubDsname)
        self.zmqSocket = context.socket(zmq.ROUTER)
        self.zmqSocket.bind('ipc://machinetalk-server.ipc')
        self.zmqDsname = self.zmqSocket.get_string(zmq.LAST_ENDPOINT, encoding='utf-8')
        if self.debug:
            print('bound ROUTER socket to %s' % self.zmqDsname)
        self.zmqLock = threading.Lock()

        self.tx = Message()
        self.rx = Message()

        self.threads.append(threading.Thread(target=self.socket_worker))
        for thread in self.threads:
            thread.start()

    def send_msg(self, identity, msg_type):
        with self.zmqLock:
            self.tx.type = msg_type
            txBuffer = self.tx.SerializeToString()
            self.zmqSocket.send_multipart([identity, txBuffer], zmq.NOBLOCK)
            self.tx.Clear()

    def socket_worker(self):
        poll = zmq.Poller()
        poll.register(self.zmqSocket, zmq.POLLIN)

        while not self.shutdown.is_set():
            s = dict(poll.poll(200))
            if self.zmqSocket in s and s[self.zmqSocket] == zmq.POLLIN:
                self.process_msg(self.zmqSocket)

    def process_msg(self, socket):
        (identity, message) = socket.recv_multipart()
        self.rx.ParseFromString(message)

        if self.debug:
            print("process message called, id: %s" % identity)
            print(str(self.rx))

        if self.rx.type == IPC_POSITION:
            self.tx.x = self.status.motion.position.x - \
                        self.status.motion.g5x_offset.x - \
                        self.status.motion.g92_offset.x - \
                        self.status.io.tool_offset.x
            self.tx.y = self.status.motion.position.y - \
                        self.status.motion.g5x_offset.y - \
                        self.status.motion.g92_offset.y - \
                        self.status.io.tool_offset.y
            self.send_msg(identity, IPC_POSITION)

        elif self.rx.type == IPC_JOG:
            self.command.set_task_mode(application.TASK_MODE_MANUAL)
            self.command.jog(self.rx.jog_type, self.rx.axis,
                             self.rx.velocity, self.rx.distance)

        elif self.rx.type == IPC_CONNECTED:
            self.tx.connected = self.status.synced and self.command.connected
            self.send_msg(identity, IPC_CONNECTED)

    def status_discovered(self, name, dsn):
        if self.debug:
            print('discovered %s %s' % (name, dsn))
        self.status.status_uri = dsn
        self.status.ready()
        #self.timer = threading.Timer(0.1, self.status_timer)
        #self.timer.start()

    def status_disappeared(self, name):
        if self.debug:
            print('%s disappeared' % name)
        self.status.stop()

    def command_discovered(self, name, dsn):
        if self.debug:
            print('discovered %s %s' % (name, dsn))
        self.command.command_uri = dsn
        self.command.ready()

    def command_disappeared(self, name):
        if self.debug:
            print('%s disappeared' % name)
        self.command.stop()

    def stop(self):
        if self.status is not None:
            self.status.stop()
        if self.command is not None:
            self.command.stop()
        self.shutdown.set()
        for thread in self.threads:
            thread.join()
        self.threads = []


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

    gobject.threads_init()  # important: initialize threads if gobject main loop is used
    #register_exit_handler()
    ipcServer = IPCServer(uuid=uuid)
    loop = gobject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()

    # while dns_sd.running and not check_exit():
    #     time.sleep(1)

    print("stopping threads")
    ipcServer.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
