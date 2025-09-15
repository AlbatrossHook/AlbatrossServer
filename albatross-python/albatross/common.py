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

import os

import toml

from .wrapper import cached_class_property

import re
import subprocess

OUT_TIME_CODE = 996
FAULT_CODE = 997


def run_shell(cmd, timeout=20, split=False):
  try:
    cmdshell = subprocess.Popen(
      cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )
    stdout, stderr = cmdshell.communicate(timeout=timeout)
    if stdout and stderr:
      lines = b"\nError:\n".join([stdout, stderr])
    elif stderr:
      lines = b"Error:\n" + stderr
    else:
      lines = stdout
    if split:
      return cmdshell.returncode, re.split("[\r\n]+", lines.decode("utf-8").strip())
    return cmdshell.returncode, lines
  except subprocess.TimeoutExpired as e:
    return OUT_TIME_CODE, b""
  except Exception as e:
    return FAULT_CODE, str(e).encode()


class Configuration(object):

  @cached_class_property
  def config(self):
    current_dir = os.path.dirname(__file__)
    local_config = current_dir + '/albatross_config_local.toml'
    if os.path.exists(local_config):
      with open(local_config) as fp:
        return toml.load(fp)
    with open(current_dir + '/albatross_config.toml') as fp:
      return toml.load(fp)

  @staticmethod
  def __make_get(name, default_value):
    def func(self):
      return self.config.get(name, default_value)

    func.__name__ = name
    return cached_class_property(func)

  lib_name = __make_get('lib_name', 'libalbatross_base.so')

  @cached_class_property
  def adb(self):
    path = self.config.get('adb_path', 'adb')
    if path[0] != '/':
      _, adb_path = run_shell('which ' + path)
      if adb_path:
        return path
    if not os.path.exists(path):
      sdk_root = os.environ.get('ANDROID_SDK_ROOT')
      if sdk_root:
        path = os.path.join(sdk_root, 'platform-tools/adb')
    if os.path.exists(path):
      return path
    return cached_class_property.nil_value

  @cached_class_property
  def resource_dir(self):
    res = self.config.get('resource_dir')
    if res:
      if os.path.exists(res):
        return res
      print('resource_dir {} is configured but does not exist'.format(res))
    res = os.path.abspath(os.path.dirname(os.path.relpath(__file__)) + '/../../resource') + '/'
    assert os.path.exists(res)
    return res

  @cached_class_property
  def jni_libs(self):
    jni_libs = self.config.get('jni_libs')
    if jni_libs and os.path.exists(jni_libs):
      if jni_libs[-1] != '/':
        jni_libs += '/'
      return jni_libs
    jni_libs = self.resource_dir + 'jniLibs/'
    return jni_libs

  @cached_class_property
  def agent_dir(self):
    agent_dir = self.config.get('agent_dir')
    if agent_dir and os.path.exists(agent_dir):
      if agent_dir[-1] != '/':
        agent_dir += '/'
      return agent_dir
    return self.resource_dir + 'agent/'

  @cached_class_property
  def system_server_agent_file(self):
    res = self.config.get('system_server_agent_file')
    if res:
      return res
    return self.agent_dir + "system_server.dex"

  @cached_class_property
  def app_agent_file(self):
    res = self.config.get('app_agent_file')
    if res:
      if os.path.exists(res):
        return res
      print('app_agent_file {} is configured but does not exist'.format(res))
    return self.agent_dir + "app_agent.dex"

  albatross_class_name = __make_get('albatross_class_name', "qing/albatross/core/Albatross")

  clear_history_launch = __make_get('clear_history_launch', True)

  albatross_agent_class = __make_get('albatross_agent_class', "qing/albatross/app/agent/AlbatrossInjectEntry")

  albatross_register_func = __make_get('albatross_register_func', "albatross_load_init")

  system_server_agent_dst = __make_get('system_server_agent_dst', '/data/dalvik-cache/albatross_server.dex')

  app_agent_dst = __make_get('app_agent_dst', '/data/dalvik-cache/app_agent.dex')

  app_injector_dir = __make_get('app_injector_dir', '/data/dalvik-cache/')

  support_abi_list = __make_get('support_abi_list', ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86'])

  @cached_class_property
  def abi_lib_names(self):
    return {'arm64-v8a': 'arm64', 'armeabi-v7a': 'arm', 'x86_64': 'x86_64', 'x86': 'x86'}

  @cached_class_property
  def server_path_map(self):
    maps = {}
    jni_libs = self.jni_libs
    lib_name = self.lib_name
    for arch in self.support_abi_list:
      arch_dir = jni_libs + arch + '/'
      if '64' in arch:
        maps[arch] = (arch_dir + 'albatross_server', arch_dir + lib_name,
        (jni_libs + f'armeabi-v7a/{lib_name}', 'arm') if 'arm64' in arch else (
          jni_libs + f'x86/{lib_name}', 'x86'))
      else:
        maps[arch] = (arch_dir + 'albatross_server', arch_dir + lib_name, None)
    return maps

  @classmethod
  def get_server_path(cls, arch):
    return cls.server_path_map[arch]

  server_dst_path = __make_get('server_dst_path', 'albatross_server')

  lib_path = __make_get('lib_path', '/data/dalvik-cache/')

  server_port = __make_get('server_port', 19088)

  system_server_address = __make_get('system_server_address', 'localabstract:albatross_system_server')

  @cached_class_property
  def system_server_listen_address(self):
    address = self.system_server_address
    assert address.startswith('localabstract:')
    return address.split(':')[1]

  system_server_init_class = __make_get('system_server_init_class',
    "qing/albatross/android/system_server/SystemServerInjectEntry")
