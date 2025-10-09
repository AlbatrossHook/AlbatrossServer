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
import select
import socket
import struct
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from .wrapper import cached_subclass_property

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


def rpc_send_data(sock, data, call_id, cmd):
  if cmd is None:
    cmd = 0
  if cmd < 0:
    cmd = 256 + cmd
  if data:
    len_result = len(data) + (cmd << 24)
    head = b'wq' + struct.pack('<HI', call_id, len_result)
    sock.send(b''.join([head, data]))
  else:
    len_result = cmd << 24
    head = b'wq' + struct.pack('<HI', call_id, len_result)
    sock.send(head)


def rpc_receive_data(sock):
  bs = sock.recv(8)
  if not bs:
    raise RpcCloseException("not get head data")
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
  s = data[idx + 2:idx + str_len + 2]
  return s.decode(), idx + 2 + str_len + 1


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
    b_len = struct.pack('<H', len(s))
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


class AlbRpcMethod(object):
  parser = None

  def __init__(self, client, name, rpc_id, handler, parser):
    self.client = client
    self.name = name
    self.rpc_id = rpc_id
    self.handler = handler
    if parser:
      self.parser = parser

  def __call__(self, *args, hint=None, timeout=None, silence=False, **kwargs):
    client = self.client
    method_name = self.name
    if client.prohibit_request:
      raise BanRequestException('forbid request {} this time'.format(method_name))
    assert not kwargs
    call_counter = client.call_counter
    method_id = call_counter & CALL_ID_MASK
    client.call_counter = call_counter + 1
    rpc_name = client.name
    if silence:
      quiet = True
    else:
      quiet = client.quiet
    if not quiet:
      method_id_name = method_name + "|" + str(method_id)
      if hint:
        print("request method:", method_id_name, args, hint)
      else:
        print("request method:", method_id_name, args)
    else:
      method_id_name = None
    content = self.handler(*args)
    sock = client.sock
    if timeout:
      sock.settimeout(timeout)
    if content and not isinstance(content, bytes):
      if isinstance(content, JustReturn):
        return content.result
      content = str(content).encode()
    request_lock = client.request_lock
    # if request_lock:
    send_exception = None
    idx, result, data = None, None, None
    get_lock = request_lock.acquire(True, timeout=client.request_lock_wait_time)
    start = time.time()
    client.last_request_time = start
    parser = self.parser
    try:
      rpc_send_data(sock, content, method_id, self.rpc_id)
      if parser != void:
        idx, result, data = rpc_receive_data(sock)
        while idx < method_id:
          idx, result, data = rpc_receive_data(sock)
    except BaseException as e:
      send_exception = e
    if get_lock:
      request_lock.release()
    if send_exception:
      raise send_exception
    end = time.time()
    if parser == void:
      if not quiet:
        print("response %s[%.2f]:" % (method_id_name, (end - start)), 'no return', rpc_name)
      return
    if idx != method_id:
      desc = f'rpc {rpc_name} {method_name} response wrong idx except {method_id},got {idx} in {threading.current_thread().name}'
      print(desc)
    if result < 0:
      err_fmt = err_desc.get(result)
      if err_fmt:
        err_fmt = err_fmt.format(method_name)
        if data:
          # err_detail, _ = read_string(data, 0)
          err_detail = data.decode()
          if err_detail:
            err_fmt += ",detail:" + err_detail
        raise RpcCallException(err_fmt)
      pass
    if parser:
      data = parser(data, result)
    elif data is None:
      data = result >= 0
    if not quiet:
      print("response %s[%.2f]:" % (method_id_name, (end - start)), str(data)[:128], rpc_name)
    if timeout:
      sock.settimeout(client.default_timeout)
    return data


def rpc_api(fn):
  fn._api = True
  return fn


def broadcast_api(fn):
  fn._broadcast = True
  return fn


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


