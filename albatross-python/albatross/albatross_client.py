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

import struct
import traceback
from enum import IntEnum, IntFlag

from .rpc_client import RpcClient, byte, read_string
from .rpc_client import rpc_api, broadcast_api, void, ByteEnum
from .rpc_common import RpcCallException
from .rpc_common import u32, long, logger
from .inject_client import JvmFlag, JvmLoadResult
from .wrapper import cached_class_property


class RwbpWatchEvent:
  """rwbp 命中事件（字段与 include/albatross.h 的 AlbRwbpWatchEvent 对齐）。"""

  __slots__ = ('seq', 'far', 'pc', 'lr', 'sp', 'regs', 'rule_addr', 'kind',
               'is_write', 'esr', 'rule_len', 'tid', 'tgid')

  def __init__(self, seq, far, pc, lr, sp, regs, rule_addr, kind, is_write, esr,
      rule_len, tid, tgid):
    self.seq = seq
    self.far = far
    self.pc = pc
    self.lr = lr
    self.sp = sp
    self.regs = regs
    self.rule_addr = rule_addr
    self.kind = kind
    self.is_write = is_write
    self.esr = esr
    self.rule_len = rule_len
    self.tid = tid
    self.tgid = tgid

  @property
  def operation(self) -> str:
    return 'write' if self.is_write else 'read'

  def __repr__(self):
    return (f'RwbpWatchEvent(seq={self.seq}, {self.operation} far=0x{self.far:x} '
            f'pc=0x{self.pc:x} lr=0x{self.lr:x} tid={self.tid} '
            f'x0=0x{self.regs[0]:x} kind={self.kind})')


class RwbpWatchDrain:
  """一次 rwbp_watch_drain 的结果（含服务器侧统计与质量位）。"""

  def __init__(self, quality, tid, written, dropped, buf_lost, delivered, events):
    self.quality = quality
    self.tid = tid
    self.written = written  # 模块侧累计写入记录数
    self.dropped = dropped  # 模块环形缓冲溢出（可见丢失）
    self.buf_lost = buf_lost  # 服务器侧缓冲溢出（可见丢失）
    self.delivered = delivered  # 本次会话已交付的事件总数
    self.events = events

  @property
  def verified(self) -> bool:
    """保留位：当前服务端/agent 都不会置它，恒 False——别拿它当可信判据。"""
    return bool(self.quality & RWBP_WATCH_Q_VERIFIED)

  @property
  def blindwin(self) -> bool:
    """会话期间**目标页**被放开过（窗口内的命中可能被静默丢弃）。

    只由目标作用域的证据驱动（目标进程的 PAGE_OPEN 记录，v2 会话才有）；
    模块 ≤0.4.27 或 v1 会话恒 0——"没报盲窗"不能当成"没丢事件"。
    模块全局的窗口计数（含别人的 rwbp 页/框架 modify 规则页）不参与判位，
    要那些数请用 rwbp_watch_drain2 头的 win_opens/uaccess_opens。"""
    return bool(self.quality & RWBP_WATCH_Q_BLINDWIN)

  def __repr__(self):
    return (f'RwbpWatchDrain(events={len(self.events)}, quality=0x{self.quality:x}, '
            f'written={self.written}, dropped={self.dropped}, buf_lost={self.buf_lost})')


class RwbpWatchEventV2(RwbpWatchEvent):
  """rwbp v2 命中事件（模块 ≥0.4.28）：v1 字段 + 时间戳/数据字节。

  - time_mono_ns / time_real_ns：fault 时刻时间戳（ts_src 位掩码判断可用性）；
  - data / data_len：数据字节快照。读事件=访问前内存；写事件=单步后落地字节
    （data_flags 带 RWBP_WATCH_DATA_AFTER），stp/SIMD 也能直接拿到值。
    data_len 是"从 far 起页内连续可读的字节数"（上限 32），**不是访问宽度**；
  - kind 3 = PAGE_OPEN（盲窗时刻记录；这类记录在 drain 里被计成 page_opens）。
  """

  __slots__ = ('time_mono_ns', 'time_real_ns', 'data_len', 'data_flags', 'data')

  def __init__(self, base: RwbpWatchEvent, time_mono_ns: int, time_real_ns: int,
      data_len: int, data_flags: int, data: bytes):
    super().__init__(base.seq, base.far, base.pc, base.lr, base.sp, base.regs,
      base.rule_addr, base.kind, base.is_write, base.esr,
      base.rule_len, base.tid, base.tgid)
    self.time_mono_ns = time_mono_ns
    self.time_real_ns = time_real_ns
    self.data_len = data_len
    self.data_flags = data_flags
    self.data = data

  @property
  def data_after(self) -> bool:
    """写事件：data 是单步执行后的落地字节。读事件恒 False。"""
    return bool(self.data_flags & RWBP_WATCH_DATA_AFTER)

  @property
  def value(self) -> int:
    """data[] 里按访存宽度读出的值（小端）。

    宽度取自指令（regs/pc 需自行解码）——这里按 data_len（页内窗口）给上限，
    调用方要精确宽度请自行截断；无数据（旧模块/旧会话）时返回 0。"""
    n = min(self.data_len, 8)
    return int.from_bytes(self.data[:n], 'little') if n else 0

  def __repr__(self):
    return (f'RwbpWatchEventV2(seq={self.seq}, {self.operation} far=0x{self.far:x} '
            f'pc=0x{self.pc:x} tid={self.tid} data_len={self.data_len} '
            f'data={self.data[:self.data_len].hex()} kind={self.kind})')


