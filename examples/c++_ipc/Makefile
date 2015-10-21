PROTOC_INCLUDE := --proto_path=. \
	--proto_path=/usr/include

all:	ipcmsg_pb2.py c++parse

%_pb2.py:	%.proto
	protoc   $(PROTOC_INCLUDE) --python_out=. $<


%.pb.cc:	%.proto
	protoc   $(PROTOC_INCLUDE) --cpp_out=. $<

clean:
	rm -f ipcmsg_pb2.py ipcmsg.pb.* ipc-client *.o *.pyc

c++parse: ipcmsg.pb.cc cppmain.cc
	g++ $^ $(CXXFLAGS) -o ipc-client  $(PROTOBUF_LIBS) $(JANSSON_LIBS) -lstdc++ -lzmq -lprotobuf
