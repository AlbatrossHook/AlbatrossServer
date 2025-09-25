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
from enum import IntEnum, IntFlag

from .rpc_client import RpcClient, byte, read_string
from .rpc_client import rpc_api, broadcast_api, void, ByteEnum


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


class InjectResult(ByteEnum):
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
  DEX_LOAD_SUCCESS = 20
  DEX_ALREADY_LOAD = 21


class SetResult(ByteEnum):
  SET_OK = 0,
  SET_ALREADY = 1,
  NOT_EXISTS = 2
  SYSTEM_SERVER_ERR = 3
  DATA_ERR = 4
  SET_CHANGE = 5


class AlbatrossClient(RpcClient):
  lib_path = None
  class_name = None

  @rpc_api
  def get_process_isa(self, pid: int) -> RunTimeISA:
    pass

  @rpc_api
  def get_service_isa(self) -> RunTimeISA:
    pass

  @rpc_api
  def get_process_pid(self, process_name: str):
    pass

  @staticmethod
  def parse_get_process_pid(data, result):
    if result >= 0:
      return struct.unpack('<i', data)[0]
    else:
      return -1

  @rpc_api
  def inject_albatross(self, pid: int, flags: InjectFlag = InjectFlag.KEEP | InjectFlag.UNIX,
      temp_dir: str | None = None) -> InjectResult:
    pass

  @rpc_api
  def set_2nd_arch_lib(self, lib_path: str) -> bool:
    pass

  @rpc_api
  def set_arch_lib(self, lib_path: str) -> bool:
    pass

  @rpc_api
  def inject(self, pid: int, flags: int, data: bytes, lib_path: str, entry_name: str, temp_dir: str) -> InjectResult:
    pass

  @rpc_api
  def load_plugin(self, pid: int, app_agent_dex: str, agent_lib: str | None, albatross_class: str, agent_class: str,
      agent_register_func: str, flags: AlbatrossInitFlags, plugin_dex: str, plugin_lib: str,
      plugin_class: str, plugin_params: str, plugin_flags: int) -> DexLoadResult:
    pass

  @rpc_api
  def load_plugin_by_id(self, pid: int, plugin_id: int) -> DexLoadResult:
    pass

  @rpc_api
  def get_address(self, pid: int) -> str:
    pass

  @rpc_api
  def load_system_plugin(self, plugin_dex: str, plugin_lib: str, plugin_class: str, plugin_params: str,
      arg_int: int) -> DexLoadResult:
    pass

  @rpc_api
  def register_plugin(self, plugin_id: int, plugin_dex: str | None, plugin_lib: str | None, plugin_class: str,
      plugin_params: str | None, arg_int: int) -> SetResult:
    pass

  @rpc_api
  def delete_plugin(self, plugin_id: int) -> byte:
    pass

  @rpc_api
  def clear_plugins(self) -> int:
    pass

  @rpc_api
  def modify_plugin(self, plugin_id: int, plugin_class: str, plugin_params: str, plugin_flags: int) -> byte:
    pass

  @rpc_api
  def delete_plugin_rule(self, plugin_id: int, app_id: int) -> bool:
    pass

  @rpc_api
  def add_plugin_rule(self, plugin_id: int, app_id: int) -> SetResult:
    pass

  @rpc_api
  def load_dex(self, pid: int, dex_path: str, lib_path: str | None, register_class: str, class_name: str,
      agent_register_func: str, flags: AlbatrossInitFlags, p1: str, p2: int) -> DexLoadResult:
    pass

  @rpc_api
  def detach(self, pid: int, flags: InjectFlag) -> bool:
    pass

  @rpc_api
  def launch(self, process_name: str, activity_name: str = None, uid: int = 0) -> str:
    pass

  @rpc_api
  def launch_intercept(self, process_name: str, activity_name: str = None, uid: int = 0) -> str:
    pass

  @rpc_api
  def set_system_server_agent(self, dex_path: str, init_class: str, server_name: str = 'system_server',
      load_flags: AlbatrossInitFlags = AlbatrossInitFlags.NONE,
      address: str | None = None, init_flags: int = 0) -> SetResult:
    pass

  @rpc_api
  def load_system_plugin(self, plugin_dex: str, plugin_lib: str | None, plugin_class: str, plugin_params: str | None,
      plugin_flags: int) -> DexLoadResult:
    pass

  @rpc_api
  def set_app_agent(self, app_agent_dex: str, agent_lib: str | None, albatross_class: str, agent_class: str,
      agent_register_func: str = "albatross_load_init",
      flags: AlbatrossInitFlags = AlbatrossInitFlags.NONE) -> SetResult:
    pass

  @broadcast_api
  def process_disconnect(self, pid: int) -> void:
    print('process disconnect', pid)

  @broadcast_api
  def system_server_die(self) -> void:
    print('system server die')

  @broadcast_api
  def launch_process(self, uid: int, pid: int, process_info: dict) -> void:
    pass

  @rpc_api
  def patch_selinux(self) -> bool:
    pass

  @rpc_api
  def is_injected(self, pid: int) -> bool:
    pass

  @rpc_api
  def uid_processes(self, uid: int, only_java: bool) -> list:
    pass

  @rpc_api
  def unload_plugin_dex(self, pid: int, plugin_id: int) -> DexLoadResult:
    pass

  @staticmethod
  def parse_uid_processes(data, result):
    if result >= 0:
      s, idx = read_string(data, 0)
      infos = s.split(',')
      processes = []
      for info in infos:
        name, pid, is_java = info.split('^_^')
        processes.append({'name': name, 'pid': int(pid), 'is_java': int(is_java)})
      return processes
    else:
      return []

  def get_java_processes_by_uid(self, uid):
    processes = self.uid_processes(uid, True)
    return [p['pid'] for p in processes if p['is_java']]
