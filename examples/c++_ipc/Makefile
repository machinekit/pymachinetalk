PROTOC_INCLUDE := --proto_path=. \
	--proto_path=/usr/include

all:	ipcmsg_pb2.py c++parse

%_pb2.py:	%.proto
	protoc   $(PROTOC_INCLUDE) --python_out=. $<


%.pb.cc:	%.proto
	protoc   $(PROTOC_INCLUDE) --cpp_out=. $<

clean:
	rm -f ipcmsg_pb2.py ipcmsg.pb.* ipc-client *.o *.pyc

# show various output formats of serialisation
pydemo:	ipcmsg_pb2.py
	python pydemo.py text	# stock protobuf text representation
	python pydemo.py hex   # wire format hex dump
	python pydemo.py json  # autoconvert into JSON
	python pydemo.py binary | od -cx  # wire format

# show how to parse those in c++
cppdemo:	ipcmsg_pb2.py c++parse
	python pydemo.py binary | ./c++parse binary
	python pydemo.py text   | ./c++parse text
	python pydemo.py json   | ./c++parse json

c++parse: ipcmsg.pb.cc cppmain.cc
	g++ $^ $(CXXFLAGS) -o ipc-client  $(PROTOBUF_LIBS) $(JANSSON_LIBS) -lstdc++ -lzmq -lprotobuf