class RpcMeta(type):

  def __new__(mcs, cls_name, bases, attrs):
    call_tables = {}
    broadcast_tables = {}
    for key, attr_value in attrs.items():
      if callable(attr_value):
        is_api = hasattr(attr_value, '_api')
        if is_api:
          annotations = attr_value.__annotations__
          default_args = attr_value.__defaults__
          args = []
          ret_f = None
          argcount = attr_value.__code__.co_argcount
          if 'return' in annotations:
            if argcount != len(annotations):
              raise WrongAnnotation('all argument should mark type')
          elif argcount != len(annotations) + 1:
            raise WrongAnnotation('all argument should mark type')
          for name, arg_type in annotations.items():
            arg_type_str = str(arg_type)
            if 'str | None' == arg_type_str:
              arg_type = str
            if name == 'return':
              ret_f = attrs.get('parse_' + key, None)
              if ret_f is not None:
                if ret_f.__class__.__name__ == 'function':
                  ret_f = staticmethod(ret_f)
              elif issubclass(arg_type, Enum):
                real_type = get_enum_real_type(arg_type)
                ret_f = EnumResultParser(arg_type, return_type_mappings[real_type])
              elif arg_type in return_type_mappings:
                ret_f = return_type_mappings[arg_type]
              elif hasattr(arg_type, 'parse_value'):
                ret_f = getattr(arg_type, 'parse_value')
                if ret_f.__class__.__name__ == 'function':
                  ret_f = staticmethod(ret_f)
              break
            if issubclass(arg_type, Enum):
              arg_type = get_enum_real_type(arg_type)
            args.append(arg_convert_tables[arg_type])
          f = create_call_function(args, default_args)
          f.__name__ = attr_value.__name__
          call_tables[key] = (f, ret_f)
        elif hasattr(attr_value, '_broadcast'):
          annotations = attr_value.__annotations__
          args = []
          ret_f = None
          argcount = attr_value.__code__.co_argcount
          if 'return' in annotations:
            if argcount != len(annotations):
              raise WrongAnnotation(f'api {key} all argument should mark type')
          elif argcount != len(annotations) + 1:
            raise WrongAnnotation(f'function {key} all argument should mark type')
          for name, arg_type in annotations.items():
            arg_type_str = str(arg_type)
            if 'str | None' == arg_type_str:
              arg_type = str
            if name == 'return':
              if arg_type in return_convert_mappings:
                ret_f = return_convert_mappings[arg_type]
              elif issubclass(arg_type, Enum):
                base_type = get_enum_real_type(arg_type)
                ret_f = return_convert_mappings[base_type]
              elif hasattr(arg_type, 'covert_value'):
                ret_f = getattr(arg_type, 'covert_value')
                if ret_f.__class__.__name__ == 'function':
                  ret_f = staticmethod(ret_f)
              break
            if issubclass(arg_type, Enum):
              real_type = get_enum_real_type(arg_type)
              reader = EnumResultReader(arg_type, arg_read_tables[real_type])
              args.append(reader)
            else:
              args.append(arg_read_tables[arg_type])
          f = create_receive_function(args)
          f.__name__ = attr_value.__name__
          broadcast_tables[key] = (f, ret_f)

    for key, (f, ret_f) in call_tables.items():
      ori_f = attrs.pop(key)
      attrs['call_' + key] = f
      if ret_f is not None:
        attrs['parse_' + key] = ret_f
    for key, (f, ret_f) in broadcast_tables.items():
      ori_f = attrs.pop(key)
      attrs['receive_' + key] = f
      if ret_f:
        attrs['result_' + key] = ret_f
      attrs['handle_' + key] = ori_f
      attrs['origin_' + key] = ori_f
      attrs[key] = key
    ncls = super().__new__(mcs, cls_name, bases, attrs)
    return ncls


use_epoll = hasattr(select, 'epoll')
use_kqueue = hasattr(select, 'kqueue')

use_polling = not use_epoll and not use_kqueue


