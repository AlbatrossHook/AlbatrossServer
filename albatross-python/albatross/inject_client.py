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

from enum import IntEnum, IntFlag

from albatross.rpc_client import RpcClient
from albatross.rpc_common import read_string, ByteEnum, rpc_api, byte, void


class LoadLibResult(ByteEnum):
  LOAD_LIB_SUCCESS = 0
  LOAD_LIB_ARG_ERR = 1
  LOAD_LIB_OPEN_ERR = 2
  LOAD_LIB_SYMBOL_ERR = 3
  LOAD_LIB_INIT_ERR = 4
  LOAD_LIB_SEND_ERR = 5


class RegisterResult(ByteEnum):
  REGISTER_SUCCESS = 0
  REGISTER_ARG_ERR = 1
  REGISTER_OPEN_ERR = 2
  REGISTER_SYMBOL_ERR = 3
  REGISTER_INIT_ERR = 4


class InsHookResult(IntEnum):
  HOOK_SUCCESS = 0
  ALREADY_HOOK = 1
  CLASS_NOT_FIND = -1
  METHOD_NOT_FIND = -2
  HOOK_FAIL = -3


class ExecutionOption(IntFlag):
  JIT_OSR = 1
  JIT_BASELINE = 2
  JIT_OPTIMIZED = 4

  DO_NOTHING = 0
  DECOMPILE = 8
  INTERPRETER = DECOMPILE
  DEFAULT_OPTION = 0x10

  RECOMPILE_OSR = JIT_OSR | DECOMPILE
  RECOMPILE_BASELINE = JIT_BASELINE | DECOMPILE
  RECOMPILE_OPTIMIZED = JIT_OPTIMIZED | DECOMPILE
  DISABLE_AOT = 0x20
  DISABLE_JIT = 0x40
  AOT = 0x80
  NATIVE_CODE = AOT | JIT_OPTIMIZED


class MethodScope(IntFlag):
  Static = 1
  Instance = 2
  Constructor = 4


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
    return f'[{self.exit_code}]{self.stdout}\n{self.stderr}'


class BaseClient(RpcClient):
  @rpc_api
  def load_lib(self, path: str, entry_symbol: str) -> LoadLibResult:
    pass

  @rpc_api
  def register_native_handler(self, call_name: str, over_write: bool, lib_path: str, symbol: str, args: str,
      return_type: byte) -> RegisterResult:
    pass

  def register_api(self, cls: RpcClient, name, lib, symbol):
    api_info = cls.register_apis.get(name)
    if not api_info:
      return False
    return self.register_native_handler(name, False, lib, symbol, api_info.args, api_info.ret.encode())

  @rpc_api
  def shell(self, command: str) -> ShellExecResult:
    pass

  @rpc_api
  def find_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> str:
    pass

  @rpc_api
  def hook_method(self, class_name: str, method_name: str, num_args: int, args: str = None,
      min_dex_pc: int = 0, max_dex_pc: int = 128, safe_string: bool = False) -> InsHookResult:
    """
    钩子方法，用于拦截和修改方法调用

    Args:
        class_name (str): 类名
        method_name (str): 方法名
        num_args (int): 参数数量
        args (str): 参数信息
        min_dex_pc (int): 最小的DEX程序计数器
        max_dex_pc (int): 最大的DEX程序计数器
        safe_string(bool): 参数是否可以安全的转换成字符串

    Returns:
        int: 监听器ID
    """

  @rpc_api
  def unhook_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> bool:
    """
    取消方法钩子

    Returns:
        bool: 是否成功取消钩子
    """

  @rpc_api
  def getuid(self) -> int:
    """
    获取当前进程的用户ID

    Returns:
        int: 用户ID
    """

  @rpc_api
  def decompile_all(self) -> void:
    pass

  @rpc_api
  def print_all_class_loader(self) -> str:
    pass

  @rpc_api
  def dump_all_threads(self) -> str:
    pass

  @rpc_api
  def find_class(self, cls_name: str, application: bool = True,
      exec_mode: ExecutionOption = ExecutionOption.DO_NOTHING) -> str:
    pass

  @rpc_api
  def find_sub_class(self, cls_name: str, application: bool = True) -> str:
    pass

  @rpc_api
  def hook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance,
      safe_tostring: bool = False) -> str:
    pass

  @rpc_api
  def unhook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance) -> str:
    pass

  @rpc_api
  def get_functions(self, lib_path: str) -> list:
    pass

  @rpc_api
  def set_to_string_config(self, max_length: int, show_bytes: bool = True) -> void:
    pass

  @rpc_api
  def read_file(self, path: str) -> str:
    pass

  @rpc_api
  def get_class_methods(self, cls_name: str, application: bool) -> str:
    pass

  @rpc_api
  def get_class_fields(self, cls_name: str, application: bool) -> str:
    pass

  def read_maps(self):
    return self.read_file('/proc/self/maps')

  def read_smaps(self):
    return self.read_file('/proc/self/smaps')
