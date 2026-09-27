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

from albatross.inject_client import BaseClient
from albatross.rpc_client import rpc_api, void, broadcast_api
from albatross.rpc_common import long, logger


class AppClient(BaseClient):

  @rpc_api
  def get_package_name(self) -> str:
    """
    获取当前应用的包名

    Returns:
        str: 应用包名
    """

  @rpc_api
  def redirect_app_log(self, file_name: str = 'app') -> bool:
    pass

  @rpc_api
  def finish_redirect_app_log(self) -> bool:
    pass

  @rpc_api
  def set_logger(self, log_dir: str, log_file_name: str) -> void:
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

  @rpc_api
  def watch_func(self, symbol: str, address: long) -> void:
    pass

  @rpc_api
  def watch_library_load(self, on: bool = True) -> void:
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
