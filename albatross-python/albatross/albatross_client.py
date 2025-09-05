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

from .rpc_client import RpcClient
from .rpc_client import rpc_api, broadcast_api, void, ByteEnum


class InjectFlag(IntEnum):
  NOTHING = 0
  DEBUG = 0x1
  ANDROID = 0x2,
  UNLOAD = 0x4
  TEST = 0x8
  KEEP = 0x10
  UNIX = 0x20


class LoadDexFlag(IntFlag):
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
  DEX_NOT_EXIT = 1
  DEX_NO_JVM = 2
  DEX_VM_ERR = 3
  DEX_LOAD_FAIL = 4
  DEX_CLASS_NO_FIND = 5
  DEX_INIT_FAIL = 6
  METHOD_NO_FIND = 7
  DEX_LOAD_SUCCESS = 20
  DEX_ALREADY_LOAD = 21


class DexSetResult(ByteEnum):
  DEX_SET_OK = 0,
  DEX_SET_ALREADY = 1


class AlbatrossClient(RpcClient):

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
  def load_injector(self, pid: int, app_agent_dex: str, agent_lib: str | None, albatross_class: str, agent_class: str,
      agent_register_func: str, flags: LoadDexFlag, injector_dex: str, injector_lib: str,
      injector_class: str, injector_arg_str: str, injector_arg_init: int) -> DexLoadResult:
    pass

  @rpc_api
  def load_dex(self, pid: int, dex_path: str, lib_path: str | None, register_class: str, class_name: str,
      loader_symbol_name: str, flags: LoadDexFlag) -> DexLoadResult:
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
  def set_system_server_agent(self, dex_path: str, server_name: str = 'system_server',
      load_flags: LoadDexFlag = LoadDexFlag.NONE) -> DexSetResult:
    pass

  @broadcast_api
  def process_disconnect(self, pid: int) -> void:
    print('process disconnect', pid)

  @broadcast_api
  def system_server_die(self) -> void:
    print('system server die')

  @broadcast_api
  def launch_process(self, process_info: dict):
    if self.can_send:
      raise Exception("launch_process should register handler")

  @rpc_api
  def patch_selinux(self) -> bool:
    pass

  @rpc_api
  def is_injected(self, pid: int) -> bool:
    pass
