# Copyright 2025 QingWan (qingwanmail@foxmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
import socket
import struct
from dataclasses import dataclass
from enum import Enum

MSG_APIS = 3
CALL_ID_MASK = 0xffff
BROADCAST_RESULT_NO_HANDLER = -120

old_version = False


class short(int):
  pass


class byte(int):
  pass


class ByteEnum(byte, Enum):
  pass


class double(float):
  pass


class long(int):
  pass


@dataclass
class ResultRaw:
  result: int
  datas: bytes

  @staticmethod
  def parse_value(data, result):
    return ResultRaw(result, data)


class ServerReturnResult(ByteEnum):
  ERR_NO_SUPPORT = -4
  NO_HANDLE = -5
  HANDLE_EXCEPTION = -6


err_desc = {
  ServerReturnResult.ERR_NO_SUPPORT: "operation not support for method {}",
  ServerReturnResult.NO_HANDLE: "not find register handle method {}",
  ServerReturnResult.HANDLE_EXCEPTION: "occur exception when handle method {}"
}

void = type(None)


def rpc_api(fn):
  fn._api = True
  return fn


def broadcast_api(fn):
  fn._broadcast = True
  return fn


def rpc_send_data(sock, data, call_id, cmd):
  if cmd is None:
    cmd = 0
  if cmd < 0:
    cmd = 256 + cmd
  if data:
    len_result = len(data) + (cmd << 24)
    head = b'wq' + struct.pack('<HI', call_id, len_result)
    payload = b''.join([head, data])
  else:
    len_result = cmd << 24
    payload = b'wq' + struct.pack('<HI', call_id, len_result)
  total_sent = sock.send(payload)
  data_len = len(payload)
  if total_sent == data_len:
    return
  while total_sent < data_len:
    send = sock.send(payload[total_sent:])
    if send == 0:
      raise ConnectionError()
    total_sent += send


def safe_receive(sock, n):
  chunk = sock.recv(n)
  if not chunk:
    raise socket.error("Socket closed")
  count = len(chunk)
  if count == n:
    return chunk
  buff_list = [chunk]
  while count < n:
    chunk = sock.recv(n - count)
    if not chunk:
      raise socket.error("Socket closed")
    buff_list.append(chunk)
    count += len(chunk)
  return b"".join(buff_list)


def rpc_receive_data(sock):
  bs = safe_receive(sock, 8)
  if bs[:2] != b'wq':
    raise struct.error('wrong head:' + str(bs))
  idx, len_result = struct.unpack('<HI', bs[2:])
  data_len_expect = len_result & 0xffffff
  result = len_result >> 24
  if data_len_expect:
    data_len = data_len_expect
    buff_list = []
    while data_len > 0:
      bs = sock.recv(data_len)
      if not bs:
        raise socket.error('socket close')
      data_len -= len(bs)
      buff_list.append(bs)
    if len(buff_list) == 1:
      data = buff_list[0]
    else:
      data = b''.join(buff_list)
    if len(data) != data_len_expect:
      print("expect get data {},but get {}".format(data_len, len(data)))
  else:
    data = None
  if result >= 128:
    result -= 256
  return idx, result, data


def read_string(data, idx):
  str_len = data[idx + 0] + (data[idx + 1] << 8)
  if str_len == 0:
    return None, idx + 2
  if str_len == 0xffff:
    assert len(data) - idx > 0xffff
    for i in range(idx + 2 + 0xffff, len(data)):
      if data[i] == 0:
        str_len = i - idx - 2
        break
  s = data[idx + 2:idx + str_len + 2]
  try:
    s = s.decode()
  except:
    s = str(s)
  return s, idx + 2 + str_len + 1


def read_json(data, idx):
  s, idx = read_string(data, idx)
  try:
    return json.loads(s), idx
  except Exception as e:
    print('decode json fail', s, e)
  return s, idx


def read_int(data, idx):
  i, = struct.unpack('<i', data[idx:idx + 4])
  return i, idx + 4


def read_bool(data, idx):
  return True if data[idx] != 0 else False, idx + 1


def read_byte(data, idx):
  return data[idx], idx + 1


def put_byte(data):
  return bytes([data])


def read_float(data, idx):
  return struct.unpack('<f', data[idx:idx + 4])[0], idx + 4


def put_float(v: float):
  return struct.pack('<f', v)


def read_double(data, idx):
  return struct.unpack('<d', data[idx:idx + 8])[0], idx + 8


def put_double(v: float):
  return struct.pack('<d', v)


def read_long(data, idx):
  return struct.unpack('<q', data[idx:idx + 8])[0], idx + 8


def put_long(data):
  return struct.pack('<q', data)


def read_short(data, idx):
  return struct.unpack('<h', data[idx:idx + 2]), idx + 2


def put_int(i: int):
  return struct.pack('<i', i)


def put_bool(b: bool):
  if b:
    return b'\1'
  else:
    return b'\0'


