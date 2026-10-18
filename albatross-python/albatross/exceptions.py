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

class AlbatrossException(Exception):
  pass


class DeviceOffline(AlbatrossException):
  def __init__(self, device):
    self.device = device

  def __repr__(self):
    return f'device {self.device} offline'

  __str__ = __repr__


class DeviceNoFindErr(AlbatrossException):
  def __init__(self, device_id):
    self.device_id = device_id

  def __repr__(self):
    return f'device {self.device_id} not find'

  __str__ = __repr__


class NoDeviceFound(AlbatrossException):
  pass


class DeviceNotRoot(AlbatrossException):
  def __init__(self, device):
    self.device = device


class DeviceReboot(AlbatrossException):
  pass


class PackageNotInstalled(AlbatrossException):
  def __init__(self, package):
    self.package = package

  def __repr__(self):
    return f'package {self.package} not install'

  __str__ = __repr__


class AttachFailed(AlbatrossException):
  """attach 系列(attach/attach_with_plugin_ids/attach_with_plugins/launch_fast)没有任何进程成功。

  只在调用方显式传 raise_on_fail=True 时抛出,默认行为仍是返回空列表(向后兼容)。
  failures 与日志里打印的汇总同源,每项形如
  {'pid': int|None, 'stage': 'process'|'inject_albatross'|'load_plugin'|'load_plugin_by_id'|'args',
   'result': 'INJECT_PROCESS_SLEEPING(-6)'|None, 'detail': str|None, 'hint': str|None}。
  """

  def __init__(self, action, target, failures=None):
    self.action = action
    self.target = target
    self.failures = list(failures or [])

  def describe(self):
    lines = [f'{self.action} {self.target}: 全部失败,没有任何进程/规则生效']
    for item in self.failures:
      line = f"  - pid={item.get('pid')} {item.get('stage')}"
      if item.get('result'):
        line += f" -> {item['result']}"
      if item.get('detail'):
        line += f" ({item['detail']})"
      if item.get('hint'):
        line += f"; {item['hint']}"
      lines.append(line)
    return '\n'.join(lines)

  def __repr__(self):
    return self.describe()

  __str__ = __repr__
