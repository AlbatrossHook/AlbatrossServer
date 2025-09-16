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

from .albatross_client import AlbatrossClient, DexLoadResult, InjectFlag, AlbatrossInitFlags, RunTimeISA
from .common import Configuration, run_shell
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
    cmd = self.shellcmd + "' {} -c ".format(self.su_file) + cmd + "'"
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
    for i in ['/sbin/su']:
      ret = self.shell('ls ' + i)
      if self.ret_code == 0:
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
    injector_dir = Configuration.app_injector_dir
    dst = injector_dir + "app_agent.dex"
    res = self.push_file(Configuration.app_agent_file, dst, mode='444')
    if res:
      oat_dir = injector_dir + 'oat/' + self.abi_lib_name
      self.root_shell('mkdir -p ' + oat_dir)
    return dst

  def get_file_md5(self, filepath):
    ret: str = self.shell('md5sum ' + filepath)
    if 'No such' in ret or not ret:
      return None
    return ret.split()[0].strip()

  def delete_file(self, file_path):
    self.root_shell('rm -rf {}'.format(file_path))
    return self.ret_code == 0

  def push_file(self, file, dst, check=False, mode=None, file_type=None):
    if not os.path.exists(file):
      return False
    md5_dst = file_md5(file)
    if not md5_dst:
      return False
    if check or os.stat(file).st_size > 8192:
      if dst[-1] == "/":
        dst += os.path.basename(file)
      md5_src = self.get_file_md5(dst)
      if md5_dst == md5_src:
        if file_type:
          self.root_shell(f'chcon u:object_r:{file_type}:s0 {dst}')
        return False
    if self.shell_user == 'shell':
      self.delete_file(dst)
    command = self.cmd + ' push "{}" "{}"'.format(file, dst)
    ret_code, s = run_shell(command)
    res = ret_code == 0
    if res:
      if mode:
        self.shell('chmod {} {}'.format(mode, dst))
      if file_type:
        self.root_shell(f'chcon u:object_r:{file_type}:s0 {dst}')
      print(s)
      return res
    if self.is_root and self.shell_user == 'shell':
      tmp_path = '/data/local/tmp/' + md5_dst
      command = self.cmd + ' push "{}" "{}"'.format(file, tmp_path)
      ret_code, s = run_shell(command)
      res = ret_code == 0
      if res:
        command = self.root_shell('mv {} {}'.format(tmp_path, dst))
        if not command:
          print(s)
          if mode:
            self.root_shell('chmod {} {}'.format(mode, dst))
          if file_type:
            self.root_shell(f'chcon u:object_r:{file_type}:s0 {dst}')
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
    update = self.push_file(server_file, server_dst_path, mode='544')
    lib_dst = Configuration.lib_path + self.abi_lib_name + '/'
    update += self.push_file(abi_lib, lib_dst)
    self.lib_dir = lib_dst
    self.lib_dst = lib_dst + Configuration.lib_name
    lib_dst_32 = None
    if abi_lib32 and self.support_32:
      lib_src_32, abi32_name = abi_lib32
      self.lib32_dir = Configuration.lib_path + abi32_name + "/"
      lib_dst_32 = self.lib32_dir + Configuration.lib_name
      self.push_file(lib_src_32, lib_dst_32)
      self.lib32_dst = lib_dst_32
    if update and self.update_kill:
      self.kill_process(os.path.basename(server_dst_path))
    else:
      try:
        client = AlbatrossClient('127.0.0.1', local_port, 'albatross-' + self.device_id, 500)
        client.set_arch_lib(self.lib_dst)
        if lib_dst_32:
          client.set_2nd_arch_lib(lib_dst_32)
        return client
      except:
        self.kill_process(os.path.basename(server_dst_path))
    if self.shell_user == 'shell':
      cmd_prefix = "nohup su -c "
    else:
      cmd_prefix = "nohup "
    cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dst} {cmd_prefix} {server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"'
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    time.sleep(2)
    process.terminate()
    client = AlbatrossClient('127.0.0.1', local_port, 'albatross-' + self.device_id, 500)
    if lib_dst_32:
      client.set_2nd_arch_lib(lib_dst_32)
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

  @cached_property
  def system_server_subscriber(self) -> SystemServerClient:
    port = self.get_forward_port(Configuration.system_server_address)
    subscribe_client = SystemServerClient('127.0.0.1', port, 'system-' + self.device_id)
    subscribe_client.set_on_close_listener(self.on_system_subscribe_close)
    subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
    subscribe_client.subscribe()
    return subscribe_client

  @cached_property
  def system_server_client(self) -> SystemServerClient:
    client = self.client
    agent_dst = Configuration.system_server_agent_dst
    if not self.is_selinux_on():
      client.patch_selinux()
    update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
    if update:
      agent_dir = os.path.dirname(agent_dst)
      oat_dir = agent_dir + '/oat/' + self.abi_lib_name
      self.root_shell('mkdir -p ' + oat_dir)
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
    res = client.inject_albatross(server_pid, SystemServerClient.inject_flags, '')
    if res < 0:
      return cached_property.nil_value
    unix_address = Configuration.system_server_listen_address
    res = client.load_dex(server_pid, agent_dst, None, Configuration.albatross_class_name,
      Configuration.system_server_init_class, Configuration.albatross_register_func,
      SystemServerClient.albatross_init_flags, unix_address, 0, timeout=30)
    if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
      port = self.get_forward_port(Configuration.system_server_address)
      system_server = SystemServerClient('127.0.0.1', port, 'system-' + self.device_id)
      system_server.init()
      system_server.set_on_close_listener(self.on_system_client_close)
      subscribe_client = SystemServerClient('127.0.0.1', port, 'system-' + self.device_id)
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

  def on_launch_process(self, uid: int, pid: int, process_info: dict) -> byte:
    print(f'launch process {uid}:{pid}', process_info)
    inject_record = self.process_launch_callback.get(uid)
    if inject_record:
      count = self.app_launch_count[uid]
      self.app_launch_count[uid] = count + 1
      if count < self.max_launch_count:
        plugin_dex, plugin_lib, plugin_class, arg_str, arg_int = inject_record
        self.attach(pid, plugin_dex, plugin_class, plugin_lib, arg_str, arg_int, AlbatrossInitFlags.FLAG_INJECT)
      else:
        return 0
    return 1

  def launch(self, target_package, plugin_dex, plugin_class, plugin_lib=None, arg_str: str = None, arg_int: int = 0):
    if not self.is_app_install(target_package):
      raise PackageNotInstalled(target_package)
    launch_callback = self.process_launch_callback
    clear_history_launch = Configuration.clear_history_launch
    if clear_history_launch:
      launch_callback.clear()
      self.client.clear_plugins()
    assert os.path.exists(plugin_dex)
    server_client = self.system_server_client
    assert server_client.init_intercept() != 0
    server_client.force_stop_app(target_package)
    app_id = server_client.set_intercept_app(target_package, clear_history_launch)
    assert self.system_server_subscriber
    launch_callback[app_id] = (plugin_dex, plugin_lib, plugin_class, arg_str, arg_int)
    self.app_launch_count[app_id] = 0
    server_client.start_activity(target_package, None, 0)

  @cached_property
  def init_plugin_env(self):
    try:
      client = self.client
      agent_dst = Configuration.system_server_agent_dst
      update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
      if update:
        agent_dir = os.path.dirname(agent_dst)
        oat_dir = agent_dir + '/oat/' + self.abi_lib_name
        self.root_shell('mkdir -p ' + oat_dir)
        server_pid = client.get_process_pid('system_server')
        if server_pid > 0 and client.is_injected(server_pid):
          self.restart_system_server()
          time.sleep(20)
      client.set_system_server_agent(agent_dst, Configuration.system_server_init_class, "system_server",
        AlbatrossInitFlags.NONE, Configuration.system_server_listen_address, 3)
      client.set_app_agent(self.agent_dex, None, Configuration.albatross_class_name,
        Configuration.albatross_agent_class, Configuration.albatross_register_func, AlbatrossInitFlags.NONE)
      return True
    except:
      return cached_property.nil_value

  def launch_fast(self, target_package, plugin_dex, plugin_class, plugin_lib=None, arg_str: str = None,
      arg_int: int = 0):
    uid = self.get_package_uid(target_package)
    if not uid:
      return False
    if not self.init_plugin_env:
      return False
    client = self.client
    assert os.path.exists(plugin_dex)
    plugin_dex_device = Configuration.app_injector_dir + os.path.basename(plugin_dex)
    self.push_file(plugin_dex, plugin_dex_device, mode='444')
    plugin = Plugin.create(plugin_dex, plugin_class, plugin_lib, arg_str, arg_int)
    if not plugin.is_register:
      client.register_plugin(plugin.plugin_id, plugin_dex_device, plugin_lib, plugin_class, arg_str, arg_int)
      plugin.is_register = True
    elif plugin.need_flush:
      client.modify_plugin(plugin.plugin_id, plugin_class, arg_str, arg_int)
      plugin.need_flush = False
    client.add_plugin_rule(plugin.plugin_id, uid)
    self.stop_app(target_package)
    self.start_app(target_package)
    return True

  def attach(self, package_or_pid, plugin_dex, plugin_class, plugin_lib=None, arg_str: str = None, arg_int: int = 0,
      init_flags=AlbatrossInitFlags.NONE):
    if isinstance(package_or_pid, str):
      pids = self.pidof(package_or_pid)
    else:
      pids = [package_or_pid]
    success = []
    if pids:
      assert os.path.exists(plugin_dex)
      client = self.client
      plugin_dex_device = Configuration.app_injector_dir + os.path.basename(plugin_dex)
      self.push_file(plugin_dex, plugin_dex_device, mode='444')
      for pid in pids:
        pid_int = int(pid)
        res = client.inject_albatross(pid_int, self.app_inject_flags, None)
        if res >= 0:
          if plugin_lib:
            assert os.path.exists(plugin_lib)
            if client.get_process_isa(pid_int) in [RunTimeISA.ISA_X86_64, RunTimeISA.ISA_ARM64]:
              lib_dst_device = self.lib_dir + os.path.basename(plugin_lib)
            else:
              lib_dst_device = self.lib32_dir + os.path.basename(plugin_lib)
            self.push_file(plugin_lib, lib_dst_device)
          else:
            lib_dst_device = None
          agent_dex = self.agent_dex
          res = client.load_plugin(pid_int, agent_dex, None, Configuration.albatross_class_name,
            Configuration.albatross_agent_class, Configuration.albatross_register_func,
            init_flags, plugin_dex_device, lib_dst_device, plugin_class, arg_str,
            arg_int)
          if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
            success.append(pid_int)
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
    cmd = self.shellcmd + '"dumpsys package ' + pkg + '| grep userId"'
    ret_str = run_shell(cmd)[1].decode("utf-8")
    if not ret_str:
      cmd = self.shellcmd + '"dumpsys package ' + pkg + '| grep uid"'
      ret_str = run_shell(cmd)[1].decode("utf-8")
    return int(ret_str.split("=")[1].split(maxsplit=1)[0].strip())

  def __repr__(self):
    return "Device: {}".format(self.device_id)


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
        system_server_subscriber.shutdown()
      system_server_client = cached_property.pop(device, 'system_server_client')
      if system_server_client is not cached_property.nil_value:
        system_server_client.close()
      client = cached_property.pop(device, 'client')
      if client is not cached_property.nil_value:
        client.close()
    devices.clear()

    _device_manager = None
