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

from typing import Optional
from . import device

__version__ = "2.2.0"


def get_device(device_id: Optional[str] = None) -> device.AlbatrossDevice:
  return device.get_device_manager().get_devices(device_id)


def destroy():
  device.destroy_device()
  from . import rpc_client
  rpc_client.close_monitor()
  from . import plugin
  plugin.clear_plugin()
