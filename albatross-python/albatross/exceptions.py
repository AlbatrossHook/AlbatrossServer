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