class RwbpWatchDrain2:
  """一次 rwbp_watch_drain2 的结果（v2 事件 + 盲窗台账 + 模块信息）。

  - page_opens 是**目标进程**的 PAGE_OPEN 记录数（已按目标 tid/tgid 过滤），
    它驱动 `blindwin`；
  - win_opens/win_open_now/uaccess_opens/win_ns 是**模块全局**计数（会话期间
    模块里任何规则的页，不区分 mm——别的 rwbp 使用者、框架自己的 modify 规则
    页都算），只作信息透出，别拿它们判"我的页"；
  - 服务端模块 ≤0.4.27 时以上字段全 0；rec_size 与本客户端预期（424）不符
    说明模块/头文件 ABI 漂移（服务端此时按 v1 前缀交付，事件尾全 0）。"""

  def __init__(self, quality, tid, written, dropped, buf_lost, delivered, events,
      win_opens, win_open_now, uaccess_opens, page_opens, filtered_pc,
      ts_src, rec_size, abi_version, win_ns):
    self.quality = quality
    self.tid = tid
    self.written = written
    self.dropped = dropped
    self.buf_lost = buf_lost
    self.delivered = delivered
    self.events = events
    self.win_opens = win_opens  # 盲窗（grace 窗口）打开次数（按页）
    self.win_open_now = win_open_now  # 当前仍放开的页数
    self.uaccess_opens = uaccess_opens  # EL1 uaccess 导致的放开（不会自动回保护）
    self.page_opens = page_opens  # 事件流里观察到的 PAGE_OPEN 记录数
    self.filtered_pc = filtered_pc  # 被 PC 包含过滤拒掉的记录数（本链路没开，恒 0）
    self.ts_src = ts_src  # 时间源位掩码：1=mono 2=real；0=不可用
    self.rec_size = rec_size  # 模块侧记录大小（应等于 424）
    self.abi_version = abi_version  # 模块 RWBP_VERSION_CODE
    self.win_ns = win_ns  # 已关闭盲窗的累计开放时长

  @property
  def verified(self) -> bool:
    """保留位：当前没有任何一端置它，恒 False（判可信看 `blindwin`）。"""
    return bool(self.quality & RWBP_WATCH_Q_VERIFIED)

  @property
  def blindwin(self) -> bool:
    """会话期间**目标页**被放开过（窗口内命中可能被静默丢弃；见类注释）。"""
    return bool(self.quality & RWBP_WATCH_Q_BLINDWIN)

  @property
  def v2(self) -> bool:
    """事件带可用的 v2 尾（时间戳 + 数据字节）：ENABLE2 会话且模块记录尺寸
    与客户端一致；不一致时服务端按 v1 前缀交付、此位为 False。"""
    return bool(self.quality & RWBP_WATCH_Q_V2)

  @property
  def ts_mono_ok(self) -> bool:
    return bool(self.ts_src & RWBP_WATCH_TS_MONO)

  @property
  def ts_real_ok(self) -> bool:
    return bool(self.ts_src & RWBP_WATCH_TS_REAL)

  def __repr__(self):
    return (f'RwbpWatchDrain2(events={len(self.events)}, quality=0x{self.quality:x}, '
            f'written={self.written}, dropped={self.dropped}, buf_lost={self.buf_lost}, '
            f'win_opens={self.win_opens}, uaccess_opens={self.uaccess_opens}, '
            f'abi_version=0x{self.abi_version:x})')


# 质量位：rwbp watch 会话能证明什么
RWBP_WATCH_Q_ACTIVE = 1  # 会话进行中
RWBP_WATCH_Q_EVENTS = 2  # 至少交付过一次命中
RWBP_WATCH_Q_RINGLOSS = 4  # 有可见丢失（模块环/服务器缓冲溢出）
RWBP_WATCH_Q_VERIFIED = 8  # 保留位：当前没有任何一端置它（别当可信判据）
RWBP_WATCH_Q_BLINDWIN = 16  # 目标页被放开过（目标作用域证据；v1 会话/≤0.4.27 恒 0）
RWBP_WATCH_Q_V2 = 32  # 事件带可用 v2 尾（ENABLE2 且模块记录尺寸一致）

