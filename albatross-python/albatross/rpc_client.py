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

import select
import threading
import time
import traceback
from collections import defaultdict

from .rpc_common import *
from .wrapper import cached_subclass_property


class RawDataParser(object):
  convertor = None

  def __init__(self, result_convert=None):
    if result_convert:
      self.convertor = result_convert

  def __call__(self, data, result):
    convertor = self.convertor
    if convertor:
      return convertor(data, result)
    return data

  def after_send(self, sock, args):
    pass


class AlbRpcMethod(object):
  parser = None

  def __init__(self, client, name, rpc_id, handler, parser):
    self.client = client
    self.name = name
    self.rpc_id = rpc_id
    self.handler = handler
    if parser:
      self.parser = parser

  def __call__(self, *args, hint=None, timeout=None, silence=False, raw=False, **kwargs):
    client = self.client
    method_name = self.name
    if client.prohibit_request:
      raise BanRequestException('forbid request {} this time'.format(method_name))
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
        client.rpc_log(f"request method:{method_id_name} {args} {hint}")
      else:
        client.rpc_log(f"request method:{method_id_name} {args}")
    else:
      method_id_name = None
    content = self.handler(*args, **kwargs)
    sock = client.sock
    if not sock:
      raise RpcCloseException(f'{client} socket closed')
    if timeout:
      sock.settimeout(timeout)
    if content and not isinstance(content, bytes):
      if isinstance(content, JustReturn):
        return content.result
      content = str(content).encode(STRING_ENCODING)
    request_lock = client.request_lock
    # if request_lock:
    send_exception = None
    idx, result, data = None, None, None
    get_lock = request_lock.acquire(True, timeout=client.request_lock_wait_time)
    start = time.time()
    client.last_request_time = (start, method_name)
    parser = self.parser
    try:
      rpc_send_data(sock, content, method_id, self.rpc_id)
      if parser != void:
        if isinstance(parser, RawDataParser):
          parser.after_send(sock, args)
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
        client.rpc_log(f"response {method_id_name}[{end - start:.2f}]:no return {rpc_name}")
      return
    if idx != method_id:
      desc = f'rpc {rpc_name} {method_name} response wrong idx except {method_id},got {idx} in {threading.current_thread().name}'
      client.log(desc)
    if result < 0:
      err_fmt = err_desc.get(result)
      if err_fmt:
        err_fmt = err_fmt.format(method_name)
        if data:
          # err_detail, _ = read_string(data, 0)
          err_detail = data.decode(STRING_ENCODING)
          if err_detail:
            err_fmt += ",detail:" + err_detail
        raise RpcCallException(err_fmt)
      pass
    if parser:
      if not raw:
        data = parser(data, result)
    elif data is None:
      data = result >= 0
    if not quiet:
      client.rpc_log(f"response {method_id_name}[{(end - start):.2f}]:{str(data)[:128]} {rpc_name}")
    if timeout:
      sock.settimeout(client.default_timeout)
    return data