class SocketMonitor(threading.Thread):
  _wake_event: threading.Event

  def __init__(self):
    super().__init__()
    self.name = 'socket monitor'
    if use_epoll:
      self.poll = select.epoll()
      self._wake_reader, self._wake_writer = socket.socketpair()
      self._wake_fileno = self._wake_reader.fileno()
      self.poll.register(self._wake_fileno, select.EPOLLIN | select.EPOLLERR | select.EPOLLRDHUP)
    elif use_kqueue:
      self.poll = select.kqueue()
      self._wake_reader, self._wake_writer = socket.socketpair()
      self._wake_fileno = self._wake_reader.fileno()
      kevent = select.kevent(self._wake_fileno, filter=select.KQ_FILTER_READ, flags=select.KQ_EV_ADD)
      self.poll.control([kevent], 0)
    else:
      self.poll = None
      self._poll_lock = threading.Lock()
      self._wake_reader, self._wake_writer = socket.socketpair()
      self._sockets_to_poll = [self._wake_reader]
      self._wake_fileno = self._wake_reader
      self._wake_event = threading.Event()
    self.callbacks = {}
    self.running = True

  def _wake(self):
    try:
      self._wake_writer.send(b'stop')
    except Exception:
      pass

  def register_socket(self, sock, callback, extra_flag=None):
    fileno = sock.fileno()
    if fileno == self._wake_fileno:
      return
    if use_epoll:
      if extra_flag is None:
        extra_flag = select.EPOLLET
      flags = select.EPOLLERR | select.EPOLLRDHUP | extra_flag
      self.poll.register(fileno, flags)
    elif use_kqueue:
      if extra_flag is None:
        extra_flag = select.KQ_EV_EOF
      kevent = select.kevent(fileno, filter=select.KQ_FILTER_READ, flags=select.KQ_EV_ADD)
      self.poll.control([kevent], 0)
    else:
      with self._poll_lock:
        self._sockets_to_poll.append(sock)
      self._wake_event.set()
    self.callbacks[fileno] = (sock, callback, extra_flag)

  def unregister_socket(self, fileno):
    if fileno == self._wake_fileno:
      return False
    v = self.callbacks.pop(fileno, None)
    if not v:
      return False
    try:
      if use_epoll:
        self.poll.unregister(fileno)
      elif use_kqueue:
        kevent = select.kevent(fileno, filter=select.KQ_FILTER_READ, flags=select.KQ_EV_DELETE)
        self.poll.control([kevent], 0)
      else:
        sock, _, _ = v
        with self._poll_lock:
          if sock in self._sockets_to_poll:
            self._sockets_to_poll.remove(sock)
        # self._wake_event.set()
    except:
      pass
    return v[1]

  def stop(self):
    if not self.running:
      return
    self.running = False
    self._wake()
    filenos = list(self.callbacks.keys())
    for fileno in filenos:
      self.unregister_socket(fileno)
    if self.is_alive():
      self.join(timeout=5)
      if self.is_alive():
        print("Warning: SocketMonitor thread did not terminate properly")
    else:
      print('socket monitor closed')
    try:
      self._wake_reader.close()
      self._wake_writer.close()
    except Exception as e:
      print(f"Error closing wake resources: {e}")
    if self.poll:
      try:
        self.poll.close()
      except Exception as e:
        print(f"Error closing poll object: {e}")

  def run(self):
    none_value = (None, None, None)
    while self.running:
      if use_epoll:
        events = self.poll.poll()
        for file_no, event in events:
          if event & (select.EPOLLERR | select.EPOLLRDHUP):
            sock, callback, flags = self.callbacks.get(file_no, none_value)
            if callback is not None:
              callback(True, sock)
            self.unregister_socket(file_no)
          else:
            continue
            # print('unsupported event', hex(event))
      elif use_kqueue:
        events = self.poll.control(None, 1)  # 等待至少1个事件
        for kev in events:
          ident = kev.ident
          sock, callback, flags = self.callbacks.get(ident, none_value)
          if callback is None:
            self.unregister_socket(ident)
            continue
          if kev.flags & (select.KQ_EV_EOF | select.KQ_EV_ERROR):
            # 处理错误事件
            callback(True, sock)
            self.unregister_socket(ident)
          elif kev.filter == select.KQ_FILTER_READ:
            if flags == select.KQ_EV_EOF:
              continue
            callback(False, sock)
      else:
        self._wake_event.clear()
        with self._poll_lock:
          sockets_to_check = list(self._sockets_to_poll)
        if sockets_to_check:
          # 使用 select.select 检查可读或异常
          try:
            ready_to_read, _, exceptional = select.select(sockets_to_check, [], sockets_to_check, None)  # 非阻塞
          except ValueError:
            # 如果 sockets_to_check 中有已关闭的socket，select可能会抛出ValueError
            time.sleep(0.2)  # 短暂休眠避免忙等
            continue
          if not ready_to_read and not exceptional:
            time.sleep(1)
            continue
          for sock in ready_to_read:
            fileno = sock.fileno()
            sock_obj, callback, flags = self.callbacks.get(fileno, none_value)
            if sock_obj is None: continue
            if callback is not None:
              callback(False, sock)
          for sock in exceptional:
            fileno = sock.fileno()
            sock_obj, callback, flags = self.callbacks.get(fileno, none_value)
            if sock_obj is None: continue
            if callback is not None:
              callback(True, sock)
            self.unregister_socket(fileno)
        else:
          self._wake_event.wait(2)


