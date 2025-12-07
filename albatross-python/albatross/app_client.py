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
from enum import IntEnum

from albatross.rpc_client import RpcClient, rpc_api, void, broadcast_api


class InsHookResult(IntEnum):
  HOOK_SUCCESS = 0
  ALREADY_HOOK = 1
  CLASS_NOT_FIND = -1
  METHOD_NOT_FIND = -2
  HOOK_FAIL = -3


class AppClient(RpcClient):

  @rpc_api
  def getuid(self) -> int:
    """
    获取当前进程的用户ID

    Returns:
        int: 用户ID
    """

  @rpc_api
  def get_package_name(self) -> str:
    """
    获取当前应用的包名

    Returns:
        str: 应用包名
    """

  @rpc_api
  def find_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> str:
    pass

  @rpc_api
  def hook_method(self, class_name: str, method_name: str, num_args: int, args: str = None,
      min_dex_pc: int = 0, max_dex_pc: int = 128) -> InsHookResult:
    """
    钩子方法，用于拦截和修改方法调用

    Args:
        class_name (str): 类名
        method_name (str): 方法名
        num_args (int): 参数数量
        args (str): 参数信息
        min_dex_pc (int): 最小的DEX程序计数器
        max_dex_pc (int): 最大的DEX程序计数器

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
  def print_all_class_loader(self) -> str:
    pass

  @rpc_api
  def redirect_app_log(self, file_name: str = 'app') -> bool:
    pass

  @rpc_api
  def finish_redirect_app_log(self) -> bool:
    pass

  @rpc_api
  def set_logger(self, log_dir: str, log_file_name: str) -> void:
    pass

  @broadcast_api
  def send(self, content: str, exception: str) -> void:
    if exception:
      print("[#]", content, exception)
    else:
      print("[*] " + content)