class RpcMeta(type):

  def __new__(mcs, cls_name, bases, attrs):
    call_tables = {}
    broadcast_tables = {}
    api_lists = [attrs]
    apis = attrs.get('apis')
    extend_apis = []
    for base in bases:
      if issubclass(base, RpcApi):
        if apis and base not in apis:
          continue
        base.mark_subclass(attrs, api_lists)
    for api_list in api_lists:
      for key, attr_value in api_list.items():
        if callable(attr_value):
          is_api = hasattr(attr_value, '_api')
          if is_api:
            if key in call_tables:
              continue
            if api_list is not attrs:
              extend_apis.append(key)
            annotations = attr_value.__annotations__
            default_args = attr_value.__defaults__
            args = []
            ret_f = None
            argcount = attr_value.__code__.co_argcount
            if 'return' in annotations:
              if argcount != len(annotations):
                raise WrongAnnotation(f'api {key} all argument should mark type')
            elif argcount != len(annotations) + 1:
              raise WrongAnnotation(f'api {key} all argument should mark type')
            arg_index = {}
            for name, arg_type in annotations.items():
              arg_index[name] = len(arg_index)
              arg_type_str = str(arg_type)
              if 'str | None' == arg_type_str:
                arg_type = str
              if name == 'return':
                ret_f = attrs.get('parse_' + key, None)
                raw_parser = None
                if ret_f:
                  try:
                    if issubclass(ret_f, RawDataParser):
                      raw_parser = ret_f
                      ret_f = None
                  except:
                    pass
                if ret_f is not None:
                  if ret_f.__class__.__name__ == 'function':
                    ret_f = staticmethod(ret_f)
                else:
                  if issubclass(arg_type, Enum):
                    real_type = get_enum_real_type(arg_type)
                    ret_f = EnumResultParser(arg_type, return_type_mappings[real_type])
                  elif arg_type in return_type_mappings:
                    ret_f = return_type_mappings[arg_type]
                  elif hasattr(arg_type, 'parse_value'):
                    ret_f = getattr(arg_type, 'parse_value')
                    if ret_f.__class__.__name__ == 'function':
                      ret_f = staticmethod(ret_f)
                  if raw_parser is not None:
                    ret_f = raw_parser(ret_f)
                break
              if issubclass(arg_type, Enum):
                arg_type = get_enum_real_type(arg_type)
              args.append(arg_convert_tables[arg_type])
            f = create_call_function(args, default_args, arg_index)
            f.__name__ = attr_value.__name__
            call_tables[key] = (f, ret_f)
          elif hasattr(attr_value, '_broadcast'):
            if key in broadcast_tables:
              continue
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
            broadcast_tables[key] = (f, ret_f, attr_value)

    for key, (f, ret_f) in call_tables.items():
      ori_f = attrs.pop(key, None)
      attrs['call_' + key] = f
      if ret_f is not None:
        attrs['parse_' + key] = ret_f
    for key, (f, ret_f, ori_f) in broadcast_tables.items():
      ori_f = attrs.pop(key, ori_f)
      attrs['receive_' + key] = f
      if ret_f:
        attrs['result_' + key] = ret_f
      attrs['handle_' + key] = ori_f
      attrs['origin_' + key] = ori_f
      attrs[key] = key
    if extend_apis:
      for api_name in extend_apis:
        attrs[api_name] = api_getter(api_name)
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
      RpcClient.log('socket monitor closed')
    try:
      self._wake_reader.close()
      self._wake_writer.close()
    except Exception as e:
      RpcClient.log(f"Error closing wake resources: {e}")
    if self.poll:
      try:
        self.poll.close()
      except Exception as e:
        RpcClient.log(f"Error closing poll object: {e}")

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
            ready_to_read, _, exceptional = select.select(sockets_to_check, [], sockets_to_check, 1)  # 非阻塞
          except ValueError:
            # 如果 sockets_to_check 中有已关闭的socket，select可能会抛出ValueError
            time.sleep(0.2)  # 短暂休眠避免忙等
            continue
          if not ready_to_read and not exceptional:
            self._wake_event.wait(1)
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
  last_request_time = (0, '')
  call_counter = 0
  request_lock_wait_time = 100
  prohibit_request = False
  can_send = True
  send_count = 0
  on_close_callbacks: dict
  quiet = False
  debug = True

  def __init__(self, port, host=None, name=None, timeout=None):
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
    self.on_close_callbacks = {}

  def forbid_call(self):
    self.allow_apis = {}

  log = print
  rpc_log = log

  def add_close_listener(self, listener, key='default'):
    self.on_close_callbacks[key] = listener

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
    return super().__getattr__(method)

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
      callbacks = self.on_close_callbacks
      if callbacks:
        for key, callback in callbacks.items():
          try:
            callback(self)
          except:
            traceback.print_exc()
        callbacks.clear()
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
  def subscribe(self, params: str = None, flags: int = 0):
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

  def _response(self, cmd, data, idx):
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
    last_request_time, method_name = self.last_request_time
    if not self.subscribe_thread:
      elapse_time = time.time() - last_request_time
      if elapse_time < 8:
        if method_name == 'subscribe':
          self.log('get subscribe return?')
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
            args = arg_parser(data, self.sock)
            handler = getattr(self, 'handle_' + broadcast_name)
            result = handler(*args)
            convertor = getattr(self, 'result_' + broadcast_name, None)
            if convertor:
              cmd, idx, to_send = convertor(cmd, idx, result)
          else:
            cmd = BROADCAST_RESULT_NO_HANDLER
            self.log(f'broadcast {cmd} no handler! receive：{idx}, {data}')
        except Exception as e:
          self.log(f'do {broadcast_name} receive error')
          traceback.print_exc()
        if should_send and not self.send_count:
          self._response(cmd, to_send, idx)
        if use_polling:
          return
    except Exception as e:
      if self.continuous:
        if not isinstance(e, OSError):
          traceback.print_exc()
        self.log(f'{self.name} subscriber close:' + str(e))
    self.close()

  subscribe_thread: threading.Thread | bool | None = None

  def join_subscribe(self, max_time=360):
    subscribe_thread = self.subscribe_thread
    if use_polling:
      if subscribe_thread:
        while self.sock and max_time > 0:
          time.sleep(5)
          max_time -= 5
    else:
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

  def create_subscriber(self, params: str = None, flags: int = 0) -> 'RpcClient':
    if self.subscriber:
      return self.subscriber
    subscriber = self.__class__(self.port, self.host, self.name + ':subscribe', self.default_timeout)
    subscriber.subscribe(params, flags)
    self.subscriber = subscriber
    subscriber.add_close_listener(self._subscriber_close, 'subscriber_watch')
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
  def get_pid(self) -> int:
    pass

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

  @broadcast_api
  def broadcast_test(self, s: str) -> int:
    print('get broadcast test:' + s)
    return len(s)

  def shutdown(self):
    self.continuous = False
    self.close()
