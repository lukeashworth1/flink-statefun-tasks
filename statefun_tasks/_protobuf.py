from google.protobuf.wrappers_pb2 import DoubleValue, Int64Value, BoolValue, StringValue, BytesValue
from google.protobuf.any_pb2 import Any
from google.protobuf.message import Message
from .messages_pb2 import MapOfStringToAny, ArrayOfAny, TaskEntry, GroupEntry, TaskRetryPolicy, NoneValue, TaskRequest, \
    TaskResult, TaskException, TaskState, GroupResults, Pipeline, PipelineEntry, Address
from ._utils import _is_tuple
from typing import Union
 

_SCALAR_TYPE_MAP = {
    float: DoubleValue,
    int: Int64Value,
    bool: BoolValue,
    str: StringValue,
    bytes: BytesValue
}

_KNOWN_PROTO_TYPES = [
    # wrappers
    DoubleValue,
    Int64Value,
    BoolValue,
    StringValue,
    BytesValue,
    NoneValue,
    
    # flink task types
    MapOfStringToAny,
    ArrayOfAny,
    TaskEntry,
    GroupEntry,
    TaskRetryPolicy,
    TaskRequest,
    TaskResult,
    TaskException,
    TaskState,
    GroupResults,
    Pipeline, 
    PipelineEntry,
    #Address
]

def _wrap_value(v):
    # if none return NoneValue wrapper
    if v is None:
        return NoneValue()

    python_type = type(v)
    # wrap scalars in protobuf wrappers
    if python_type in _SCALAR_TYPE_MAP:
        mapped = _SCALAR_TYPE_MAP[python_type]()
        mapped.value = v
    # leave other protobufs alone
    elif isinstance(v, Message):
        mapped = v
    else:
        raise ValueError(f'Cannot wrap non-scalar {type(v)} in a protobuf.  Try converting to protobuf first.')

    return mapped

def _unwrap_value(v):
    # if NoneValue wrapper return None
    if isinstance(v, NoneValue):
        return None

    proto_type = type(v)
    # unwrap scalars in protobuf wrappers
    if proto_type in _SCALAR_TYPE_MAP.values():
        return v.value
    return v

def _wrap_any(value) -> Any:
    any = Any()
    any.Pack(value)
    return any

def _parse_any_from_bytes(bytes) -> Any:
    any = Any()
    any.ParseFromString(bytes)
    return any

def _is_wrapped_known_proto_type(value, known_proto_types):
    if isinstance(value, Any):
        return value.TypeName() in known_proto_types

    return False

def _unwrap_any(value, known_proto_types):
    if _is_wrapped_known_proto_type(value, known_proto_types):
        unwrapped = known_proto_types[value.TypeName()]()
        value.Unpack(unwrapped)
        return unwrapped

    return value


def _convert_to_proto(data) -> Union[MapOfStringToAny, ArrayOfAny, Message]:

    def convert(obj):
        if isinstance(obj, dict):
            proto = MapOfStringToAny()

            for k,v in obj.items():
                v = _wrap_any(convert(v))
                proto.items[k].CopyFrom(v)

            return proto
        elif isinstance(obj, list) or _is_tuple(obj):
            proto = ArrayOfAny()

            for v in obj:
                v = _wrap_any(convert(v))
                proto.items.append(v)

            return proto
        else:
            return _wrap_value(obj)

    return convert(data)


def _convert_from_proto(proto: Union[MapOfStringToAny, ArrayOfAny, Message], known_proto_types = []):

    # map of known proto types
    all_known_proto_types = {t.DESCRIPTOR.full_name: t for t in _KNOWN_PROTO_TYPES}
    all_known_proto_types.update({t.DESCRIPTOR.full_name: t for t in known_proto_types})

    def convert(obj):
        if isinstance(obj, MapOfStringToAny):
            output = {}

            for k,v in obj.items.items():
                v = convert(_unwrap_any(v, all_known_proto_types))
                output[k] = v
            
            return output

        elif isinstance(obj, ArrayOfAny):
            output = []

            for v in obj.items:
                v = convert(_unwrap_any(v, all_known_proto_types))
                output.append(v)

            return output

        elif isinstance(obj, Any):
            if _is_wrapped_known_proto_type(obj, all_known_proto_types):
                return convert(_unwrap_any(obj, all_known_proto_types))
            else:
                return obj # leave it as an any and go no futher with it
        else:    
            return _unwrap_value(obj)

    return convert(proto)