def put_string(s: str):
  if s:
    s_len = len(s)
    if s_len > 0xffff:
      s_len = 0xffff
    b_len = struct.pack('<H', s_len)
    return b''.join([b_len, s.encode(), b'\0'])
  return b'\0\0'


def convert_int(cmd, idx, i: int):
  return cmd, idx, struct.pack('<i', i)


def convert_short(cmd, idx, i: int):
  return cmd, idx, struct.pack('<h', i)


def convert_bool(cmd, idx, b: bool):
  if b:
    return 1, idx, None
  else:
    return 0, idx, None


def convert_byte(cmd, idx, b: byte):
  return b, idx, None


def convert_bytes(cmd, idx, b: bytes):
  return cmd, idx, b


def convert_string(cmd, idx, s: str):
  if s:
    b_len = struct.pack('<H', len(s))
    return cmd, idx, b''.join([b_len, s.encode(), b'\0'])
  return cmd, idx, b'\0\0'


def convert_json(cmd, idx, o):
  return convert_string(cmd, idx, json.dumps(o, ensure_ascii=False, indent=1))


def put_bytes(b: bytes):
  if b:
    return struct.pack('<i', len(b)) + b
  return b'\0\0\0\0'


arg_convert_tables = {int: put_int, str: put_string, str | None: put_string, bytes: put_bytes, bool: put_bool,
                      float: put_float, double: put_double, byte: put_byte, long: put_long}

arg_read_tables = {int: read_int, str: read_string, str | None: read_string, byte: read_byte, bool: read_bool,
                   float: read_float, double: read_double, short: read_short, long: read_long, dict: read_json,
                   list: read_json}


class RpcException(Exception):
  pass


class WrongAnnotation(Exception):
  pass


class RpcCallException(RpcException):
  pass


class RpcCloseException(RpcException):
  pass


class RpcSendException(RpcException):
  pass


class BanRequestException(RpcException):
  pass


class JustReturn(object):
  def __init__(self, result):
    self.result = result


def create_call_function(arg_list, default_args):
  def __wrapper(client, *args):
    bs = []
    len_args = len(args)
    if len_args != len(arg_list):
      if len_args > len(arg_list):
        raise RuntimeError('too many arguments')
      if not default_args or len(default_args) + len_args < len(arg_list):
        raise RuntimeError('too few arguments')
      new_args = []
      new_args.extend(args)
      new_args.extend(default_args[(len_args - len(arg_list)):])
      args = new_args

    for i, arg in enumerate(args):
      bs.append(arg_list[i](arg))
    return b''.join(bs)

  return __wrapper


def create_receive_function(arg_list):
  def __wrapper(client, sock_data: bytes):
    args = []
    idx = 0
    for parser in arg_list:
      arg, idx = parser(sock_data, idx)
      args.append(arg)
    return args

  return __wrapper


def parse_bool(data, result):
  return result > 0


def parse_byte(data, result):
  return result


def parse_int(data, result):
  if result == -1:
    raise Exception
  return struct.unpack('<i', data)[0]


def parse_long(data, result):
  if result == -1:
    raise Exception
  return struct.unpack('<q', data)[0]


def parse_str(data, result):
  return read_string(data, 0)[0]


def parse_bytes(data, result):
  return data


def parse_dict(data, result):
  if not data:
    return {}
  d, _ = read_json(data, 0)
  assert isinstance(d, dict)
  return d


def parse_list(data, result):
  if not data:
    return []
  d, _ = read_json(data, 0)
  assert isinstance(d, list)
  return d


class EnumResultParser(object):
  def __init__(self, enum_type, parser):
    self.enum_type = enum_type
    self.parser = parser

  def __call__(self, data, result):
    return self.enum_type(self.parser(data, result))


class EnumResultReader(object):
  def __init__(self, enum_type, parser):
    self.enum_type = enum_type
    self.parser = parser

  def __call__(self, cmd, idx, data):
    return self.enum_type(self.parser(cmd, idx, data))


return_type_mappings = {bool: staticmethod(parse_bool), int: staticmethod(parse_int),
                        str: staticmethod(parse_str), bytes: staticmethod(parse_bytes),
                        dict: staticmethod(parse_dict), list: staticmethod(parse_list),
                        byte: staticmethod(parse_byte), long: staticmethod(parse_long),
                        void: void}

return_convert_mappings = {bool: staticmethod(convert_bool), int: staticmethod(convert_int),
                           str: staticmethod(convert_string), bytes: staticmethod(convert_bytes),
                           dict: staticmethod(convert_json), list: staticmethod(convert_json),
                           void: None, short: staticmethod(convert_short), byte: staticmethod(convert_byte),
                           }


def get_enum_real_type(t):
  while True:
    bases = t.__bases__
    for base in bases:
      if base in return_type_mappings:
        return base
    t = bases[0]
    if not issubclass(t, Enum):
      return t
