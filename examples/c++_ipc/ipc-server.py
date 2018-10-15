#!/usr/bin/env python
import sys
import os
import time
import threading
import zmq

# Machinekit specific, can only use on local machine
from machinekit import config

# Machinetalk bindings
from pymachinetalk.dns_sd import ServiceDiscovery, ServiceDiscoveryFilter
from pymachinetalk.application import ApplicationStatus
from pymachinetalk.application import ApplicationCommand
import pymachinetalk.application as application

from ipcmsg_pb2 import *


if sys.version_info >= (3, 0):
    import configparser
else:
    import ConfigParser as configparser


class IPCServer:
    def __init__(self, uuid, debug=True):
        self.debug = debug
        self.threads = []
        self.shutdown = threading.Event()
        sd_filter = ServiceDiscoveryFilter(txt_records={'uuid': uuid})
        self.sd = ServiceDiscovery(filter_=sd_filter)
        self.status = ApplicationStatus()
        self.command = ApplicationCommand()
        self.sd.register(self.status)
        self.sd.register(self.command)

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

        self._tx = Message()
        self._rx = Message()

        self.threads.append(threading.Thread(target=self.socket_worker))
        for thread in self.threads:
            thread.start()

    def send_msg(self, identity, msg_type):
        with self.zmqLock:
            self._tx.type = msg_type
            txBuffer = self._tx.SerializeToString()
            self.zmqSocket.send_multipart([identity, txBuffer], zmq.NOBLOCK)
            self._tx.Clear()

    def socket_worker(self):
        poll = zmq.Poller()
        poll.register(self.zmqSocket, zmq.POLLIN)

        while not self.shutdown.is_set():
            s = dict(poll.poll(200))
            if self.zmqSocket in s and s[self.zmqSocket] == zmq.POLLIN:
                self.process_msg(self.zmqSocket)

    def process_msg(self, socket):
        (identity, message) = socket.recv_multipart()
        self._rx.ParseFromString(message)

        if self.debug:
            print("process message called, id: %s" % identity)
            print(str(self._rx))

        if self._rx.type == IPC_POSITION:
            self._tx.x = (
                self.status.motion.position.x
                - self.status.motion.g5x_offset.x
                - self.status.motion.g92_offset.x
                - self.status.io.tool_offset.x
            )
            self._tx.y = (
                self.status.motion.position.y
                - self.status.motion.g5x_offset.y
                - self.status.motion.g92_offset.y
                - self.status.io.tool_offset.y
            )
            self.send_msg(identity, IPC_POSITION)

        elif self._rx.type == IPC_JOG:
            self.command.set_task_mode(application.EMC_TASK_MODE_MANUAL)
            self.command.jog(
                self._rx.jog_type, self._rx.axis, self._rx.velocity, self._rx.distance
            )

        elif self._rx.type == IPC_CONNECTED:
            self._tx.connected = self.status.synced and self.command.connected
            self.send_msg(identity, IPC_CONNECTED)

    def start(self):
        self.sd.start()

    def stop(self):
        self.sd.stop()
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

    ipcServer = IPCServer(uuid=uuid)
    ipcServer.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print("stopping threads")
    ipcServer.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