# 事件尾巴的 data_flags
RWBP_WATCH_DATA_AFTER = 1  # data 是单步执行后的落地字节（写事件）
# 模块时间源位掩码（server 头里的 ts_src）
RWBP_WATCH_TS_MONO = 1
RWBP_WATCH_TS_REAL = 2
# 模块侧 v2 记录大小（rec_size 对照值；不一致 = 模块/头文件 ABI 漂移）
RWBP_WATCH_REC_SIZE_V2 = 424

_RWBP_WATCH_DRAIN_HEADER = '<iiiqqqq'
_RWBP_WATCH_EVENT = '<37Q4I2i'  # 320 字节，与 C 端 AlbRwbpWatchEvent / server RwbpWatchEvent 对齐
# v2（376 字节，与 server RwbpWatchEventV2 对齐）：320 + 2*u64 + 2*u32 + 32B
_RWBP_WATCH_EVENT_V2 = '<37Q4I2i2Q2I32s'
# v2 头（116 字节）：前 44 字节与 v1 头一致 + 9 个 i64 台账/模块信息
_RWBP_WATCH_DRAIN_HEADER2 = '<iiiqqqq9q'


def _parse_rwbp_watch_event(fields) -> RwbpWatchEvent:
  return RwbpWatchEvent(
    seq=fields[0], far=fields[1], pc=fields[2], lr=fields[3], sp=fields[4],
    regs=fields[5:36], rule_addr=fields[36], kind=fields[37],
    is_write=fields[38], esr=fields[39], rule_len=fields[40],
    tid=fields[41], tgid=fields[42])


def parse_rwbp_watch_drain(data: bytes) -> RwbpWatchDrain:
  """解析 rwbp_watch_drain 返回的原始字节（v1 事件：320 字节/条）。"""
  if data is None:
    # 服务端错误回复只有结果码、没有 payload（例：-ENOMEM）
    raise RpcCallException('rwbp_watch_drain 无 payload（服务端错误回复）')
  count, quality, tid, written, dropped, buf_lost, delivered = struct.unpack_from(
    _RWBP_WATCH_DRAIN_HEADER, data, 0)
  events = []
  off = struct.calcsize(_RWBP_WATCH_DRAIN_HEADER)
  size = struct.calcsize(_RWBP_WATCH_EVENT)
  for _ in range(count):
    fields = struct.unpack_from(_RWBP_WATCH_EVENT, data, off)
    off += size
    events.append(_parse_rwbp_watch_event(fields))
  return RwbpWatchDrain(quality, tid, written, dropped, buf_lost, delivered, events)


def parse_rwbp_watch_drain2(data: bytes) -> RwbpWatchDrain2:
  """解析 rwbp_watch_drain2 返回的原始字节（v2 事件 + 盲窗台账）。

  服务端模块 ≤0.4.27 时事件尾与台账字段全 0（事件仍可用，只是没有时间戳/
  数据字节/盲窗计数）。rec_size 与 RWBP_WATCH_REC_SIZE_V2 不一致说明模块与
  客户端头文件 ABI 漂移，事件字段可能错位——别用。"""
  if data is None:
    raise RpcCallException('rwbp_watch_drain2 无 payload（服务端错误回复）')
  (count, quality, tid, written, dropped, buf_lost, delivered, win_opens,
   win_open_now, uaccess_opens, page_opens, filtered_pc, ts_src, rec_size,
   abi_version, win_ns) = struct.unpack_from(_RWBP_WATCH_DRAIN_HEADER2, data, 0)
  events = []
  off = struct.calcsize(_RWBP_WATCH_DRAIN_HEADER2)
  size = struct.calcsize(_RWBP_WATCH_EVENT_V2)
  for _ in range(count):
    fields = struct.unpack_from(_RWBP_WATCH_EVENT_V2, data, off)
    off += size
    events.append(RwbpWatchEventV2(
      base=_parse_rwbp_watch_event(fields[:43]),
      time_mono_ns=fields[43], time_real_ns=fields[44],
      data_len=fields[45], data_flags=fields[46], data=fields[47]))
  return RwbpWatchDrain2(quality, tid, written, dropped, buf_lost, delivered,
    events, win_opens, win_open_now, uaccess_opens,
    page_opens, filtered_pc, ts_src, rec_size, abi_version,
    win_ns)


class InjectFlag(IntFlag):
  NOTHING = 0
  DEBUG = 0x1
  ANDROID = 0x2,
  UNLOAD = 0x4
  TEST = 0x8
  KEEP = 0x10
  UNIX = 0x20
  SOCKET = 0x40
  MEMFD = 0x80
  # W^X 模式：目标进程的 seccomp 策略禁 RWX（mprotect 的 W|X 组合）时必须置位——
  # 代码写改走 /proc/self/mem 免翻转后端、目标入口只写单字补丁，否则装 hook 会让
  # minijail 直接 abort 目标进程。机制见 doc/framework_feedback/req-wxorx-seccomp-no-rwx-20261009.md
  WXORX = 0x100


