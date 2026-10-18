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
    # 异步方法: 走 MSG_ASYNC_CALL，payload 前置 handler 名。服务端把 handler 挪到
    # 工作线程执行，结果仍以本 call idx 回（接收按 idx 匹配，等待语义与同步一致）；
    # handler 卡死时由服务端超时代答 RPC_JOB_TIMEOUT。老服务端不认识该 cmd 会回
    # NO_HANDLE —— except 分支里降级为普通同步调用重发。
    is_async_call = method_name in getattr(client, '_async_methods', frozenset())
    if is_async_call:
      content = put_string(method_name) + (content or b'')
    request_lock = client.request_lock
    # if request_lock:
    send_exception = None
    idx, result, data = None, None, None
    get_lock = request_lock.acquire(True, timeout=client.request_lock_wait_time)
    start = time.time()
    client.last_request_time = (start, method_name)
    parser = self.parser
    try:
      rpc_send_data(sock, content, method_id, MSG_ASYNC_CALL if is_async_call else self.rpc_id)
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
      # 老服务端没有 MSG_ASYNC_CALL（dynamic/固定表都查不到）回 NO_HANDLE——
      # 降级同步重发一次；其余异常照抛
      if is_async_call and isinstance(send_exception, RpcCallException) \
          and 'not find register handle' in str(send_exception):
        if not quiet:
          client.rpc_log(f'async not supported by server, fallback sync: {method_name}')
        is_async_call = False
        try:
          get_lock = request_lock.acquire(True, timeout=client.request_lock_wait_time)
          start = time.time()
          try:
            rpc_send_data(sock, self.handler(*args, **kwargs) or b'', method_id, self.rpc_id)
            if parser != void:
              if isinstance(parser, RawDataParser):
                parser.after_send(sock, args)
              idx, result, data = rpc_receive_data(sock)
              while idx < method_id:
                idx, result, data = rpc_receive_data(sock)
          except BaseException as e2:
            send_exception = e2
        finally:
          request_lock.release()
        if send_exception:
          raise send_exception
      else:
        raise send_exception
    end = time.time()
    if client.recording_arms and method_name in getattr(client, '_arm_methods', frozenset()):
      client.record_arm(method_name, args, kwargs)
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


@dataclass
class RegisterApiInfo:
  args: str
  ret: str


