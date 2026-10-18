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

from enum import IntFlag

from albatross.inject_client import BaseClient
from albatross.rpc_client import rpc_api, void, broadcast_api
from albatross.rpc_common import long, logger


class TraceScope(IntFlag):
  kJdk = 1
  kPlatform = 2
  kApplication = 4
  kPackageFilter = 8
  kEntryOnly = 0x10

  CALL_ENTER = 0x100


class EventType(IntFlag):
  """Java 方法级 trace 的事件位(qing.albatross.tracker.EventType 的镜像)"""
  EXEC = 1
  CALL = 2
  BLOCK = 8
  RETURN = 0x10
  FILE_READ = 0x20
  FIELD_WRITE = 0x40
  DUMP = 0x80
  CALL_ENTER = 0x100
  ALL = 0xffff


class AppClient(BaseClient):

  @rpc_api
  def get_package_name(self) -> str:
    """
    获取当前应用的包名

    Returns:
        str: 应用包名
    """

  @rpc_api
  def unshell(self) -> bool:
    pass

  @rpc_api
  def finish_unshell(self) -> bool:
    pass

  @rpc_api(arm=True)
  def trace_call(self, only_main_thread: bool) -> bool:
    pass

  @rpc_api(arm=True)
  def trace_return(self, only_main_thread: bool, extra_flags: int = 0) -> bool:
    pass

  @rpc_api(arm=True)
  def trace_keyword(self, keyword: str, main_thread: bool) -> bool:
    pass

  @rpc_api(arm=True)
  def trace_string(self, keyword: str, main_thread: bool) -> bool:
    pass

  @rpc_api
  def trace_test(self, only_main_thread: bool) -> bool:
    pass

  @rpc_api
  def stop_trace(self) -> bool:
    pass

  @rpc_api
  def trace_count(self) -> int:
    pass

  @rpc_api(arm=True)
  def set_trace_scope(self, trace_scope: TraceScope) -> void:
    pass

  @rpc_api(arm=True)
  def set_trace_timeout(self, timeout_ms: int) -> void:
    """
    追踪窗口时长(毫秒): 到点自动停止, 0 = 不限时。
    未调用时默认 60000 兜底(防止"忘了停"的追踪一直跑);
    追踪进行中调用同样生效(从现在起重新计时)。
    """
    pass

  @rpc_api(arm=True)
  def set_trace_max_events(self, max_events: int) -> void:
    """事件数上限(0 = 不限): 抓到该数量事件后自动停止(与超时并列的第二个停止条件)"""
    pass

  @rpc_api
  def trace_status(self) -> str:
    """
    追踪状态(JSON 字符串), 如:
    {"running":false,"mode":"main","stop_reason":1,"stop_reason_name":"timeout",
     "timeout_ms":5000,"max_events":0,"elapsed_ms":5012,"events":456}
    stop_reason: 0 未自动停止 / 1 超时 / 2 事件数上限。
    """
    pass

  @rpc_api(arm=True)
  def trace_java_method(self, class_name: str, method_name: str, num_args: int, args: str,
      events: int = 0, timeout_ms: int = -1, max_events: int = 0) -> int:
    """
    动态 hook 一个 Java 方法, 并在每次调用期间 trace 它的执行流:
    进入方法时对该线程 arm 一轮 Java 方法级 trace(与 trace_call 同一引擎),
    方法退出即 disarm —— 单次调用就是一个追踪窗口, 递归/多线程按调用配对,
    timeout_ms/max_events 只作单次调用的兜底上限。
    产物走既有日志通道(sinker 为 DefaultSinker, 方法与参数、按调用深度缩进):
    默认 logcat(tag Albatross), 注入带 FLAG_LOG 时是应用侧滚动文件(见 se_logger/flush_log)。

    class_name/method_name/num_args/args: 目标解析(同 dyn_hook_method / find_method);
    events: EventType 位掩码, 0 = CALL|RETURN; EXEC(1)/DUMP(0x80) 不支持会被屏蔽
            (kDexPcMoved 的监听器增删在 ART 34+ 要停世界, 不能出现在执行路径上);
    timeout_ms: 单次调用窗口上限, -1 = 默认 60s 兜底, 0 = 不限时; max_events: 0 = 不限。
    返回 0 成功 / 1 同目标已安装(参数已更新) / -1 类找不到 / -2 方法找不到 / -3 安装失败。
    """
    pass

  @rpc_api(arm=True)
  def untrace_java_method(self, class_name: str, method_name: str, num_args: int, args: str) -> bool:
    """
    卸载 trace_java_method 安装的按方法 trace: 只摘本特征那一层动态 hook 回调,
    不影响同方法上其它 dyn hook 层(dyn_hook_method 等); 有在途调用时延后到该调用退出执行。
    返回是否命中一个已安装目标。
    """
    pass

  @rpc_api
  def java_method_trace_status(self) -> str:
    """
    按方法 trace 状态(JSON 字符串), 如:
    {"count":1,"targets":[{"target":"int albatross.demo.JavaMethodTraceTarget.run(int)",
     "events":2,"timeout_ms":-1,"max_events":0,"invocations":3,"live":0,
     "cancelled":false,"removed":false}],
     "trace_running":false,"stop_reason":1,"stop_reason_name":"timeout","window_events":42,
     "window_timeout_ms":-1,"window_max_events":0}
    """
    pass

  @rpc_api
  def redirect_app_log(self, file_name: str = 'app') -> bool:
    pass

  @rpc_api
  def finish_redirect_app_log(self) -> bool:
    pass

  @rpc_api(arm=True)
  def se_logger(self, log_dir: str, base_name: str, clean_old: bool = False) -> void:
    """
    把框架日志(OceanLogger/事件行、插件 log)接到应用侧滚动文件:
    <log_dir or /data/data/<pkg>/files/log>/<base_name>_<date>.log(按卷滚动);
    配 flush_log 立即落盘。缺省(未配置)时日志走 logcat(tag Albatross)。
    """
    pass

  @rpc_api
  def flush_log(self) -> void:
    """立刻把滚动日志缓冲落盘(取文件前调一次)"""
    pass

  @rpc_api(arm=True)
  def add_not_trace_package(self, pkg: str) -> bool:
    pass

  @rpc_api
  def class_loaders(self, sync: bool) -> str:
    pass

  @rpc_api
  def get_modules(self, include_sys: bool = False) -> list:
    pass

  @rpc_api
  def init_native_log(self) -> void:
    pass

  @rpc_api(arm=True)
  def watch_func(self, symbol: str, address: long) -> void:
    pass

  @rpc_api(arm=True)
  def watch_library_load(self, on: bool = True) -> void:
    pass

  @rpc_api(arm=True, is_async=True)
  def trace_native_function(self, lib_name: str, symbol: str, address: long,
      timeout_ms: int, max_events: int, flags: int, log_path: str) -> bool:
    """
    内置默认 native trace(寄存器级 + 访存字节, C++ 实现): 追踪一个 native 函数并记录
    运行过程(call/ret/block/exec + 参数/返回值/执行寄存器 + 访存读/写的数据字节),
    系统库事件被过滤; 结束(超时/上限/手动 stop_native_trace)自动落盘到 log_path。

    访存字节: 访存指令在其 EXEC 行下多打一行 mem —— 读侧是访问地址处读到的数据,
    store 是从源寄存器/立即数重建的写入数据(W* = 源不可得, 显示写前快照),
    宽度按访问宽度、上限 64 字节; 默认开启, 用 flags bit1 关闭。

    lib_name: 目标库名(子串匹配, 如 "libtarget.so"), address != 0 时忽略;
    symbol: 目标符号名, address != 0 时忽略; address: 函数地址(0 = 按库名+符号解析);
    timeout_ms: 窗口毫秒, -1 默认 60s 兜底, 0 不限时; max_events: 事件数上限 0 = 不限;
    flags: bit0 = 只记录主线程, bit1 = 不记录访存字节(默认记录); log_path: 落盘绝对路径。
    进程内单会话: 换目标返回 False, 同目标重复调用为幂等/重开窗口。
    """
    pass

  @rpc_api
  def stop_native_trace(self) -> bool:
    """停止默认 native trace 并落盘; 未启动返回 False"""
    pass

  @rpc_api
  def native_trace_status(self) -> str:
    """
    默认 native trace 状态(JSON 字符串), 如:
    {"running":false,"started":true,"target":"0x7b12..","log_path":"/data/.../native_trace_x.log",
     "stop_reason":1,"stop_reason_name":"timeout","timeout_ms":-1,"max_events":0,
     "engine_events":12345,"appended":6553,"dropped":0,"readable":6553,"ring_cells":16384,
     "file_written":true}
    stop_reason: -1 未启动 / 0 手动停 / 1 超时 / 2 事件数上限。
    已停未落盘时本查询会补写文件。
    """
    pass

  @rpc_api
  def native_trace_dump(self, max_bytes: int = 0) -> str:
    """格式化的 trace 文本(运行过程); max_bytes > 0 时截断; 未启动返回空串"""
    pass

  @rpc_api
  def dump_native_method(self) -> str:
    pass

  @broadcast_api
  def send(self, content: str, exception: str) -> void:
    if exception:
      logger.error("[#] %s %s", content, exception)
    elif not self.quiet:
      logger.info("[*] " + content)

  @broadcast_api
  def on_lib_load(self, lib_name: str, thread_id: str) -> void:
    logger.info(f'load library {lib_name} by {thread_id}')