class AlbatrossInitFlags(IntFlag):
  NONE = 0
  INIT_CLASS = 0x1
  DEBUG = 0x2
  LOADER_FROM_CALLER = 0x4
  FLAG_DISABLE_JIT = 0x8
  FLAG_SUSPEND_VM = 0x10
  FLAG_NO_COMPILE = 0x20
  FLAG_FIELD_BACKUP_INSTANCE = 0x40
  FLAG_FIELD_BACKUP_STATIC = 0x80
  FLAG_FIELD_BACKUP_BAN = 0x100
  FLAG_FIELD_DISABLED = 0x200
  FLAG_INJECT = 0x800
  FLAG_INIT_RPC = 0x1000
  FLAG_CALL_CHAIN = 0x2000
  FLAG_ANTI_DETECTION = 0x4000
  FLAG_INTERPRETER = 0x8000
  # FLAG_NOT_INS_HOOK = 0x10000

  FLAG_LOG = 0x80000
  REDIRECT_LOG = 0x100000


class InjectResult(ByteEnum):
  INJECT_PROCESS_SLEEPING = -6,
  ARCH_NO_SUPPORT = -5,
  PROCESS_DEAD = -4,
  NO_LIB = -3,
  FAIL = -2,
  CREATE_FAIL = -1,
  SUCCESS = 0,
  ALREADY = 1,


class RunTimeISA(ByteEnum):
  ISA_ARM = 1
  ISA_ARM64 = 2
  ISA_X86 = 3
  ISA_X86_64 = 4


class DexLoadResult(ByteEnum):
  DEX_SEND_ERR = 0
  DEX_NOT_EXIT = 1
  DEX_NO_JVM = 2
  DEX_VM_ERR = 3
  DEX_LOAD_FAIL = 4
  DEX_CLASS_NO_FIND = 5
  DEX_INIT_FAIL = 6
  METHOD_NO_FIND = 7
  DEX_SYSTEM_SERVER_ERR = 9
  DEX_PROCESS_SLEEPING = 10
  DEX_LOAD_SUCCESS = 20
  DEX_ALREADY_LOAD = 21


class SetResult(ByteEnum):
  SET_OK = 0,
  SET_ALREADY = 1,
  NOT_EXISTS = 2
  SYSTEM_SERVER_ERR = 3
  DATA_ERR = 4
  SET_CHANGE = 5
  MISS_INFO = 6


class MountResult(ByteEnum):
  MOUNT_SUCCESS = 0
  MOUNT_OPEN_FAIL = 1
  MOUNT_FORK_FAIL = 2
  MOUNT_SET_NS_FAIL = 3
  MOUNT_FAIL = 4
  MOUNT_SWITCH_FAIL = 5


class ShellExecResult(object):

  def __init__(self, exit_code, stdout, stderr):
    self.exit_code = exit_code
    self.stdout = stdout
    self.stderr = stderr

  @staticmethod
  def parse_value(data, result):
    s, _ = read_string(data, 0)
    if s:
      exit_code, stdout_len, shell_str = s.split(':', maxsplit=2)
      stdout_len = int(stdout_len)
      stdout = shell_str[:stdout_len]
      stderr = shell_str[stdout_len + 1:]
      return ShellExecResult(int(exit_code), stdout, stderr)
    return None

  def __repr__(self):
    if self.stdout:
      return self.stdout
    if self.stderr:
      return self.stderr
    return f'exit:{self.exit_code}'