class RpcMeta(type):

  def __new__(mcs, cls_name, bases, attrs):
    call_tables = {}
    broadcast_tables = {}
    register_apis = {}
    arm_methods = set()
    async_methods = set()
    api_lists = [attrs]
    apis = attrs.get('apis')
    extend_apis = []
    for base in bases:
      if issubclass(base, RpcApi):
        if apis and base not in apis:
          continue
        # 基类的 _api 方法在基类 meta 构建时已被替换成 call_*，_arm 标记拿不到了，
        # 直接并基类已收集好的集合
        arm_methods |= getattr(base, '_arm_methods', frozenset())
        base.mark_subclass(attrs, api_lists)
      elif issubclass(base, RpcClient):
        # 客户端继承链走 RpcClient（metaclass=RpcMeta），基类方法靠 __getattr__
        # 动态解析，这里只并 arm/async 方法集合
        arm_methods |= getattr(base, '_arm_methods', frozenset())
        async_methods |= getattr(base, '_async_methods', frozenset())
    for api_list in api_lists:
      for key, attr_value in api_list.items():
        if callable(attr_value):
          is_api = hasattr(attr_value, '_api')
          if is_api:
            if key in call_tables:
              continue
            if getattr(attr_value, '_arm', False):
              arm_methods.add(key)
            if getattr(attr_value, '_async_call', False):
              async_methods.add(key)
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
            args_desc = []
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
                    register_apis[key] = RegisterApiInfo(args=''.join(args_desc),
                      ret=type_symbol_maps.get(real_type, '0'))
                    ret_f = EnumResultParser(arg_type, return_type_mappings[real_type])
                  elif arg_type in return_type_mappings:
                    ret_f = return_type_mappings[arg_type]
                    register_apis[key] = RegisterApiInfo(args=''.join(args_desc),
                      ret=type_symbol_maps.get(arg_type, '0'))
                  elif hasattr(arg_type, 'parse_value'):
                    ret_f = getattr(arg_type, 'parse_value')
                    if ret_f.__class__.__name__ == 'function':
                      ret_f = staticmethod(ret_f)
                  if raw_parser is not None:
                    ret_f = raw_parser(ret_f)
                break
              if arg_type is socket.socket:
                # 传输层注入参数（打包表 nop，wire 不占字节）：打包保留、签名跳过，
                # 与服务端 sign_of 的跳过对齐，否则比对/校验两侧都错位
                args.append(arg_convert_tables[arg_type])
                continue
              if issubclass(arg_type, Enum):
                arg_type = get_enum_real_type(arg_type)
              args_desc.append(type_symbol_maps.get(arg_type, '0'))
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
    attrs['register_apis'] = register_apis
    attrs['_arm_methods'] = frozenset(arm_methods)
    attrs['_async_methods'] = frozenset(async_methods)
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
    sockets = []
    for fileno in filenos:
      value = self.callbacks.get(fileno)
      if value:
        sockets.append(value[0])
    for fileno in filenos:
      self.unregister_socket(fileno)
    if self.is_alive():
      self.join(timeout=5)
      if self.is_alive():
        logger.warning("Warning: SocketMonitor thread did not terminate properly")
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
    # close_monitor() can be called without first closing every RpcClient.
    # Do not leave those sockets open after removing them from the poller.
    for sock in sockets:
      try:
        sock.close()
      except Exception:
        pass

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
  register_apis: dict
  broadcast_tables = None
  broadcast_id_maps = None
  # 服务端广播参数类型描述（名字 → 逐字符 ArgType 符号串，不含返回类型），连接时经 MSG_APIS v2 下发
  broadcast_types = None
  broadcast_ret_signs = None
  # 服务端 RPC 方法签名（名字 → "ret+args"，如 "Zs" = boolean f(String)），v2 下发
  allow_signs = None
  # 武装脚本（进程重启重连后可重放的状态变更序列）。默认 None=未绑定（不记录）；
  # 绑定为 list 后（见 start_arm_recording / Device.replay_arm_scripts），
  # recording_arms 期间成功的武装型 RPC（@rpc_api(arm=True)）会按序追加进列表，
  # reconnect() 成功后自动重放（auto_replay_arm 可关）。
  arm_script: list | None = None
  recording_arms = False
  auto_replay_arm = True
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

  # ---- 武装记录与重放（@rpc_api(arm=True) 的方法参与） ----

  def start_arm_recording(self):
    """开启武装记录：之后成功的武装型 RPC 按序追加进 self.arm_script。

    arm_script 未绑定时自动建独立列表；要与 Device 共享（launch 重启自动重放）
    先 bind_arm_script(server.arm_scripts.setdefault(uid, [])) 再开启。
    """
    if self.arm_script is None:
      self.arm_script = []
    self.recording_arms = True
    return self.arm_script

  def stop_arm_recording(self):
    self.recording_arms = False

  def record_arm(self, method, args, kwargs):
    """按调用序记一条武装调用。注意是**引用语义**：记的是 args/kwargs 的引用，
    可变参数（list/dict）事后被改，重放的是改后的值——要定格就传不可变值或
    先拷贝。"""
    if not self.recording_arms or self.arm_script is None:
      return
    self.arm_script.append((method, args, dict(kwargs)))

  def replay_arm(self, script=None):
    """在当前连接上按序重放武装脚本。单条失败记日志继续（如类还没加载出来），
    返回 [(method, result, exception)]。脚本本身不清空，可重复重放。
    重放期间抑制记录：重连自动重放时 recording_arms 往往还开着（没人规定要先
    stop），重放出的调用再记回同一份脚本会每轮重启翻倍（N→2N→4N）。"""
    entries = self.arm_script if script is None else script
    results = []
    was_recording = self.recording_arms
    self.recording_arms = False
    try:
      for method, args, kwargs in list(entries or []):
        try:
          results.append((method, getattr(self, method)(*args, **kwargs), None))
        except Exception as e:
          self.log(f'{self.name} replay_arm {method}{args} fail: {e}')
          results.append((method, None, e))
    finally:
      self.recording_arms = was_recording
    return results

  def bind_arm_script(self, script: list):
    """绑定共享武装脚本列表（与其它 client / Device 共享同一份）。"""
    self.arm_script = script

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
    # allow_apis/broadcast_tables 未连接时是类级 None，按空表处理，避免 TypeError 吞掉真实错误
    allow_apis = self.allow_apis or {}
    if method in allow_apis:
      handle_method = getattr(self, 'call_' + method, None)
      if handle_method is None:
        raise AttributeError(f'{type(self).__name__} has no declared api: {method}')
      parse_method = getattr(self, 'parse_' + method, None)
      rpc_method = AlbRpcMethod(self, method, allow_apis[method], handle_method, parse_method)
      setattr(self, method, rpc_method)
      return rpc_method
    if method in (self.broadcast_tables or {}):
      return self._ensure_broadcast_parser(method)
    if not self.sock:
      raise RpcCloseException("connection is closed")
    raise AttributeError(f'{type(self).__name__} has no rpc api or broadcast: {method}')

  def _make_receive(self, name, types_desc=None):
    """为服务端已注册、客户端类未声明的广播合成 payload 解析器（自动发现）。

    有类型描述（MSG_APIS v2 下发的 ArgType 符号串）按类型解析；空串 = 无参广播；
    无类型信息或含未知符号时退化为尽力按字符串收，保证订阅循环不再因漏声明而
    抛 AttributeError。
    """
    if types_desc:
      readers = []
      for ch in types_desc:
        reader = broadcast_arg_readers.get(ch)
        if reader is None:
          readers = None
          break
        readers.append(reader)
    else:
      # None = 服务端没给类型（老服务端）；'' = 已知无签名（native registerBroadcast
      # 未登记 sign）。两者都可能实际带参，按"尽力按字符串收"处理而不是当零参——
      # 零参解析器会把真实参数静默丢掉。真零参广播 payload 为空，走 [] 分支不受影响。
      readers = None
    if readers is None:
      readers = [read_string]

    def __wrapper(client, sock_data, sock):
      if not sock_data:
        return []
      args = []
      idx = 0
      for parser in readers:
        if parser == socket.socket:
          args.append(sock)
          continue
        arg, idx = parser(sock_data, idx)
        args.append(arg)
      return args

    return __wrapper

  def _ensure_broadcast_parser(self, name):
    key = 'receive_' + name
    # 显式查实例/类字典，不走 getattr——get_apis 在 self.sock 赋值前就会调到这里，
    # 走 __getattr__ 会误抛 RpcCloseException
    parser = self.__dict__.get(key)
    if parser is None:
      # 类属性拿到的是未绑定函数（create_receive_function 的首参是 client），必须
      # 绑到实例上，订阅循环才能按 parser(data, sock) 调用；实例字典里的（本方法
      # 合成的闭包、外部塞的函数）保持原样——闭包再绑会错位注入 self
      parser = getattr(type(self), key, None)
      if parser is not None:
        parser = parser.__get__(self, type(self))
    if parser is not None:
      return parser
    # create_receive_function 的首参是 client（类里静态生成的 receive_* 靠方法绑定传入），
    # 这里合成的要自己绑住实例，与订阅循环的 parser(data, sock) 调用约定对齐
    raw_parser = self._make_receive(name, (self.broadcast_types or {}).get(name))

    def bound_parser(sock_data, sock, _self=self, _raw=raw_parser):
      return _raw(_self, sock_data, sock)

    setattr(self, key, bound_parser)
    return bound_parser

  def _ensure_broadcast_result(self, name):
    """为自动发现的广播合成 result_<name> 回包打包器（v2 签名的返回类型字符
    → broadcast_result_packagers）。已声明的（类上有 RpcMeta 生成的 result_）
    与无返回类型的不动。"""
    key = 'result_' + name
    if self.__dict__.get(key) is not None:
      return
    if getattr(type(self), key, None) is not None:
      return
    ret_ch = (self.broadcast_ret_signs or {}).get(name)
    packager = broadcast_result_packagers.get(ret_ch) if ret_ch else None
    if packager is not None:
      setattr(self, key, packager)

  def _ensure_broadcast_handler(self, name):
    key = 'handle_' + name
    # 同 _ensure_broadcast_parser：实例字典原样用，类属性（声明的广播存根/
    # 类级 handler）按方法绑定；订阅循环 handler(*args) 不传 self
    handler = self.__dict__.get(key)
    if handler is None:
      handler = getattr(type(self), key, None)
      if handler is not None:
        handler = handler.__get__(self, type(self))
    if handler is not None:
      return handler

    def auto_handler(*args):
      self.log(f'{self.name} broadcast {name} (auto-discovered, no handler): {args}')

    # 标记为自动兜底：带回包的广播按 BROADCAST_RESULT_NO_HANDLER 回给服务端，
    # 让带返回值的广播（broadcastWithResult）跳过本订阅者而不是乱解析回包
    auto_handler._auto_broadcast = True
    setattr(self, 'handle_' + name, auto_handler)
    return auto_handler

  def connect(self):
    sock = self.sock
    if sock:
      try:
        sock.close()
      except:
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      sock.settimeout(20)
      sock.connect((self.host, self.port))
      self.get_apis(sock)
      sock.settimeout(self.default_timeout)
    except Exception as e:
      sock.close()
      raise
    self.sock = sock
    try:
      if use_polling:
        get_monitor().register_socket(sock, self.on_read_win)
      else:
        get_monitor().register_socket(sock, self.on_close)
    except Exception:
      self.sock = None
      try:
        sock.close()
      except Exception:
        pass
      raise

  def reconnect(self):
    try:
      if not self.sock:
        self.connect()
        if self.arm_script and self.auto_replay_arm:
          # 进程重启重连后自动重放武装脚本（单条失败已在 replay_arm 里记日志）
          self.replay_arm()
        return True
    except:
      pass
    return False

  def close(self):
    subscriber: RpcClient = self.subscriber
    if subscriber:
      try:
        subscriber.shutdown()
      except Exception:
        traceback.print_exc()
      finally:
        self.subscriber = None
    sock = self.sock
    if sock:
      try:
        self.sock = None
        get_monitor().unregister_socket(sock.fileno())
      finally:
        sock.close()
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

  def flush_api(self):
    sock = self.sock
    if not sock:
      return None
    return self.get_apis(sock)

  def get_apis(self, sock=None):
    if not sock:
      sock = self.sock
    # payload 'v' = 客户端按 v2 解析广播段（含参数类型）；老服务端忽略 payload 回老格式
    rpc_send_data(sock, b'v', self.call_counter, MSG_APIS)
    self.call_counter += 1
    idx, result, data = rpc_receive_data(sock)
    num_api = struct.unpack('<i', data[:4])[0]
    if not old_version:
      num_broadcast = struct.unpack('<i', data[4:8])[0]
      idx = 8
    else:
      num_broadcast = 0
      idx = 4
    # v2 标志: 两计数后 1 字节 0x00（0 永不成为合法方法/广播 id——python 端自
    # MSG_APIS+1 起编号、native 端固定/动态 cmd 均从 MSG_LAST 起且避开 0，老服务端
    # 此位置必是首个方法的非零 cmd）。不能以广播数为前提：无广播的服务端 v2 也会写标志。
    has_types = False
    if not old_version and data[idx:idx + 1] == b'\0':
      has_types = True
      idx += 1
    broadcast_tables = {}
    broadcast_id_maps = {}
    broadcast_types = {}
    broadcast_ret_signs = {}
    allow_signs = {}

    rpc_tables = {}
    for _ in range(num_api):
      cmd = data[idx]
      rpc_name, idx = read_string(data, idx + 1)
      if has_types:
        sign, idx = read_string(data, idx)
        allow_signs[rpc_name] = sign
      rpc_tables[rpc_name] = cmd
    for _ in range(num_broadcast):
      cmd = data[idx]
      rpc_name, idx = read_string(data, idx + 1)
      if has_types:
        types_desc, idx = read_string(data, idx)
        # 服务端 sign 首字符是返回类型：参数段喂解析器，返回段喂回包打包器
        broadcast_types[rpc_name] = types_desc[1:] if types_desc else ''
        broadcast_ret_signs[rpc_name] = types_desc[0] if types_desc else ''
      broadcast_tables[rpc_name] = cmd
      broadcast_id_maps[cmd] = rpc_name
    self.allow_apis = rpc_tables
    self.broadcast_tables = broadcast_tables
    self.broadcast_id_maps = broadcast_id_maps
    self.broadcast_types = broadcast_types
    self.broadcast_ret_signs = broadcast_ret_signs
    self.allow_signs = allow_signs
    # 为未声明的广播提前合成解析器与回包打包器（漏声明不再炸订阅循环，
    # 带返回值的广播也不会把 'send empty' 字面量当返回值回给服务端）
    for name in broadcast_tables:
      self._ensure_broadcast_parser(name)
      self._ensure_broadcast_result(name)
    self._check_signatures(allow_signs)
    return rpc_tables

  @staticmethod
  def _sign_compatible(a: str, b: str) -> bool:
    """兼容比对（不要求精确）：'s' 与 'j' 的 wire 布局相同（u16 长度 + 数据 +
    '\0'），dict/list/json 传成 string、string 传成 json 都能正确解析，视为
    可互换；其余类型必须同字符，参数个数不同（长度不同）不兼容。"""
    if a == b:
      return True
    if len(a) != len(b):
      return False
    for ca, cb in zip(a, b):
      if ca == cb:
        continue
      if {ca, cb} <= {'s', 'j'}:
        continue
      return False
    return True

  def _check_signatures(self, server_signs):
    """连接即比对：本类声明的方法签名 vs 服务端注册签名，不兼容立刻抛
    （参数类型/个数错了当场发现，而不是等到调用拿到垃圾值）。比对是兼容
    语义：dict/list/json 与 string 同 wire 布局可互换。只比对类里声明过的
    方法（register_apis）；cmodule 等动态注册的方法、服务端未下发签名的
    （老服务端）跳过。"""
    declared = getattr(self, 'register_apis', None) or {}
    mismatches = []
    for name, info in declared.items():
      server_sign = server_signs.get(name)
      if not server_sign:
        continue
      expect = (info.ret or '') + (info.args or '')
      if '0' in expect:
        # 声明里含无法映射符号的类型（如 socket 注入参数），wire 上不占字节，
        # 无法构造可比的签名，跳过而不是误报不匹配
        continue
      if not self._sign_compatible(expect, server_sign):
        mismatches.append(f'{name}: declared {expect!r} != server {server_sign!r}')
    if mismatches:
      raise RpcCallException('rpc signature mismatch (python side declaration != server):\n'
                             + '\n'.join(mismatches))

  @rpc_api
  def subscribe(self, params: str = None, flags: int = 0):
    """
    订阅RPC服务，用于接收广播消息

    Returns:
        订阅结果
    """

  def register_broadcast_handler(self, broadcast_name, handler):
    # 未声明过的广播先合成解析器与回包打包器，保证 payload 能解出来、
    # 带返回值的广播能把 handler 返回值正确打包回去
    self._ensure_broadcast_parser(broadcast_name)
    self._ensure_broadcast_result(broadcast_name)
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
            arg_parser = self._ensure_broadcast_parser(broadcast_name)
            args = arg_parser(data, self.sock)
            handler = self._ensure_broadcast_handler(broadcast_name)
            result = handler(*args)
            if getattr(handler, '_auto_broadcast', False):
              # 自动发现但没挂真 handler：按"无 handler"回给服务端，带返回值的
              # 广播会跳过本订阅者（兜底 handler 返回 None，不能进打包器）
              cmd = BROADCAST_RESULT_NO_HANDLER
            else:
              convertor = getattr(self, 'result_' + broadcast_name, None)
              if convertor:
                cmd, idx, to_send = convertor(cmd, idx, result)
          else:
            self.log(f'{self.name} get broadcast {cmd} no handler register! receive：{idx}, {data}')
            cmd = BROADCAST_RESULT_NO_HANDLER
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
    subscriber = None
    try:
      subscriber = self.__class__(self.port, self.host, self.name + ':subscribe', self.default_timeout)
      subscriber.subscribe(params, flags)
      self.subscriber = subscriber
      subscriber.add_close_listener(self._subscriber_close, 'subscriber_watch')
      return subscriber
    except BaseException:
      if subscriber is not None:
        subscriber.shutdown()
      raise

  def parse_subscribe(self, data, result):
    if result >= 0:
      if use_polling:
        self.subscribe_thread = True
        return True
      else:
        subscribe_thread = threading.Thread(target=self.__subscribe_loop, name='{}:subscribe'.format(self.name),
          daemon=True)
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
    logger.info('get broadcast test:' + s)
    return len(s)

  def shutdown(self):
    self.continuous = False
    self.close()
