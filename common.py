

class MessageObject():
    def __init__(self):
        self.is_position = False

    def __str__(self):
        output = ''
        for attr in dir(self)[3:]:
            output += '%s: %s\n' % (attr, getattr(self, attr))
        return output

    def __getitem__(self, index):
        if self.is_position:
            mapping = ['x', 'y', 'z', 'a', 'b', 'c', 'u', 'v', 'w']
            return getattr(self, mapping[index])
        else:
            raise RuntimeError("Object does not support indexed access")


def recurse_descriptor(descriptor, obj):
    for field in descriptor.fields:
        value = None

        if field.type == field.TYPE_BOOL:
            value = False
        elif field.type == field.TYPE_DOUBLE \
        or field.type == field.TYPE_FLOAT:
            value = 0.0
        elif field.type == field.TYPE_INT32 \
        or field.type == field.TYPE_INT64 \
        or field.type == field.TYPE_UINT32 \
        or field.type == field.TYPE_UINT64:
            value = 0
        elif field.type == field.TYPE_STRING:
            value = ''
        elif field.type == field.TYPE_ENUM:
            value = 0
        elif field.type == field.TYPE_MESSAGE:
            value = MessageObject()
            msg_descriptor = field.message_type
            if msg_descriptor.name == 'Position':
                value.is_position = True
            recurse_descriptor(msg_descriptor, value)

        if field.label == field.LABEL_REPEATED:
            delattr(value, 'index')
            attributes = dir(value)
            if len(attributes) == 4:  # only single attribute
                value = getattr(value, attributes[-1])
            value = [value]

        setattr(obj, field.name, value)


def recurse_message(message, obj, field_filter=''):
    for descriptor in message.DESCRIPTOR.fields:
        filter_enabled = field_filter != ''
        # TODO: handle special file case here...

        if filter_enabled and descriptor.name != field_filter:
            continue

        if descriptor.label != descriptor.LABEL_REPEATED:
            if message.HasField(descriptor.name):
                if descriptor.type == descriptor.TYPE_MESSAGE:
                    sub_obj = getattr(obj, descriptor.name)
                    recurse_message(getattr(message, descriptor.name), sub_obj)
                else:
                    setattr(obj, descriptor.name, getattr(message, descriptor.name))
        else:
            if descriptor.type == descriptor.TYPE_MESSAGE:
                array = getattr(obj, descriptor.name)
                repeated = getattr(message, descriptor.name)
                for sub_message in repeated:
                    index = sub_message.index

                    while len(array) < (index + 1):
                        array.append(MessageObject())

                    value = None
                    if len(sub_message.DESCRIPTOR.fields) == 2:
                        sub_obj = MessageObject()
                        recurse_message(sub_message, sub_obj)
                        delattr(sub_obj, 'index')
                        value = getattr(sub_obj, dir(sub_obj)[-1])
                    else:
                        sub_obj = array[index]
                        recurse_message(sub_message, sub_obj)
                        delattr(sub_obj, 'index')
                        value = sub_obj
                    array[index] = value
