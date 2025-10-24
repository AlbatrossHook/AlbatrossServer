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
import re
import socket
import subprocess
import sys
import time

from .albatross_client import AlbatrossClient, DexLoadResult, InjectFlag, AlbatrossInitFlags, RunTimeISA, SetResult
from .common import Configuration, run_shell, lib_origin_name
from .exceptions import DeviceOffline, NoDeviceFound, DeviceNoFindErr, DeviceNotRoot, PackageNotInstalled
from .plugin import Plugin
from .rpc_client import byte
from .system_server_client import SystemServerClient
from .wrapper import cached_property


def check_socket_port(ip, port):
  try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = s.connect_ex((ip, port))
    if result == 0:
      return False
    return True
  except:
    return False


def get_valid_port():
  import socket

  temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  temp_sock.bind(("", 0))
  port = temp_sock.getsockname()[1]
  temp_sock.close()
  return port


adb_path = Configuration.adb


def get_devices():
  try:
    _, lines = run_shell(adb_path + " devices", split=True)
    if "Error" in lines:
      return []
    line_len = len(lines)
    if line_len > 1:
      devices = []
      for i in range(1, line_len):
        device = lines[i].strip().split()
        if len(device) == 2:
          if device[1] != "offline":
            devices.append(device[0])
          else:
            run_shell(adb_path + ' disconnect ' + device[0], timeout=4)
      return devices
    return []
  except:
    return []


def check_device_alive(device_name, try_time=3):
  for i in range(try_time):
    ret_code, bs = run_shell(f"{adb_path} -s {device_name} shell echo ping", timeout=2)
    if bs and bs.startswith(b'ping'):
      return True
    if i < try_time - 1:
      time.sleep(0.5)
  return False


if sys.platform.startswith('win'):
  import hashlib


  def file_md5(file_path):
    md5 = hashlib.md5()
    try:
      with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
          md5.update(chunk)
      return md5.hexdigest()
    except IOError as e:
      return None
else:

  def file_md5(file_path):
    ret, ret_bs = run_shell('md5sum ' + file_path)
    if ret == 0:
      return ret_bs.decode().split()[0]
    return None

pkg_pattern = re.compile(r"package:([\w.]+)(?:\s+|$)")