class AlbatrossClient(RpcClient):
  lib_path = None
  class_name = None

  @rpc_api
  def get_process_isa(self, pid: int) -> RunTimeISA:
    """
    获取指定进程的指令集架构

    Args:
        pid (int): 进程ID

    Returns:
        RunTimeISA: 运行时指令集架构
    """

  @rpc_api
  def get_service_isa(self) -> RunTimeISA:
    """
    获取服务的指令集架构

    Returns:
        RunTimeISA: 运行时指令集架构
    """

  @rpc_api
  def get_process_pid(self, process_name: str):
    """
    根据进程名获取进程ID

    Args:
        process_name (str): 进程名称

    Returns:
        int: 进程ID，如果未找到返回-1
    """

  @staticmethod
  def parse_get_process_pid(data, result):
    if result >= 0:
      return struct.unpack('<i', data)[0]
    else:
      return -1

  @rpc_api
  def inject_albatross(self, pid: int, flags: InjectFlag = InjectFlag.KEEP | InjectFlag.UNIX,
      temp_dir: str | None = None) -> InjectResult:
    """
    向指定进程注入Albatross

    Args:
        pid (int): 目标进程ID
        flags (InjectFlag): 注入标志，默认为KEEP|UNIX
        temp_dir (str | None): 临时目录路径

    Returns:
        InjectResult: 注入结果
    """

  @rpc_api
  def set_2nd_arch_lib(self, lib_path: str) -> SetResult:
    """
    设置第二架构库路径

    Args:
        lib_path (str): 库文件路径

    Returns:
        bool: 是否设置成功
    """

  @rpc_api
  def set_arch_lib(self, lib_path: str) -> SetResult:
    """
    设置架构库路径

    Args:
        lib_path (str): 库文件路径

    Returns:
        bool: 是否设置成功
    """

  @rpc_api
  def inject(self, pid: int, flags: int, data: bytes, lib_path: str, entry_name: str, temp_dir: str) -> InjectResult:
    """
    注入自定义代码到指定进程

    Args:
        pid (int): 目标进程ID
        flags (int): 注入标志
        data (bytes): 注入数据
        lib_path (str): 库文件路径
        entry_name (str): 入口点名称
        temp_dir (str): 临时目录路径

    Returns:
        InjectResult: 注入结果
    """

  @rpc_api
  def set_app_info(self, uid: int, info: str | None) -> void:
    pass

  @rpc_api
  def get_app_info(self, uid: int) -> str:
    pass

  @rpc_api
  def load_plugin(self, pid: int, app_agent_dex: str, agent_lib: str | None, albatross_class: str, agent_class: str,
      agent_register_func: str, flags: AlbatrossInitFlags, extra_info: str | None, plugin_dex: str, plugin_lib: str,
      plugin_class: str, plugin_params: str, plugin_flags: int) -> DexLoadResult:
    """
    加载插件到指定进程

    Args:
        pid (int): 目标进程ID
        app_agent_dex (str): 应用代理DEX文件路径
        agent_lib (str | None): 代理库文件路径
        albatross_class (str): Albatross类名
        agent_class (str): 代理类名
        agent_register_func (str): 代理注册函数名
        flags (AlbatrossInitFlags): 初始化标志
        plugin_dex (str): 插件DEX文件路径
        plugin_lib (str): 插件库文件路径
        plugin_class (str): 插件类名
        plugin_params (str): 插件参数
        plugin_flags (int): 插件标志

    Returns:
        DexLoadResult: DEX加载结果
    """

  @rpc_api
  def load_plugin_by_id(self, pid: int, plugin_id: int) -> DexLoadResult:
    """
    根据插件ID加载插件

    Args:
        pid (int): 目标进程ID
        plugin_id (int): 插件ID

    Returns:
        DexLoadResult: DEX加载结果
    """

  @rpc_api
  def get_address(self, pid: int) -> str:
    """
    获取指定进程的地址信息

    Args:
        pid (int): 进程ID

    Returns:
        str: 地址信息
    """

  @rpc_api
  def load_system_plugin(self, plugin_dex: str, plugin_lib: str, plugin_class: str, plugin_params: str,
      arg_int: int) -> DexLoadResult:
    """
    加载系统插件

    Args:
        plugin_dex (str): 插件DEX文件路径
        plugin_lib (str): 插件库文件路径
        plugin_class (str): 插件类名
        plugin_params (str): 插件参数
        arg_int (int): 整数参数

    Returns:
        DexLoadResult: DEX加载结果
    """

  @rpc_api
  def get_plugin_id(self, plugin_dex: str, plugin_class: str) -> int:
    pass

  @rpc_api
  def register_plugin(self, plugin_id: int, plugin_dex: str | None, plugin_lib: str | None, plugin_class: str,
      plugin_params: str | None, arg_int: int) -> SetResult:
    """
    注册插件

    Args:
        plugin_id (int): 插件ID
        plugin_dex (str | None): 插件DEX文件路径
        plugin_lib (str | None): 插件库文件路径
        plugin_class (str): 插件类名
        plugin_params (str | None): 插件参数
        arg_int (int): 整数参数

    Returns:
        SetResult: 设置结果
    """

  @rpc_api
  def delete_plugin(self, plugin_id: int, affect_exist: bool = False) -> byte:
    """
    删除插件

    Args:
        plugin_id (int): 插件ID
        affect_exist(bool): 是否对已经注入的app生效

    Returns:
        byte: 删除结果
    """

  @rpc_api
  def clear_plugins(self, affect_exist: bool = False) -> int:
    """
    清除所有插件

    Returns:
        int: 清除的插件数量
    """

  @rpc_api
  def modify_plugin(self, plugin_id: int, plugin_class: str, plugin_params: str, plugin_flags: int) -> byte:
    """
    修改插件配置

    Args:
        plugin_id (int): 插件ID
        plugin_class (str): 插件类名
        plugin_params (str): 插件参数
        plugin_flags (int): 插件标志

    Returns:
        byte: 修改结果
    """

  @rpc_api
  def delete_plugin_rule(self, plugin_id: int, app_id: int) -> bool:
    """
    删除插件规则

    Args:
        plugin_id (int): 插件ID
        app_id (int): 应用ID

    Returns:
        bool: 是否删除成功
    """

  @rpc_api
  def add_plugin_rule(self, plugin_id: int, app_id: int, process: str | None = None) -> SetResult:
    """
    添加插件规则

    Args:
        plugin_id (int): 插件ID
        app_id (int): 应用ID
        process (str):进程名（for uid=1000）

    Returns:
        SetResult: 设置结果
    """

  @rpc_api
  def load_dex(self, pid: int, dex_path: str, lib_path: str | None, register_class: str, class_name: str,
      agent_register_func: str, flags: AlbatrossInitFlags, p1: str, p2: int) -> DexLoadResult:
    """
    加载DEX文件到指定进程

    Args:
        pid (int): 目标进程ID
        dex_path (str): DEX文件路径
        lib_path (str | None): 库文件路径
        register_class (str): 注册类名
        class_name (str): 类名
        agent_register_func (str): 代理注册函数名
        flags (AlbatrossInitFlags): 初始化标志
        p1 (str): 参数1
        p2 (int): 参数2

    Returns:
        DexLoadResult: DEX加载结果
    """

  @rpc_api
  def load_jvm(self, pid: int, libart_path: str | None = None, classpath: str | None = None,
      library_path: str | None = None, flags: JvmFlag = JvmFlag(0)) -> JvmLoadResult:
    """
    在没有 Java VM 的目标进程（需已注入 albatross）里创建 JVM，
    之后 load_dex / load_plugin / Java hook 等能力才可用。

    Args:
        pid (int): 目标进程ID
        libart_path (str | None): libart 路径，None/空 用设备默认 "libart.so"
        classpath (str | None): JVM classpath（':' 分隔的 dex/apk/jar 列表）
        library_path (str | None): -Djava.library.path（System.loadLibrary 查找目录）
        flags (JvmFlag): JVM_FLAG_* 组合，见 inject_client.JvmFlag

    Returns:
        JvmLoadResult: JVM_LOAD_SUCCESS / JVM_ALREADY_LOADED / 具体失败码
    """

  @rpc_api
  def detach(self, pid: int, flags: InjectFlag) -> bool:
    """
    从指定进程分离

    Args:
        pid (int): 目标进程ID
        flags (InjectFlag): 分离标志

    Returns:
        bool: 是否分离成功
    """

  @rpc_api
  def launch(self, process_name: str, activity_name: str = None, uid: int = 0) -> str:
    """
    启动应用进程

    Args:
        process_name (str): 进程名称
        activity_name (str): Activity名称，可选
        uid (int): 用户ID，默认为0

    Returns:
        str: 启动结果
    """

  @rpc_api
  def launch_intercept(self, process_name: str, activity_name: str = None, uid: int = 0) -> str:
    """
    启动应用进程并拦截

    Args:
        process_name (str): 进程名称
        activity_name (str): Activity名称，可选
        uid (int): 用户ID，默认为0

    Returns:
        str: 启动结果
    """

  @rpc_api
  def set_system_server_agent(self, dex_path: str, init_class: str, server_name: str = 'system_server',
      load_flags: AlbatrossInitFlags = AlbatrossInitFlags.NONE,
      address: str | None = None, init_flags: int = 0) -> SetResult:
    """
    设置系统服务器代理

    Args:
        dex_path (str): DEX文件路径
        init_class (str): 初始化类名
        server_name (str): 服务器名称，默认为'system_server'
        load_flags (AlbatrossInitFlags): 加载标志，默认为NONE
        address (str | None): 地址，可选
        init_flags (int): 初始化标志，默认为0

    Returns:
        SetResult: 设置结果
    """

  @rpc_api
  def load_system_plugin(self, plugin_dex: str, plugin_lib: str | None, plugin_class: str, plugin_params: str | None,
      plugin_flags: int) -> DexLoadResult:
    """
    加载系统插件

    Args:
        plugin_dex (str): 插件DEX文件路径
        plugin_lib (str | None): 插件库文件路径
        plugin_class (str): 插件类名
        plugin_params (str | None): 插件参数
        plugin_flags (int): 插件标志

    Returns:
        DexLoadResult: DEX加载结果
    """

  @rpc_api
  def set_app_agent(self, app_agent_dex: str, agent_lib: str | None, albatross_class: str, agent_class: str,
      agent_register_func: str = "albatross_load_init",
      flags: AlbatrossInitFlags = AlbatrossInitFlags.NONE) -> SetResult:
    """
    设置应用代理

    Args:
        app_agent_dex (str): 应用代理DEX文件路径
        agent_lib (str | None): 代理库文件路径
        albatross_class (str): Albatross类名
        agent_class (str): 代理类名
        agent_register_func (str): 代理注册函数名，默认为"albatross_load_init"
        flags (AlbatrossInitFlags): 初始化标志，默认为NONE

    Returns:
        SetResult: 设置结果
    """

  @broadcast_api
  def process_disconnect(self, pid: int) -> void:
    logger.info('process disconnect %d', pid)

  @broadcast_api
  def system_server_die(self) -> void:
    logger.info('system server die')

  @broadcast_api
  def launch_process(self, uid: int, pid: int, pkg: str, process: str, process_info: dict) -> void:
    """
    进程启动广播

    Args:
        uid (int): 用户ID
        pid (int): 进程ID
        process_info (dict): 进程信息

    Returns:
        void: 无返回值
    """
    self.log(f'[*] process uid:{uid} pid:{pid} process:{process} info: {process_info}')
    callbacks = self.launch_callback.get(uid)
    if callbacks:
      self.invoke_callbacks(callbacks, uid, pid, process_info)

  def invoke_callbacks(self, callbacks, uid, pid, process_info):
    to_removed = []
    for callback in callbacks:
      try:
        callback(uid, pid, process_info)
      except Exception as e:
        traceback.print_exc()
        to_removed.append(callback)
    for callback in to_removed:
      callbacks.remove(callback)

  @cached_class_property
  def launch_callback(self):
    return {}

  # uid → 武装脚本（(method, args, kwargs) 列表）。记录端（app client 开启
  # start_arm_recording 后）与重放端（launch 重启后新建的 client）共享同一份列表。
  @cached_class_property
  def arm_scripts(self):
    return {}

  def bind_arm_script(self, uid, client):
    """把 uid 的共享武装脚本绑到 client 上：绑定的 client 开启记录后写入的就是
    这份列表；进程重启后新建的 client 绑同一份，reconnect() 时自动重放。"""
    script = self.arm_scripts.setdefault(uid, [])
    client.bind_arm_script(script)
    return script

  def clear_arm_script(self, uid):
    self.arm_scripts.pop(uid, None)

  def register_launch_callback(self, uid, callback):
    launch_callbacks = self.launch_callback
    if uid in launch_callbacks:
      launch_callbacks[uid].append(callback)
    else:
      launch_callbacks[uid] = [callback]

  def unregister_launch_callback(self, uid, callback):
    launch_callbacks = self.launch_callback
    if uid in launch_callbacks:
      target_callbacks: list = launch_callbacks[uid]
      if callback in target_callbacks:
        target_callbacks.remove(callback)

  @rpc_api
  def patch_selinux(self) -> bool:
    """
    修补SELinux策略

    Returns:
        bool: 是否修补成功
    """

  @rpc_api
  def add_selinux_rule(self, source: str, target: str, klass: str, perm: str) -> int:
    """
    动态向当前 SELinux 策略追加 allow 规则：allow <source> <target>:<klass> { <perm> }

    用于注入 vendor 守护进程（qcrild/qcrilNrd 等）这类需要在线补权限的场景——
    目标专属规则不进基础补丁表，由调用方按需添加，例如：
      rild   rild                    process            execmem
      domain dalvikcache_data_file   dir                search          # 部署 so 的目录遍历
      domain shell_data_file         dir                search
      adbd   domain                  unix_stream_socket connectto,read,write  # adb forward 连目标 socket
    （规则立即生效、重启前一直有效；source/target 用已存在的类型或属性名，
     perms 逗号分隔。背景见 doc/pitfalls/pitfall-inject-fail-no-detach-20261009.md）

    Args:
        source (str): 源域/属性（如 rild、adbd、domain）
        target (str): 目标类型/属性（如 rild、domain，或 "$self"）
        klass (str): 目标类（如 process/dir/file/unix_stream_socket）
        perm (str): 权限，逗号分隔多条（如 "connectto,read,write"）

    Returns:
        int: 成功 ensure 的权限条数（>0，含原本已存在的）；负值为错误码
             （-1 参数、-2 读策略失败、-3 isids 失败、-4 写回失败、-5 全部 perm 失败、
              -6/-7/-8 source/target/class 不存在）
    """

  @rpc_api
  def is_injected(self, pid: int) -> bool:
    """
    检查指定进程是否已注入

    Args:
        pid (int): 进程ID

    Returns:
        bool: 是否已注入
    """

  @rpc_api
  def uid_processes(self, uid: int, only_java: bool) -> list:
    """
    获取指定用户ID的进程列表

    Args:
        uid (int): 用户ID
        only_java (bool): 是否只返回Java进程

    Returns:
        list: 进程信息列表
    """

  @rpc_api
  def unload_plugin_dex(self, pid: int, plugin_id: int) -> DexLoadResult:
    """
    卸载指定进程的插件DEX

    Args:
        pid (int): 目标进程ID
        plugin_id (int): 插件ID

    Returns:
        DexLoadResult: DEX卸载结果
    """

  @rpc_api
  def is_lsposed_injected(self) -> bool:
    pass

  @rpc_api
  def disable_plugin(self, pid: int, plugin_id: int) -> DexLoadResult:
    pass

  @rpc_api
  def shell(self, command: str) -> ShellExecResult:
    pass

  @rpc_api
  def process_uid(self, pid: int) -> int:
    pass

  @rpc_api
  def mount(self, pid: int, mount_path: str, is_mount: bool = True, fork: bool = False) -> MountResult:
    pass

  @rpc_api
  def add_launch_mount(self, mount_path: str) -> bool:
    pass

  @rpc_api
  def add_launch_umount(self, mount_path: str) -> bool:
    pass

  @rpc_api
  def remove_launch_umount(self, mount_path: str = None) -> byte:
    pass

  @rpc_api
  def mount_config(self, pid: int) -> MountResult:
    pass

  def umount(self, pid: int, mount_path: str, fork: bool = True) -> MountResult:
    return self.mount(pid, mount_path, False, fork)

  @rpc_api
  def watch_app(self, uid: int) -> bool:
    pass

  @rpc_api
  def support_extend_kpm(self) -> bool:
    pass

  @rpc_api
  def rwbp_watch_add(self, tid: int, addr: long, size: u32, watch_type: u32 = 3) -> int:
    """给 tid 所在进程的 [addr, addr+size) 设 rwbp 内核读写断点。

    由服务器（root）执行，用于**跨进程**监视；type: 1=读 2=写 3=读写。
    同进程内自己设点更快，可直接用 C API AlbRwbpWatchAdd（见 include/albatross.h）。
    注意：普通断点在同页出现非命中访问后会把整页放开 5ms，窗口内的命中会静默
    丢失——服务端模块 ≥0.4.28 时用 rwbp_watch_drain2 读 `page_opens`/`blindwin`
    （**目标作用域**：目标进程的 PAGE_OPEN 记录），热页据此判结果可信度；
    win_opens/uaccess_opens 是模块全局计数，只能当参考；≤0.4.27 无计数，只能按
    尽力而为对待（见 kpms/rwbp/poc/README.md）。
    结束务必调用 rwbp_watch_del。
    返回：0 = 成功；<0 = -errno（模块不在位/权限不足/参数非法等）。
    """
    pass

  @rpc_api
  def rwbp_watch_del(self) -> int:
    """删除当前会话的断点并关闭事件通道。返回 0 或 -errno。"""
    pass

  @rpc_api
  def rwbp_watch_drain(self, max_events: u32 = 0) -> bytes:
    """取出服务器缓冲的命中事件（原始字节，用 parse_rwbp_watch_drain 解析）。

    v1 视图（320 字节/条），不含时间戳/数据字节；要这些用 rwbp_watch_drain2。"""
    pass

  @rpc_api
  def rwbp_watch_drain2(self, max_events: u32 = 0) -> bytes:
    """取出服务器缓冲的 v2 事件 + 盲窗台账（原始字节，用 parse_rwbp_watch_drain2 解析）。

    事件带 fault 时间戳与数据字节（读=访问前内存、写=单步后落地字节），头里带
    page_opens（目标作用域，驱动 blindwin）/win_opens/uaccess_opens（模块全局）/
    ts_src/rec_size/abi_version。服务端模块 ≤0.4.27 或记录尺寸与客户端不一致时
    这些字段全 0（事件仍能取，只是退化为 v1 内容）。"""
    pass

  @rpc_api
  def hide_path(self, path: str, uid: u32 = 10000) -> bool:
    pass

  @rpc_api
  def redirect_path(self, uid: u32, src_path: str, dst_path: str) -> bool:
    pass

  @rpc_api
  def set_dex_load_timeout(self, sec: u32) -> int:
    pass

  @rpc_api
  def set_inject_flags(self, inject_flags: InjectFlag, temp_path: str) -> bool:
    pass

  @staticmethod
  def parse_uid_processes(data, result):
    if result >= 0:
      s, idx = read_string(data, 0)
      if not s:
        return []
      infos = s.split('\n')
      processes = []
      for info in infos:
        name, pid, is_java = info.split('|')
        processes.append({'name': name, 'pid': int(pid), 'is_java': int(is_java)})
      return processes
    else:
      return []

  def get_java_processes_by_uid(self, uid):
    if not uid:
      return []
    processes = self.uid_processes(uid, True)
    return [p['pid'] for p in processes if p['is_java']]
