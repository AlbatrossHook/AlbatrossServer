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

from .albatross_client import AlbatrossClient, InjectFlag, AlbatrossInitFlags
from .rpc_client import rpc_api, broadcast_api, byte, RpcClient
from .rpc_common import void
from .wrapper import cached_class_property


class SystemServerClient(RpcClient):
  albatross_client: AlbatrossClient

  @cached_class_property
  def inject_flags(self):
    return InjectFlag.KEEP | InjectFlag.UNIX

  albatross_init_flags = AlbatrossInitFlags.FLAG_CALL_CHAIN

  @rpc_api
  def init(self) -> bool:
    """
    初始化系统服务器客户端

    Returns:
        bool: 是否初始化成功
    """

  @rpc_api
  def init_intercept(self) -> int:
    """
    初始化拦截功能

    Returns:
        int: 初始化结果
    """

  @rpc_api
  def get_top_activity(self, detail: bool = False) -> str:
    """
    获取顶层Activity信息

    Args:
        detail (bool): 是否获取详细信息，默认为False

    Returns:
        str: Activity信息
    """

  @rpc_api
  def get_front_activity(self) -> list:
    """
    获取前台Activity列表

    Returns:
        list: Activity列表
    """

  @rpc_api
  def get_front_activity_quick(self) -> list:
    """
    快速获取前台Activity列表

    Returns:
        list: Activity列表
    """

  @rpc_api
  def get_all_processes(self) -> dict:
    """
    获取所有进程信息

    Returns:
        dict: 进程信息字典
    """

  @rpc_api
  def start_activity(self, pkg: str, activity: str | None, user_id: int) -> str:
    """
    启动Activity

    Args:
        pkg (str): 包名
        activity (str | None): Activity名称
        user_id (int): 用户ID

    Returns:
        str: 启动结果
    """

  @rpc_api
  def set_top_app(self, pkg: str) -> str:
    """
    设置顶层应用

    Args:
        pkg (str): 包名

    Returns:
        str: 设置结果
    """

  def start_app(self, pkg: str):
    return self.start_activity(pkg, None, 0)

  @rpc_api
  def set_intercept_app(self, pkg: str | None, clear: bool = True) -> int:
    """
    设置拦截应用

    Args:
        pkg (str | None): 包名
        clear (bool): 是否清除之前的设置，默认为True

    Returns:
        int: 设置结果
    """

  @rpc_api
  def force_stop_app(self, pkg: str) -> bool:
    """
    强制停止应用

    Args:
        pkg (str): 包名

    Returns:
        bool: 是否停止成功
    """

  @broadcast_api
  def launch_process(self, uid: int, pid: int, pkg: str, process: str, process_info: dict) -> byte:
    if self.debug:
      print(f'launch process {uid}:{pid}:{process}', process_info)
    return byte(-1)

  @broadcast_api
  def collect_data(self, data: str) -> void:
    if self.debug:
      print('collect data', data)

  @rpc_api
  def add_watch_app(self, pkg: str, clear: bool = False) -> int:
    pass

  @rpc_api
  def set_app_android_id(self, uid: int, android_id: str) -> void:
    pass

  @rpc_api
  def get_version(self) -> int:
    pass

  @rpc_api
  def allow_app_permission(self, pkg: str, permission_name: str, uid: int) -> str:
    pass

  @rpc_api
  def mock_battery_info(self, on: bool) -> void:
    pass
