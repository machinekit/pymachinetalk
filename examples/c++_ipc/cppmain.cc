#include <zmq.hpp> // https://github.com/zeromq/cppzmq
#include "ipcmsg.pb.h" // protobuf message
#include <stdio.h>
#include <sstream>
#include <unistd.h>

void send_message(zmq::socket_t *socket, pb::Message *msg) {
    std::string msg_str;
    zmq::message_t message;

    msg->SerializeToString(&msg_str);
    message.rebuild(msg_str.length());
    memcpy(message.data(), (void*)msg_str.c_str(), msg_str.length());
    socket->send(message);
    msg->Clear();
}

void recv_message(zmq::socket_t *socket, pb::Message *msg)
{
    zmq::message_t message;
    socket->recv(&message);
    std::istringstream iss(static_cast<char*>(message.data()));
    msg->ParseFromIstream(&iss);
}

int main (int argc, char *argv[])
{
    // Verify that the version of the library that we linked against is
    // compatible with the version of the headers we compiled against.
    GOOGLE_PROTOBUF_VERIFY_VERSION;

    zmq::context_t context(1);
    pb::Message tx, rx;

    //  Socket to send messages to
    char identity[25] = {};
    sprintf(identity, "machinetalk-ipc-%i", getpid());
    zmq::socket_t socket(context, ZMQ_DEALER);
    socket.setsockopt(ZMQ_IDENTITY, identity, strlen(identity));
    socket.connect("ipc://machinetalk-server.ipc");

    // get connection status
    tx.set_type(pb::IPC_CONNECTED);
    send_message(&socket, &tx);
    recv_message(&socket, &rx);
    printf("connection status %i\n", rx.connected());

    // get current position
    tx.set_type(pb::IPC_POSITION);
    send_message(&socket, &tx);
    recv_message(&socket, &rx);
    printf("position X:%f Y:%f\n", rx.x(), rx.y());

    // jog around
    tx.set_type(pb::IPC_JOG);
    tx.set_jog_type(pb::JOG_INCREMENTAL);
    tx.set_axis(0);
    tx.set_velocity(0.1);
    tx.set_distance(0.1);
    send_message(&socket, &tx);

    return 0;
}