global_socket_monitor: SocketMonitor | None = None


def get_monitor() -> SocketMonitor:
  global global_socket_monitor
  if global_socket_monitor is None:
    global_socket_monitor = SocketMonitor()
    global_socket_monitor.start()
  return global_socket_monitor


def close_monitor():
  global global_socket_monitor
  if global_socket_monitor is not None:
    global_socket_monitor.stop()
    global_socket_monitor = None


class RpcClient(metaclass=RpcMeta):
  sock: socket.socket | None = None
  allow_apis = None
  broadcast_tables = None
  broadcast_id_maps = None
  default_timeout = 100
  last_request_time = 0
  call_counter = 0
  request_lock_wait_time = 100
  prohibit_request = False
  can_send = True
  send_count = 0
  on_close_callback = None
  quiet = False

  def __init__(self, host, port, name=None, timeout=None):
    super().__init__()
    if not host:
      host = '127.0.0.1'
    self.host = host
    self.port = port
    if timeout:
      self.default_timeout = timeout
    self.connect()
    if name is None:
      name = self.__class__.__name__.lower() + '-{}'.format(port)
    self.name = name
    self.request_lock = threading.Lock()

  def forbid_call(self):
    self.allow_apis = {}

  def set_on_close_listener(self, listener):
    self.on_close_callback = listener

  def on_close(self, is_close: bool, sock):
    self.forbid_call()
    self.close()

  def __repr__(self):
    return self.name

  def try_connect(self):
    try:
      if self.sock:
        self.ping(timeout=5)
        return True
    except:
      pass
    try:
      self.connect()
      self.ping(timeout=5)
      return True
    except:
      return False

  def __getattr__(self, method):
    allow_apis = self.allow_apis
    if method in allow_apis:
      handle_method = getattr(self, 'call_' + method)
      parse_method = getattr(self, 'parse_' + method, None)
      rpc_method = AlbRpcMethod(self, method, self.allow_apis[method], handle_method, parse_method)
      setattr(self, method, rpc_method)
      return rpc_method
    if method in self.broadcast_tables:
      parse_method = getattr(self, 'receive_' + method, None)
      setattr(self, method, parse_method)
      return parse_method
    if not self.sock:
      raise RpcCloseException("connection is closed")
    return super().__getattribute__(method)

  def connect(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(20)
    sock.connect((self.host, self.port))
    self.get_apis(sock)
    sock.settimeout(self.default_timeout)
    self.sock = sock
    if use_polling:
      get_monitor().register_socket(sock, self.on_read_win)
    else:
      get_monitor().register_socket(sock, self.on_close)

  def reconnect(self):
    try:
      if not self.sock:
        self.connect()
        return True
    except:
      pass
    return False

  def close(self):
    subscriber: RpcClient = self.subscriber
    if subscriber:
      subscriber.shutdown()
      self.subscriber = None
    sock = self.sock
    if sock:
      try:
        self.sock = None
        get_monitor().unregister_socket(sock.fileno())
        sock.close()
      except:
        pass
      if self.on_close_callback:
        try:
          self.on_close_callback(self)
          self.on_close_callback = None
        except:
          traceback.print_exc()
      return True
    return False

  def get_apis(self, sock=None):
    if not sock:
      sock = self.sock
    rpc_send_data(sock, None, self.call_counter, MSG_APIS)
    self.call_counter += 1
    idx, result, data = rpc_receive_data(sock)
    num_api = struct.unpack('<i', data[:4])[0]
    if not old_version:
      num_broadcast = struct.unpack('<i', data[4:8])[0]
      idx = 8
    else:
      num_broadcast = 0
      idx = 4
    broadcast_tables = {}
    broadcast_id_maps = {}

    rpc_tables = {}
    for _ in range(num_api):
      cmd = data[idx]
      rpc_name, idx = read_string(data, idx + 1)
      rpc_tables[rpc_name] = cmd
    for _ in range(num_broadcast):
      cmd = data[idx]
      rpc_name, idx = read_string(data, idx + 1)
      broadcast_tables[rpc_name] = cmd
      broadcast_id_maps[cmd] = rpc_name
    self.allow_apis = rpc_tables
    self.broadcast_tables = broadcast_tables
    self.broadcast_id_maps = broadcast_id_maps
    return rpc_tables

  @rpc_api
  def subscribe(self):
    """
    订阅RPC服务，用于接收广播消息

    Returns:
        订阅结果
    """

  def register_broadcast_handler(self, broadcast_name, handler):
    setattr(self, 'handle_' + broadcast_name, handler)

  def register_broadcast_listener(self, msg_id, listener):
    raise NotImplementedError

  @cached_subclass_property
  def broadcast_listeners(self) -> dict:
    return defaultdict(list)

  def send(self, cmd, data, idx):
    if self.can_send:
      rpc_send_data(self.sock, data, idx, cmd)
    else:
      raise RpcSendException('can not send data {}'.format(data))
    self.send_count += 1

  continuous = True
  idx = None

  def on_read_win(self, is_close, sock):
    if is_close:
      self.on_close(is_close, sock)
      return
    if not self.subscribe_thread:
      elapse_time = time.time() - self.last_request_time
      if elapse_time < 8:
        return
      self.on_close(is_close, sock)
      if not is_close:
        get_monitor().unregister_socket(sock.fileno())
      return
    self.__subscribe_loop()

  def __subscribe_loop(self):
    self.can_send = False
    try:
      self.sock.settimeout(20)
      while self.continuous:
        try:
          idx, cmd, data = rpc_receive_data(self.sock)
        except TimeoutError as e:
          continue
        broadcast_name = self.broadcast_id_maps.get(cmd)
        should_send = idx & 1
        to_send = b'send empty'
        self.idx = idx
        # idx = idx >> 1
        if should_send:
          self.can_send = True
          self.send_count = 0
        else:
          self.can_send = False
        try:
          if broadcast_name:
            arg_parser = getattr(self, 'receive_' + broadcast_name)
            args = arg_parser(data)
            handler = getattr(self, 'handle_' + broadcast_name)
            result = handler(*args)
            convertor = getattr(self, 'result_' + broadcast_name, None)
            if convertor:
              cmd, idx, to_send = convertor(cmd, idx, result)
          else:
            cmd = BROADCAST_RESULT_NO_HANDLER
            print(broadcast_name + ' no handler! receive', idx, cmd, data)
        except Exception as e:
          traceback.print_exc()
        if should_send and not self.send_count:
          self.send(cmd, to_send, idx)
        if use_polling:
          return
    except Exception as e:
      if self.continuous:
        traceback.print_exc()
        print(f'{self.name} subscriber close:', e)
    self.close()

  subscribe_thread: threading.Thread | bool | None = None

  def join_subscribe(self, max_time=360):
    subscribe_thread = self.subscribe_thread
    if subscribe_thread is not None:
      while subscribe_thread.is_alive() and max_time > 0:
        time.sleep(5)
        max_time -= 5
        # subscribe_thread.join()
      if not subscribe_thread.is_alive():
        self.subscribe_thread = None

  subscriber = None

  def _subscriber_close(self, subscriber):
    subscriber.close()
    self.subscriber = None

  def create_subscriber(self) -> 'RpcClient':
    if self.subscriber:
      return self.subscriber
    subscriber = self.__class__(self.host, self.port, self.name + ':subscribe', self.default_timeout)
    subscriber.subscribe()
    self.subscriber = subscriber
    subscriber.set_on_close_listener(self._subscriber_close)
    return subscriber

  def parse_subscribe(self, data, result):
    if result >= 0:
      if use_polling:
        self.subscribe_thread = True
        return True
      else:
        subscribe_thread = threading.Thread(target=self.__subscribe_loop, name='{}:subscribe'.format(self.name))
        subscribe_thread.start()
        self.subscribe_thread = subscribe_thread
        return subscribe_thread
    return None

  @rpc_api
  def get_tid(self) -> int:
    """
    获取当前线程ID

    Returns:
        int: 线程ID
    """

  @rpc_api
  def ping(self) -> str:
    """
    测试RPC连接是否正常

    Returns:
        str: ping响应消息
    """

  @rpc_api
  def stop(self) -> void:
    """
    停止RPC服务

    Returns:
        void: 无返回值
    """

  def shutdown(self):
    self.continuous = False
    self.close()