class AlbatrossDevice(object):
  anti_detection = True

  ret_code: int
  shell_user = 'shell'
  lib_dst: str
  lib_dir: str
  lib32_dir: str
  update_kill = True
  lib32_dst: str
  max_launch_count = 20
  reconnect = True

  def __init__(self, device_id):
    self.device_id = device_id
    self.cmd = adb_path + " -s " + device_id + " "
    self.shellcmd = self.cmd + "shell "
    self.process_launch_callback = {}
    self.app_launch_count = {}

  def shell(self, cmd, timeout=None) -> list | str:
    cmd = self.shellcmd + '"' + cmd + '"'
    if timeout:
      ret = run_shell(cmd, timeout=timeout)
    else:
      ret = run_shell(cmd)
    self.ret_code = ret[0]
    result = ret[1].decode().strip()
    return result

  root_shell = shell

  def device_alive(self, try_time=2):
    get_devices()
    for i in range(try_time):
      try:
        ret = self.shell('echo "ping"', timeout=2)
        if ret == 'ping':
          return True
      except:
        pass
      device_id = self.device_id
      if '.' in device_id:
        run_shell(adb_path + ' connect ' + device_id, timeout=2)
        time.sleep(1)
    return 'ping' == self.shell('echo "ping"', timeout=2)

  @property
  def is_screen_on(self):
    cmd = self.shellcmd + "dumpsys power"
    ret_str = run_shell(cmd)[1].decode("utf-8")
    if 'mWakefulness=' in ret_str:
      return 'mWakefulness=Awake' in ret_str
    match = re.search(r"Display Power: state=(\w+)", ret_str)
    return match.group(1) == 'ON'

  def wake_up(self):
    if not self.is_screen_on:
      run_shell(self.shellcmd + "input keyevent 26")

  def check_alive(self):
    if not self.device_alive(1):
      raise DeviceOffline(self.device_id)
    return True

  def adb_cmd(self, *args, **kwargs):
    cmd_line = [self.cmd] + list(args)
    cmd_line = " ".join(cmd_line)
    return run_shell(cmd_line, **kwargs)

  def forward_list(self):
    lines = (self.adb_cmd("forward", "--list")[1].decode("utf-8").strip().splitlines())
    return [line.strip().split() for line in lines]

  def forward(self, local, remote, tcp=True):
    if tcp:
      local = "tcp:%d" % local
    else:
      local = "udp:%d" % local
    ret_code, _ = self.adb_cmd("forward", local, remote)
    return ret_code

  def connect(self):
    run_shell(adb_path + ' connect ' + self.device_id, timeout=3)

  def is_online(self):
    devices = get_devices()
    return self.device_id in devices

  def is_adb_root(self):
    un_root = "Permission" in self.shell("rm /data/local/file_test")
    if un_root or "Permission" in self.shell("touch /data/local/file_test"):
      ret, rstr = self.adb_cmd("root")
      if b'cannot run as root in production builds' in rstr:
        return False
      i = 2
      while i > 0:
        if self.is_online():
          break
        time.sleep(1)
        i -= 1
        self.connect()
      else:
        return False
      ret = "Permission" not in self.shell("touch /data/local/file_test")
      return ret
    else:
      return "Permission" not in self.shell("rm /data/local/file_test")

  def su_shell(self, cmd, timeout=10):
    cmd = self.shellcmd + "'{} -c \"".format(self.su_file) + cmd + "\"'"
    ret = run_shell(cmd, timeout=timeout)
    self.ret_code = ret[0]
    result = ret[1].decode().strip()
    return result

  def is_shell_root(self):
    is_not_root = "Permission" in self.su_shell("touch /data/local/file_test")
    ret = "Permission" not in self.su_shell("rm /data/local/file_test")
    return ret

  @cached_property
  def su_file(self):
    su_file = self.shell('which su')
    if su_file:
      return su_file
    for i in ["/system/bin/su", "/system/xbin/su", "/sbin/su", "/system/su", "/system/bin/.ext/su",
      "/system/usr/we-need-root/su", "/data/local/xbin/su", "/data/local/bin/su", "/data/local/su"]:
      ret_code, _ = run_shell(self.shellcmd + 'ls ' + i)
      if ret_code == 0:
        return i
    return 'su'

  @cached_property
  def is_root(self):
    adb_root = self.is_adb_root()
    if adb_root:
      self.shell_user = 'root'
      self.root_shell = self.shell
      return True
    shell_root = self.is_shell_root()
    if shell_root:
      self.root_shell = self.su_shell
    return shell_root

  @cached_property
  def agent_dex(self):
    plugin_dir = Configuration.app_plugin_home
    dst = plugin_dir + Configuration.app_agent_name
    res = self.push_file(Configuration.app_agent_file, dst, mode='444', check=True)
    if res:
      self.create_dex_oat_dir(dst)
    return dst

  def get_file_md5(self, filepath):
    ret: str = self.shell('md5sum ' + filepath)
    if not ret or 'No such' in ret:
      return None
    if 'permission' in ret.lower():
      ret = self.root_shell('md5sum ' + filepath)
      if not ret or 'No such' in ret:
        return None
    return ret.split()[0].strip()

  def delete_file(self, file_path):
    self.root_shell('rm -rf {}'.format(file_path))
    return self.ret_code == 0

  def push_file(self, file, dst, check=False, mode=None, file_type=None, owner=None):
    if not os.path.exists(file):
      return False
    md5_dst = file_md5(file)
    extra_cmds = []
    if mode:
      extra_cmds.append(f'chmod {mode} {dst}')
    if file_type:
      extra_cmds.append(f'chcon u:object_r:{file_type}:s0 {dst}')
    if owner:
      extra_cmds.append(f'chown {owner}:{owner} {dst}')
    if not md5_dst:
      return False
    if check or os.stat(file).st_size > 8192:
      if dst[-1] == "/":
        dst += os.path.basename(file)
      md5_current = self.get_file_md5(dst)
      if md5_dst == md5_current:
        if extra_cmds:
          self.root_shell(';'.join(extra_cmds))
        return False
    if self.shell_user == 'shell':
      self.delete_file(dst)
    command = self.cmd + ' push "{}" "{}"'.format(file, dst)
    ret_code, s = run_shell(command)
    res = ret_code == 0
    if res:
      if extra_cmds:
        self.root_shell(';'.join(extra_cmds))
      print(s)
      return res
    if self.is_root and self.shell_user == 'shell':
      tmp_path = '/data/local/tmp/' + md5_dst
      command = self.cmd + ' push "{}" "{}"'.format(file, tmp_path)
      ret_code, s = run_shell(command)
      res = ret_code == 0
      if res:
        command = self.root_shell(f'mkdir -p {os.path.dirname(dst)} && mv {tmp_path} {dst}')
        if not command:
          print(s)
          if extra_cmds:
            self.root_shell(';'.join(extra_cmds))
          return True
    return False

  def pidofs(self, cmd_line):
    pids = []
    grep_cmd = f'grep "{cmd_line}"'
    ret: str = self.shell('ps -ef |' + grep_cmd)
    if ret:
      grep_exclude = 'grep ' + cmd_line
      lines = ret.split('\n')
      for line in lines:
        if grep_cmd in line:
          continue
        if grep_exclude in line:
          continue
        pids.append(line.split(maxsplit=2)[1])
    return pids

  def pidof(self, process_name):
    s = self.shell('pidof ' + process_name)
    return s.split()

  def kill_process(self, process):
    pids = self.pidof(process)
    if pids:
      for pid in pids:
        self.kill_pid(pid)
        print('kill', process, pid)

  def kill_pid(self, pid, sig=9):
    if pid:
      self.root_shell("kill -{} {}".format(sig, pid))

  def __on_close(self, client):
    cached_property.delete(self, 'client')
    print('albatross server disconnected')

  def setenforce(self, on=False):
    if on:
      self.root_shell("setenforce 1")
    else:
      self.root_shell("setenforce 0")

  def is_selinux_on(self):
    return self.shell('getenforce') == 'Enforcing'

  @cached_property
  def support_32(self):
    return not not self.pidof('zygote')

  @cached_property
  def file_type(self):
    if self.is_selinux_on():
      return 'albatross_file'
    return None

  def get_client(self) -> AlbatrossClient:
    if not self.is_root:
      raise DeviceNotRoot(self)
    server_dst_path = Configuration.server_dst_path
    server_dst_path = '/data/local/tmp/' + server_dst_path
    server_port = Configuration.server_port
    local_port = self.get_forward_port(server_port)
    device_abi = self.cpu_abi
    server_file, abi_lib, abi_lib32 = Configuration.get_server_path(device_abi)
    assert os.path.exists(server_file)
    update = self.push_file(server_file, server_dst_path, check=True, mode='500', owner='root')
    lib_dir = Configuration.lib_path + self.abi_lib_name + '/'
    server_lib_dst = lib_dir + lib_origin_name
    update += self.push_file(abi_lib, server_lib_dst, file_type=self.file_type)
    self.lib_dir = lib_dir
    lib_name = Configuration.lib_name
    app_lib_dst = lib_dir + lib_name
    self.lib_dst = app_lib_dst
    if app_lib_dst != server_lib_dst:
      self.push_file(abi_lib, app_lib_dst, mode='644', file_type=self.file_type)
    lib_dst_32 = None
    lib_src_32 = None
    if abi_lib32 and self.support_32:
      lib_src_32, abi32_name = abi_lib32
      self.lib32_dir = Configuration.lib_path + abi32_name + "/"
      lib_dst_32 = self.lib32_dir + lib_name
      self.push_file(lib_src_32, lib_dst_32, mode='644', file_type=self.file_type)
      self.lib32_dst = lib_dst_32
    if update and self.update_kill:
      self.kill_process(os.path.basename(server_dst_path))
    else:
      try:
        client = AlbatrossClient('127.0.0.1', local_port, 'albatross-' + self.device_id, 500)
        client.set_arch_lib(self.lib_dst)
        if lib_dst_32:
          client.set_2nd_arch_lib(self.lib32_dst)
        return client
      except:
        self.kill_process(os.path.basename(server_dst_path))
    if type(server_port) == str and server_port.startswith('localabstract:'):
      server_port = server_port.split(':')[1]
    if self.shell_user == 'shell':
      cmd_prefix = "nohup su -c "
      cmd = f'{self.shellcmd} \'LD_LIBRARY_PATH={lib_dir} {cmd_prefix} "{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"\''
    else:
      cmd_prefix = "nohup "
      cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dir} {cmd_prefix} {server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"'
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    time.sleep(2)
    process.terminate()
    client = AlbatrossClient('127.0.0.1', local_port, 'albatross-' + self.device_id, 500)
    client.set_arch_lib(self.lib_dst)
    if lib_dst_32:
      client.set_2nd_arch_lib(self.lib32_dst)
    if self.is_selinux_on():
      client.patch_selinux()
    return client

  def restart_system_server(self):
    self.root_shell('stop')
    time.sleep(0.5)
    self.root_shell('start')
    time.sleep(1)

  def on_system_subscribe_close(self, client):
    if self.reconnect:
      print('system_server subscriber close')
      try:
        if client.reconnect():
          client.subscribe()
          return
      except:
        pass
    cached_property.delete(self, "system_server_subscriber")

  def on_system_client_close(self, client):
    if self.reconnect:
      print('system_server client close')
      if not client.reconnect():
        cached_property.delete(self, "system_server_client")

  system_server_address = None

  @cached_property
  def system_server_subscriber(self) -> SystemServerClient:
    port = self.get_forward_port(self.system_server_address)
    subscribe_client = SystemServerClient('127.0.0.1', port, 'system-' + self.device_id)
    subscribe_client.set_on_close_listener(self.on_system_subscribe_close)
    subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
    subscribe_client.subscribe()
    return subscribe_client

  system_client_class_impl = SystemServerClient

  @cached_property
  def system_server_client(self) -> SystemServerClient:
    client = self.client
    system_client_class = self.system_client_class_impl
    agent_dst = Configuration.system_server_agent_dst
    if not self.is_selinux_on():
      client.patch_selinux()
    update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
    if update:
      self.create_dex_oat_dir(agent_dst)
      server_pid = client.get_process_pid('system_server')
      if server_pid > 0 and client.is_injected(server_pid):
        self.restart_system_server()
        time.sleep(20)
    server_pid = client.get_process_pid('system_server')
    if server_pid <= 0:
      self.restart_system_server()
      time.sleep(15)
      server_pid = client.get_process_pid('system_server')
    if server_pid <= 0:
      return cached_property.nil_value
    res = client.inject_albatross(server_pid, system_client_class.inject_flags, '')
    if res < 0:
      return cached_property.nil_value
    # unix_address = Configuration.system_server_listen_address
    res = client.load_dex(server_pid, agent_dst, None, Configuration.albatross_class_name,
      Configuration.system_server_init_class, Configuration.albatross_register_func,
      system_client_class.albatross_init_flags, None, 0, timeout=30)
    if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
      system_server_address = client.get_address(server_pid)
      system_server_address = 'localabstract:' + system_server_address
      self.system_server_address = system_server_address
      port = self.get_forward_port(system_server_address)
      system_server = system_client_class('127.0.0.1', port, 'system-' + self.device_id)
      system_server.init()
      system_server.set_on_close_listener(self.on_system_client_close)
      subscribe_client = system_client_class('127.0.0.1', port, 'system-' + self.device_id)
      subscribe_client.set_on_close_listener(self.on_system_subscribe_close)
      subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
      subscribe_client.subscribe()
      system_server.set_intercept_app(None)
      cached_property.reset(self, 'system_server_subscriber', subscribe_client)
      return system_server
    return cached_property.nil_value

  @cached_property
  def client(self):
    client = self.get_client()
    client.set_on_close_listener(self.__on_close)
    return client

  def clear_plugins(self):
    assert self.init_plugin_env
    return self.client.clear_plugins()

  @cached_property
  def is_64(self):
    return '64' in self.cpu_abi

  @cached_property
  def abi_lib_name(self):
    return Configuration.abi_lib_names[self.cpu_abi]

  @cached_property
  def cpu_abi(self):
    cpu_abi = self.shell('getprop ro.product.cpu.abi')
    if cpu_abi:
      return cpu_abi
    file_type = self.shell('file /system/bin/sh')
    if 'arm64' in file_type:
      return 'arm64-v8a'
    if 'arm' in file_type:
      return 'armeabi-v7a'
    if 'x86' in file_type:
      if '64' in file_type:
        return 'x86_64'
    else:
      return 'x86'
    return None

  app_inject_flags = InjectFlag.KEEP | InjectFlag.UNIX
  app_albatross_init_flags = AlbatrossInitFlags.FLAG_INJECT | AlbatrossInitFlags.FLAG_CALL_CHAIN | AlbatrossInitFlags.FLAG_LOG

  def on_launch_process(self, uid: int, pid: int, process_info: dict) -> byte:
    print(f'launch process {uid}:{pid}', process_info)
    inject_record = self.process_launch_callback.get(uid)
    if inject_record:
      count = self.app_launch_count[uid]
      self.app_launch_count[uid] = count + 1
      if count < self.max_launch_count:
        plugin_dex, plugin_lib, plugin_class, arg_str, arg_int = inject_record
        self.attach(pid, plugin_dex, plugin_class, plugin_lib, arg_str, arg_int, self.app_albatross_init_flags)
      else:
        return 0
    return 1

  def launch(self, target_package, plugin_dex, plugin_class, plugin_lib=None, plugin_params: str = None,
      plugin_flags: int = 0):
    if not self.is_app_install(target_package):
      raise PackageNotInstalled(target_package)
    launch_callback = self.process_launch_callback
    clear_history_launch = Configuration.clear_history_launch
    if clear_history_launch:
      launch_callback.clear()
    server_client = self.system_server_client
    assert server_client.init_intercept() != 0
    server_client.force_stop_app(target_package)
    app_id = server_client.set_intercept_app(target_package, clear_history_launch)
    assert self.system_server_subscriber
    launch_callback[app_id] = (plugin_dex, plugin_lib, plugin_class, plugin_params, plugin_flags)
    self.app_launch_count[app_id] = 0
    server_client.start_activity(target_package, None, 0)

  def create_dex_oat_dir(self, dex_path):
    dex_dir = os.path.dirname(dex_path)
    oat_dir = dex_dir + '/oat/' + self.abi_lib_name
    self.root_shell('mkdir -p ' + oat_dir + " && chmod 777 " + oat_dir)

  @cached_property
  def init_plugin_env(self):
    try:
      client = self.client
      agent_dst = Configuration.system_server_agent_dst
      update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
      if update:
        self.create_dex_oat_dir(agent_dst)
        server_pid = client.get_process_pid('system_server')
        if server_pid > 0 and client.is_injected(server_pid):
          self.restart_system_server()
          time.sleep(20)
      client.set_system_server_agent(agent_dst, Configuration.system_server_init_class, "system_server",
        AlbatrossInitFlags.NONE, None, 3)
      client.set_app_agent(self.agent_dex, None, Configuration.albatross_class_name,
        Configuration.albatross_agent_class, Configuration.albatross_register_func,
        AlbatrossInitFlags.FLAG_CALL_CHAIN | AlbatrossInitFlags.FLAG_LOG)
      if not client.patch_selinux():
        self.setenforce(False)
      return True
    except Exception as e:
      print('init plugin env fail:' + str(e))
      return cached_property.nil_value

  def launch_fast(self, target_package, plugin_dex, plugin_class, plugin_params: str = None,
      plugin_flags: int = 0, plugin_lib=None):
    uid = self.get_package_uid(target_package)
    if not uid:
      return False
    if not self.init_plugin_env:
      return False
    client = self.client
    plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
    self.push_file(plugin_dex, plugin_dex_device, mode='444')
    plugin = Plugin.create(plugin_dex, plugin_class, plugin_lib, plugin_params, plugin_flags)
    client.register_plugin(plugin.plugin_id, plugin_dex_device, plugin_lib, plugin_class, plugin_params, plugin_flags)
    client.add_plugin_rule(plugin.plugin_id, uid)
    self.stop_app(target_package)
    self.start_app(target_package)
    return True

  def launch_with_plugins(self, target_package, plugins):
    uid = self.get_package_uid(target_package)
    if not uid:
      return False
    client = self.client
    for plugin in plugins:
      res = client.add_plugin_rule(plugin.plugin_id, uid)
      if res not in [SetResult.SET_OK, SetResult.SET_ALREADY]:
        return False
    self.start_app(target_package)
    return True

  def attach_with_plugins(self, package_or_pid, plugins, init_flags=AlbatrossInitFlags.FLAG_LOG):
    client = self.client
    if isinstance(package_or_pid, str):
      pids = client.get_java_processes_by_uid(self.get_package_uid(package_or_pid))
    else:
      pids = [package_or_pid]
    success = []
    if pids and plugins:
      agent_dex = self.agent_dex
      for pid in pids:
        res = client.inject_albatross(pid, self.app_inject_flags, None)
        if res >= 0:
          for plugin in plugins:
            res = client.load_plugin(pid, agent_dex, None, Configuration.albatross_class_name,
              Configuration.albatross_agent_class, Configuration.albatross_register_func,
              init_flags, plugin.dex_device_dst, plugin.plugin_lib, plugin.plugin_class, plugin.plugin_params,
              plugin.plugin_flags)
            if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
              success.append((pid, plugin))
    return success

  def attach_with_plugin_ids(self, package_or_pid, plugins):
    assert self.init_plugin_env
    client = self.client
    if isinstance(package_or_pid, str):
      pids = client.get_java_processes_by_uid(self.get_package_uid(package_or_pid))
    else:
      pids = [package_or_pid]
    success = []
    for pid in pids:
      res = client.inject_albatross(pid, self.app_inject_flags, None)
      if res >= 0:
        for plugin in plugins:
          res = client.load_plugin_by_id(pid, plugin.plugin_id)
          if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
            success.append((pid, plugin))
    return success

  def register_plugin(self, plugin_dex, plugin_class, plugin_params: str = None,
      plugin_flags: int = 0, plugin_lib=None):
    assert os.path.exists(plugin_dex)
    client = self.client
    plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
    self.push_file(plugin_dex, plugin_dex_device, mode='444')
    plugin = Plugin.create(plugin_dex, plugin_class, plugin_lib, plugin_params, plugin_flags)
    client.register_plugin(plugin.plugin_id, plugin_dex_device, plugin_lib, plugin_class, plugin_params, plugin_flags)
    plugin.dex_device_dst = plugin_dex_device
    return plugin

  def reload_plugin(self, plugin: Plugin):
    assert self.init_plugin_env
    if not plugin.dex_device_dst:
      plugin_dex = plugin.plugin_dex
      plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
      self.push_file(plugin_dex, plugin_dex_device, mode='444')
      plugin.dex_device_dst = plugin_dex_device
    self.client.register_plugin(plugin.plugin_id, plugin.dex_device_dst, None, plugin.plugin_class,
      plugin.plugin_params, plugin.plugin_flags)

  def remove_plugin(self, plugin: Plugin):
    self.client.delete_plugin(plugin.plugin_id)

  def load_system_plugin(self, plugin_dex, plugin_class, plugin_params: str = None, plugin_flags: int = 0,
      plugin_lib: str | None = None):
    assert os.path.exists(plugin_dex)
    assert self.init_plugin_env
    client = self.client
    plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
    self.push_file(plugin_dex, plugin_dex_device, mode='444')
    if plugin_lib:
      assert os.path.exists(plugin_lib)
      pid = client.get_process_pid('system_server')
      if client.get_process_isa(pid) in [RunTimeISA.ISA_X86_64, RunTimeISA.ISA_ARM64]:
        lib_dst_device = self.lib_dir + os.path.basename(plugin_lib)
      else:
        lib_dst_device = self.lib32_dir + os.path.basename(plugin_lib)
      self.push_file(plugin_lib, lib_dst_device)
      plugin_lib = lib_dst_device
    res = client.load_system_plugin(plugin_dex_device, plugin_lib, plugin_class, plugin_params, plugin_flags)
    return res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]

  def add_plugin_rule(self, plugin: Plugin, target_package):
    assert self.init_plugin_env
    uid = self.get_package_uid(target_package)
    client = self.client
    client.add_plugin_rule(plugin.plugin_id, uid)

  def attach(self, package_or_pid, plugin_dex, plugin_class, plugin_lib=None, plugin_params: str = None,
      plugin_flags: int = 0, init_flags=AlbatrossInitFlags.NONE):
    client = self.client
    if isinstance(package_or_pid, str):
      pids = client.get_java_processes_by_uid(self.get_package_uid(package_or_pid))
    else:
      pids = [package_or_pid]
    success = []
    if pids:
      assert os.path.exists(plugin_dex)
      plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
      self.push_file(plugin_dex, plugin_dex_device, mode='444')
      for pid in pids:
        # pid_int = int(pid)
        res = client.inject_albatross(pid, self.app_inject_flags, None)
        if res >= 0:
          if plugin_lib:
            assert os.path.exists(plugin_lib)
            if client.get_process_isa(pid) in [RunTimeISA.ISA_X86_64, RunTimeISA.ISA_ARM64]:
              lib_dst_device = self.lib_dir + os.path.basename(plugin_lib)
            else:
              lib_dst_device = self.lib32_dir + os.path.basename(plugin_lib)
            self.push_file(plugin_lib, lib_dst_device)
          else:
            lib_dst_device = None
          agent_dex = self.agent_dex
          time.sleep(1)
          res = client.load_plugin(pid, agent_dex, None, Configuration.albatross_class_name,
            Configuration.albatross_agent_class, Configuration.albatross_register_func,
            init_flags, plugin_dex_device, lib_dst_device, plugin_class, plugin_params,
            plugin_flags)
          if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
            success.append(pid)
    return success

  def get_forward_port(self, remote_port, not_check=True):
    if isinstance(remote_port, int):
      remote_port = 'tcp:' + str(remote_port)
    for s, lp, rp in self.forward_list():
      if rp == remote_port and s == self.device_id:
        local_port = int(lp[4:])
        if not_check or check_socket_port("127.0.0.1", local_port):
          break
    else:
      local_port = get_valid_port()
      self.forward(local_port, remote_port)
    return local_port

  def remove_albatross_port(self):
    for s, lp, rp in self.forward_list():
      if re.findall('localabstract:albatross_\\d+', rp):
        run_shell(self.cmd + 'forward --remove ' + lp)

  def remove_forward_port(self, port):
    if isinstance(port, int):
      port = 'tcp:' + str(port)
    run_shell(self.cmd + 'forward --remove ' + port)

  def get_app_main_activities(self, pkg):
    cmd = self.shellcmd + " dumpsys package " + pkg
    _, ret_bs = run_shell(cmd)
    ret_str = ret_bs.decode("utf-8")
    res = ret_str.split("android.intent.action.MAIN:")
    if len(res) > 1:
      str_list = (re.match("(\\s+[\\da-f]+\\s+[\\w/.]+)+", res[1]).group(0).strip().split())
      activities = [val for idx, val in enumerate(str_list) if idx & 1]
      return activities
    return []

  def start_activity(self, pkg_activity, action=None):
    command = self.cmd + "shell am start -n {}".format(pkg_activity)
    if action:
      command += ' -a ' + action
    # command = self.cmd + 'shell am start -n {}/{}'.format(pkg_name, activity)
    ret_code, ret_str = run_shell(command, timeout=None)
    if ret_code == 0 and b"Error" not in ret_str:
      return True
    else:
      return False

  def stop_app(self, target_package):
    command = self.shellcmd + "am force-stop " + target_package
    ret_code, _ = run_shell(command)
    if ret_code == 0:
      return True
    return False

  def start_app(self, target_package):
    activities = self.get_app_main_activities(target_package)
    if activities:
      for activity in activities:
        if self.start_activity(activity):
          return True
    else:
      return False

  def is_app_install(self, pkg):
    return pkg in self.get_user_packages(include_disabled=True)

  def get_user_packages(self, include_disabled=False):
    if include_disabled:
      pkgs = self.shell('pm list packages -3')
    else:
      pkgs = self.shell('pm list packages -3 -e')
    return pkg_pattern.findall(pkgs)

  def home(self):
    cmd = self.shellcmd + "input keyevent 3"
    run_shell(cmd)

  def switch_app(self):
    cmd = self.shellcmd + 'input keyevent KEYCODE_APP_SWITCH'
    run_shell(cmd)

  @cached_property
  def sdk_version(self):
    try:
      sdk = int(run_shell(self.shellcmd + "getprop ro.build.version.sdk")[1].decode().strip())
      return sdk
    except:
      return None

  def pull_file(self, src_android, dst_pc, is_del=False):
    command = self.cmd + ' pull "{}" "{}"'.format(src_android, dst_pc)
    ret_code, res = run_shell(command)
    if ret_code != 0:
      if 'Permission denied' in str(res) and self.is_root:
        self.shell('mkdir -p /data/local/tmp/pull')
        dst_mv = '/data/local/tmp/pull/' + os.path.basename(src_android)
        # if src_android[-1] == '/':
        #   dst_mv = '/data/local/tmp/pull/' + os.path.basename(src_android)
        # else:
        #   dst_mv = '/data/local/tmp/pull'
        self.root_shell('cp -r {} {}'.format(src_android, dst_mv))
        self.root_shell('chown -R shell:shell ' + dst_mv)
        # if src_android[-1] != '/':
        #   command = self.cmd + ' pull "{}" "{}"'.format(dst_mv + '/' + os.path.basename(src_android), dst_pc)
        # else:
        command = self.cmd + ' pull "{}" "{}"'.format(dst_mv, dst_pc)
        ret_code, res = run_shell(command)
        self.root_shell('rm -rf {}'.format(dst_mv))
        if is_del:
          self.root_shell('rm -rf {}'.format(src_android))
        return ret_code == 0
      return False
    if not is_del:
      return True
    del_command = self.shellcmd + " rm -rf " + src_android
    ret_code, _ = run_shell(del_command)
    if ret_code == 0:
      return True
    else:
      return False

  def screenshot(self, path):
    command = self.shellcmd + "screencap -p  /sdcard/screen.png"
    ret_code, _ = run_shell(command)
    if ret_code != 0:
      return False
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
      os.makedirs(dirpath)
    return self.pull_file("/sdcard/screen.png", path)

  def get_package_uid(self, pkg):
    cmd = self.shellcmd + 'dumpsys package ' + pkg
    ret_str = run_shell(cmd)[1].decode("utf-8")
    res = re.findall(r'\s+(?:appId|uid|userId)=(\d+)', ret_str)
    if res:
      return int(res[0])
    return None

  def __repr__(self):
    return "Device: {}".format(self.device_id)

  def get_processes_by_uid(self, target_uid: int, save_name=False):
    output = self.shell("ps -A -o USER,UID,PID,NAME")
    if not output:
      return []
    processes = []
    uid_str = str(target_uid)
    for line in output.splitlines():
      if not line.strip():
        continue
      match = re.match(r'^\s*(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s*$', line)
      if match:
        user, uid, pid, name = match.groups()
        if uid == uid_str:
          if save_name:
            processes.append({'pid': int(pid), 'name': name})
          else:
            processes.append(pid)
    return processes

  def watch_plugin(_self, target_pkg: str, plugin: Plugin, change_restart=False, attach=False):
    from watchdog.events import FileSystemEventHandler
    target_uid = _self.get_package_uid(target_pkg)
    _self.reload_plugin(plugin)

    plugin_dex = plugin.plugin_dex
    if not attach:
      _self.add_plugin_rule(plugin, target_pkg)

    class FileChangeHandler(FileSystemEventHandler):

      def __init__(self):
        self.debounce_delay = 0.5  # 防抖延迟（秒）
        self.plugin_md5 = file_md5(plugin_dex)
        self.last_processed = 0

      def handle_plugin_change(self):
        try:
          new_md5 = file_md5(plugin_dex)
          if new_md5 == self.plugin_md5:
            return
          current_time = time.time()
          # 防抖处理
          if current_time - self.last_processed < self.debounce_delay:
            return
          self.last_processed = current_time
          self.plugin_md5 = new_md5
          _self.push_file(plugin_dex, plugin.dex_device_dst, mode='444', check=True)
          if change_restart:
            _self.stop_app(target_pkg)
            _self.start_app(target_pkg)
            if attach:
              time.sleep(10)
              pids = _self.client.get_java_processes_by_uid(target_uid)
              _self.attach_with_plugin_ids(pids, [plugin])
          else:
            pids = _self.client.get_java_processes_by_uid(target_uid)
            if not pids:
              _self.start_app(target_pkg)
              time.sleep(10)
              pids = _self.client.get_java_processes_by_uid(target_uid)
              for pid in pids:
                _self.client.load_plugin_by_id(pid, plugin.plugin_id)
            else:
              for pid in pids:
                _self.client.unload_plugin_dex(pid, plugin.plugin_id)
                _self.client.load_plugin_by_id(pid, plugin.plugin_id)

        except Exception as e:
          print(f"\n更新插件失败: {str(e)}", file=sys.stderr)

      def on_modified(self, event):
        """处理文件修改事件"""
        if not event.is_directory and event.src_path == os.path.abspath(plugin_dex):
          self.handle_plugin_change()

      def on_created(self, event):
        """处理文件创建事件（针对文件被删除后重新创建的情况）"""
        if not event.is_directory and event.src_path == os.path.abspath(plugin_dex):
          print("检测到版本文件重新创建")
          self.handle_plugin_change()

    event_handler = FileChangeHandler()
    from watchdog.observers import Observer
    observer = Observer()
    observer.schedule(event_handler, plugin_dex, recursive=False)
    observer.start()
    print(f"开始监控插件: {Observer} ")
    print("按Ctrl+C停止监控")
    try:
      while True:
        time.sleep(5)
    except KeyboardInterrupt:
      observer.stop()
      print("\n监控已停止")
    observer.join()


