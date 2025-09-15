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
from .wrapper import cached_class_property


class SystemServerClient(RpcClient):
  albatross_client: AlbatrossClient

  @cached_class_property
  def inject_flags(self):
    return InjectFlag.KEEP | InjectFlag.UNIX

  @cached_class_property
  def albatross_init_flags(self):
    return AlbatrossInitFlags.NONE

  @rpc_api
  def init(self) -> bool:
    pass

  @rpc_api
  def init_intercept(self) -> int:
    pass

  @rpc_api
  def get_top_activity(self, detail: bool = False) -> str:
    pass

  @rpc_api
  def get_front_activity(self) -> list:
    pass

  @rpc_api
  def get_front_activity_quick(self) -> list:
    pass

  @rpc_api
  def get_all_processes(self) -> dict:
    pass

  @rpc_api
  def start_activity(self, pkg: str, activity: str | None, uid: int) -> str:
    pass

  @rpc_api
  def set_top_app(self, pkg: str) -> str:
    pass

  def start_app(self, pkg: str):
    return self.start_activity(pkg, None, 0)

  @rpc_api
  def set_intercept_app(self, pkg: str | None, clear: bool = True) -> int:
    pass

  @rpc_api
  def force_stop_app(self, pkg: str) -> bool:
    pass

  @broadcast_api
  def launch_process(self, uid: int, pid: int, process_info: dict) -> byte:
    print('launch process', process_info)
    return byte(0)
