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
from .wrapper import cached_class_property


class InjectFlag(IntEnum):
  NOTHING = 0
  DEBUG = 0x1
  ANDROID = 0x2,
  UNLOAD = 0x4
  TEST = 0x8
  KEEP = 0x10
  UNIX = 0x20


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
  FLAG_LOG = 0x10000
  REDIRECT_LOG = 0x20000


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
  DEX_SYSTEM_SERVER_ERR = 9,
  DEX_PROCESS_SLEEPING = 10,
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
  def delete_plugin(self, plugin_id: int) -> byte:
    """
    删除插件

    Args:
        plugin_id (int): 插件ID

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
  def add_plugin_rule(self, plugin_id: int, app_id: int) -> SetResult:
    """
    添加插件规则

    Args:
        plugin_id (int): 插件ID
        app_id (int): 应用ID

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
    print('process disconnect', pid)

  @broadcast_api
  def system_server_die(self) -> void:
    print('system server die')

  @broadcast_api
  def launch_process(self, uid: int, pid: int, process_info: dict) -> void:
    """
    进程启动广播

    Args:
        uid (int): 用户ID
        pid (int): 进程ID
        process_info (dict): 进程信息

    Returns:
        void: 无返回值
    """
    print(f'[*] process uid:{uid} pid:{pid} info: {process_info}')
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