class DeviceManager:

  def __init__(self):
    self.devices = {}

  def get_devices(self, device_id) -> AlbatrossDevice:
    if device_id and ":" in device_id:
      if device_id not in run_shell(adb_path + " devices")[1].decode():
        if "." in device_id or "localhost" in device_id:
          run_shell(adb_path + " connect " + device_id, timeout=5)
        else:
          port = device_id.split(":")[1]
          run_shell(adb_path + " connect 127.0.0.1:" + port, timeout=5)
    devices = get_devices()
    if not devices:
      raise NoDeviceFound()
    if device_id:
      if device_id not in devices:
        raise DeviceNoFindErr(device_id)
    else:
      device_id = devices[0]
      if len(devices) > 1:
        print("more than one device,default choose device " + device_id)
    device_tables = self.devices
    if device_id in device_tables:
      device = device_tables[device_id]
      if device.check_alive():
        return device
    if not check_device_alive(device_id):
      raise DeviceOffline(device_id)
    device = AlbatrossDevice(device_id)
    device_tables[device_id] = device
    return device


_device_manager: DeviceManager | None = None


def get_device_manager() -> "DeviceManager":
  global _device_manager
  if _device_manager is None:
    _device_manager = DeviceManager()
  return _device_manager


def destroy_device():
  global _device_manager
  if _device_manager is not None:
    devices = _device_manager.devices
    for device_id, device in devices.items():
      device: AlbatrossDevice
      device.reconnect = False
      system_server_subscriber = cached_property.pop(device, 'system_server_subscriber')
      if system_server_subscriber != cached_property.nil_value:
        system_server_subscriber.close()
      system_server_client = cached_property.pop(device, 'system_server_client')
      if system_server_client is not cached_property.nil_value:
        system_server_client.close()
        device.remove_forward_port(system_server_client.port)
      client = cached_property.pop(device, 'client')
      if client is not cached_property.nil_value:
        client.close()
        device.remove_forward_port(client.port)
    devices.clear()

    _device_manager = None
