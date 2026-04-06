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
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

from .albatross_client import AlbatrossClient, DexLoadResult, InjectFlag, AlbatrossInitFlags, RunTimeISA, SetResult
from .common import Configuration, run_shell, lib_origin_name, generate_random_variable_name, SYSTEM_UID, OUT_TIME_CODE
from .exceptions import DeviceOffline, NoDeviceFound, DeviceNoFindErr, DeviceNotRoot, PackageNotInstalled, DeviceReboot
from .plugin import Plugin
from .rpc_client import byte
from .system_server_client import SystemServerClient
from .wrapper import cached_property


class DeviceBrand:
  OnePlus = 'OnePlus'
  RealMe = 'realme'
  Aosp = 'Android'
  Google = 'google'
  RedMi = 'Redmi'


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
          device_status = device[1]
          if device_status != "offline":
            if device_status != 'unauthorized':
              devices.append(device[0])
          else:
            run_shell(adb_path + ' disconnect ' + device[0], timeout=4)
      return devices
    return []
  except:
    return []


def get_usb_devices():
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
          device_id = device[0]
          device_status = device[1]
          if device_status != "offline":
            if '.' not in device_id and device_status != 'unauthorized':
              devices.append(device_id)
          else:
            run_shell(f'{adb_path} disconnect {device_id}')
      return devices
    return []
  except:
    return []


default_connect_timeout = 5


def try_connect(device_name, try_time=2):
  for i in range(try_time):
    ret_code, bs = run_shell(f"{adb_path} connect {device_name}", timeout=default_connect_timeout)
    if ret_code == OUT_TIME_CODE:
      return False
    if b'failed' not in bs:
      if b'already' in bs:
        return 'already connected'
      return True
    # return False
    # if i < try_time - 1:
    #   time.sleep(0.5)
  return False


def disconnect(device_name):
  get_device_manager().devices.pop(device_name, None)
  run_shell(f"{adb_path} disconnect {device_name}")


default_try_time = 3
default_timeout = 2


def check_device_alive(device_name, try_time=None):
  if not try_time:
    try_time = default_try_time
  if '.' in device_name:
    timeout = min(default_timeout * 2, 10)
  else:
    timeout = default_timeout
  for i in range(try_time):
    ret_code, bs = run_shell(f"{adb_path} -s {device_name} shell echo ping", timeout=timeout)
    if bs and bs.startswith(b'ping'):
      return True
    if '.' in device_name:
      code, res = run_shell(f"{adb_path} connect {device_name}", timeout=2)
      if b'failed' in res:
        return False
      if b'connected' in res:
        timeout = 8 + default_timeout
      else:
        timeout += 1
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

resume_activity_pattern = re.compile(r"mResumedActivity: ActivityRecord{\w+\s\w+\s([\w\.]+/[\w\.]+)")


class AlbatrossDevice(object):
  anti_detection = True
  auto_subscribe_system_server = True

  ret_code: int
  shell_user = 'shell'
  lib_dst: str
  lib_dir: str
  lib32_dir: str
  update_kill = True
  update_kill_system_server = True
  lib32_dst: str
  max_launch_count = 20
  reconnect = True
  cached_ip = False
  usb_mode = True

  def __init__(self, device_id):
    self.device_id = device_id
    self.cmd = adb_path + " -s " + device_id + " "
    shellcmd_list = [adb_path, "-s", device_id, "shell"]
    self.shellcmd = ' '.join(shellcmd_list) + ' '
    self.shellcmd_list = shellcmd_list
    self.process_launch_callback = {}
    self.app_launch_count = {}
    if '.' in device_id:
      self.usb_mode = False
      if ':' in device_id:
        device_id, self.tcp_port = device_id.split(':')
      self.connect_ip = device_id
    else:
      if AlbatrossDevice.cached_ip:
        self.connect_ip = self.get_device_ip()
        port = self.getprop('service.adb.tcp.port')
        if port:
          self.tcp_port = int(port)


  def shell(self, cmd, timeout=None, su_cmd=False) -> list | str:
    start_time = time.time()
    for i in range(4):
      shell_prefix = self.shellcmd_list
      if su_cmd:
        if sys.platform == 'win32' or "'" not in cmd:
          command = shell_prefix + [f"{self.su_file} -c '{cmd}'"]
        else:
          # command = shell_prefix + "'{} -c \"".format(self.su_file) + cmd + "\"'"
          # command = f"{self.shellcmd} {self.su_file} -c \"{cmd}\""
          command = shell_prefix + [f"{self.su_file} -c \"{cmd}\""]
      else:
        if sys.platform == 'win32' or True:
          command = shell_prefix + [cmd]
        else:
          command = f'{self.shellcmd} "{cmd}"'
      if timeout:
        ret = run_shell(command, timeout=timeout, shell=False)
      else:
        ret = run_shell(command, shell=False)
      self.ret_code = ret[0]
      result = ret[1].decode().strip()
      if 'not found' in result:
        if f"device '{self.device_id}' not found" in result:
          if i < 1:
            continue
          if i < 2:
            time.sleep(0.2)
            continue
          if self.usb_mode and self.connect_ip:
            if '.' not in self.shellcmd:
              if self.switch_to_ip_connect():
                continue
            elif self.switch_to_usb_connect():
              continue
          raise DeviceOffline(self)
      elif 'error: device offline' in result:
        raise DeviceOffline(self)
      end_time = time.time()
      cost = end_time - start_time
      if cost > 10:
        print(f'device {self.device_id} run {cmd[:32]} cost {cost}s')
      return result

  @cached_property
  def serial_no(self):
    device_id = self.device_id
    if '.' not in device_id:
      return device_id
    return self.getprop('ro.serialno')

  def device_alive(self, try_time=2):
    get_devices()
    if self.usb_mode:
      return check_device_alive(self.device_id, try_time)
    return check_device_alive(self.connect_ip, try_time)

  # ime_server=pkg/class
  def set_ime(self, ime_service, enable=True):
    if enable:
      self.root_shell(f"ime enable {ime_service} && ime set {ime_service}")
    else:
      self.root_shell("ime disable " + ime_service)

  @property
  def is_screen_on(self):
    ret_str = self.run_as_shell("dumpsys power | grep -E 'mWakefulness=|Display Power'")
    if 'Error' in ret_str:
      if "Can't find service" in ret_str:
        return None
      return True
    if 'mWakefulness=' in ret_str:
      return 'mWakefulness=Awake' in ret_str
    match = re.search(r"Display Power: state=(\w+)", ret_str)
    return match.group(1) == 'ON'

  def wake_up(self):
    ret = self.is_screen_on
    if not ret:
      if ret is None:
        self.reboot()
        print('Rebooting for server:' + self.device_id)
        return
      self.run_as_shell("input keyevent 26")
    else:
      self.click(1, 1)

  def lock_screen(self):
    if self.is_screen_on:
      self.run_as_shell("input keyevent 26")

  def click(self, x, y):
    if x and y:
      self.run_as_shell(f"input tap {x} {y}")
      return True
    return False

  def back(self):
    run_shell(self.shellcmd + 'input keyevent 4')

  def reboot(self):
    run_shell(self.cmd + ' reboot')

  def screen_size(self, size=None):
    if size is None:
      cmd = self.shellcmd + "wm size"
      lines: str = run_shell(cmd)[1].decode("utf-8")
      lines = lines.rsplit(':', maxsplit=1)[-1]
      width, height = re.findall("(\\d+)", lines)
      return int(width), int(height)
    else:
      cmd = self.shellcmd + "wm size " + size
      lines = run_shell(cmd)[1].decode("utf-8")
      return lines

  @cached_property
  def screen_width(self):
    return self.screen_size()[0]

  @cached_property
  def screen_height(self):
    return self.screen_size()[1]

  @cached_property
  def swipe_direction(self):
    x, y = self.screen_size()
    halfX = x / 2
    thirdX = x / 3
    two_thirdX = thirdX * 2
    halfY = y / 2
    thirdY = y / 3
    two_thirdY = thirdY * 2
    dirdict = {
      "left": (two_thirdX, halfY, thirdX, halfY),
      "right": (thirdX, halfY, two_thirdX, halfY),
      "up": (halfX, two_thirdY, halfX, thirdY),
      "down": (halfX, thirdY, halfX, two_thirdY),
    }
    return dirdict

  def swipe(self, x1, y1, x2, y2, time=None):
    cmd = self.shellcmd + "input swipe {} {} {} {}".format(int(x1), int(y1), int(x2), int(y2))
    if time:
      cmd += " {}".format(time)
    run_shell(cmd)

  def swipe_to(self, direction='up'):
    dirdict = self.swipe_direction
    return self.swipe(*dirdict[direction])

  def check_alive(self):
    if not self.device_alive(2 if self.usb_mode else 3):
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
    return self.shell(cmd, timeout, True)

  root_shell = su_shell

  def switch_shell_run(self, cmd, timeout=10):
    on = self.is_selinux_on()
    if on:
      self.setenforce(False)
    cmd = self.shellcmd + "'{} shell -c \"".format(self.su_file) + cmd + "\"'"
    ret = run_shell(cmd, timeout=timeout)
    self.ret_code = ret[0]
    result = ret[1].decode().strip()
    if on:
      self.setenforce(True)
    return result

  run_as_shell = shell

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
      if self.brand == 'realme':
        self.run_as_shell = self.switch_shell_run
      return True
    shell_root = self.is_shell_root()
    if shell_root:
      self.root_shell = self.su_shell
    return shell_root

  def getprop(self, prop):
    return self.shell(f'getprop {prop}')

  @cached_property
  def debuggable(self):
    return self.shell('getprop ro.debuggable') == '1'

  app_agent_updated = False

  @cached_property
  def device_config_path(self):
    device_dir = Configuration.config_dir + "device/"
    os.makedirs(device_dir, exist_ok=True)
    return device_dir + f"device_{self.serial_no}_config.json"

  update_count = 0

  def flush_config(self):
    if self.update_count:
      device_config_path = self.device_config_path
      with open(device_config_path, 'w') as fp:
        json.dump(self.device_config, fp, ensure_ascii=False, indent=1)
      self.update_count = 0

  @cached_property
  def device_config(self):
    device_config_path = self.device_config_path
    if os.path.exists(device_config_path):
      with open(device_config_path, 'r') as fp:
        device_config = json.load(fp)
    else:
      device_config = {}
    if not device_config:
      lib_name = 'lib' + generate_random_variable_name(min_length=2, max_length=5) + '.so'
      app_agent_name = 'framework-' + generate_random_variable_name(min_length=2, max_length=6) + '.jar'
      device_config = {'lib_name': lib_name, 'app_agent_name': app_agent_name,
                       'server_port': 'localabstract:' + generate_random_variable_name(min_length=2,
                         max_length=8), 'dex_maps': {}}
      with open(device_config_path, 'w') as fp:
        json.dump(device_config, fp, ensure_ascii=False, indent=1)
    return device_config

  @cached_property
  def agent_dex(self):
    plugin_dir = Configuration.app_plugin_home
    app_agent_name = Configuration.app_agent_name
    if app_agent_name == 'random':
      app_agent_name = self.device_config['app_agent_name']
    dst = plugin_dir + app_agent_name
    res = self.push_file(Configuration.app_agent_file, dst, mode='444', check=True)
    if res:
      self.app_agent_updated = True
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
    md5_current = False
    if check or os.stat(file).st_size > 8192:
      if dst[-1] == "/":
        dst += os.path.basename(file)
      md5_current = self.get_file_md5(dst)
      if md5_dst == md5_current:
        if extra_cmds:
          self.root_shell(';'.join(extra_cmds))
        return False
    if self.shell_user == 'shell' and md5_current is not None:
      self.delete_file(dst)
    command = self.cmd + ' push "{}" "{}"'.format(file, dst)
    ret_code, s = run_shell(command)
    res = ret_code == 0
    if res:
      if extra_cmds:
        self.root_shell(';'.join(extra_cmds))
      print(s)
      return res
    elif b'pushed' in s:
      new_md5 = self.get_file_md5(dst)
      if new_md5 == md5_dst:
        return True
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
    ret_code, ret = run_shell(self.shellcmd + f'\'ps -ef | grep "{cmd_line}"\'')
    if ret:
      ret = ret.decode()
      lines = ret.split('\n')
      for line in lines:
        if not line:
          continue
        if 'grep ' in line:
          continue
        pids.append(line.split(maxsplit=2)[1])
    return pids

  def pidof(self, process_name):
    s = self.shell('pidof ' + process_name)
    if s:
      return [int(i) for i in s.split()]
    return []

  def kill_process(self, process):
    pids = self.pidof(process)
    if pids:
      for pid in pids:
        self.kill_pid(pid)
        print('kill', process, pid)

  def kill_pid(self, pid, sig=9):
    if pid:
      self.root_shell(f"kill -{sig} {pid}")

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

  @cached_property
  def cpu_temp_path(self):
    expect_path = '/sys/class/thermal/thermal_zone5/'
    res = self.root_shell('cat ' + expect_path + 'type')
    if 'cpu' in res:
      return expect_path + 'temp'
    for i in range(0, 10):
      if i == 5:
        continue
      expect_path = f'/sys/class/thermal/thermal_zone{i}/'
      res = self.root_shell('cat ' + expect_path + 'type')
      if 'cpu' in res:
        return expect_path + 'temp'
    return None

  def get_cpu_temp(self):
    temp_path = self.cpu_temp_path
    if not temp_path:
      return 0
    v = self.root_shell('cat ' + temp_path)
    try:
      res = int(v)
      if res > 1000:
        return res // 1000
      return res
    except:
      return 0

  def get_battery_level(self):
    result = self.shell('dumpsys battery | grep level')
    return int(result.split(':')[1])

  def kill_client(self):
    self.kill_process(os.path.basename(Configuration.server_dst_path))

  def get_client(self) -> AlbatrossClient:
    if not self.is_root:
      raise DeviceNotRoot(self)
    server_dst_path = Configuration.server_dst_path
    server_dst_path = '/data/local/tmp/' + server_dst_path
    server_port = Configuration.server_port
    if server_port == 'random':
      # res = re.findall(r'albatross_server (\w+)', self.shell('ps -ef | grep albatross_server'))
      # if res and res[0] and len(res) < 16:
      #   server_port = 'localabstract:' + res[0]
      # else:
      server_port = self.device_config.get('server_port', 'localabstract:albatross_manager')
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
    device_id = self.device_id
    if lib_name == 'random':
      lib_name = self.device_config['lib_name']
    app_lib_dst = lib_dir + lib_name
    self.lib_dst = app_lib_dst
    if app_lib_dst != server_lib_dst:
      self.push_file(abi_lib, app_lib_dst, mode='644', file_type=self.file_type)
    lib_dst_32 = None
    lib_src_32 = None
    if abi_lib32 and self.support_32:
      lib_src_32, abi32_name = abi_lib32
      if os.path.exists(lib_src_32):
        self.lib32_dir = Configuration.lib_path + abi32_name + "/"
        lib_dst_32 = self.lib32_dir + lib_name
        self.push_file(lib_src_32, lib_dst_32, mode='644', file_type=self.file_type)
        self.lib32_dst = lib_dst_32
    if update and self.update_kill:
      self.kill_process(os.path.basename(server_dst_path))
    else:
      try:
        client = AlbatrossClient(local_port, '127.0.0.1', 'albatross-' + device_id, 500)
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
      if sys.platform == 'win32':
        cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dir} {cmd_prefix} \'{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &\'"'
      else:
        cmd = f'{self.shellcmd} \'LD_LIBRARY_PATH={lib_dir} {cmd_prefix} "{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"\''
    else:
      cmd_prefix = "nohup "
      cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dir} {cmd_prefix} {server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"'
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    time.sleep(2)
    process.terminate()
    client = AlbatrossClient(local_port, '127.0.0.1', 'albatross-' + device_id, 500)
    client.set_arch_lib(self.lib_dst)
    if lib_dst_32:
      client.set_2nd_arch_lib(self.lib32_dst)
    if self.is_selinux_on():
      client.patch_selinux()
    return client

  def restart_system_server(self):
    print('try restart system server')
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
  def brand(self):
    return self.shell('getprop ro.product.brand')

  system_server_address = None

  @cached_property
  def system_server_subscriber(self) -> SystemServerClient:
    port = self.get_forward_port(self.system_server_address)
    system_client_class = self.system_client_class_impl
    subscribe_client = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
    subscribe_client.add_close_listener(self.on_system_subscribe_close, 'system_subscribe')
    subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
    subscribe_client.subscribe()
    return subscribe_client

  system_client_class_impl = SystemServerClient

  @cached_property
  def system_server_client(self) -> SystemServerClient:
    client = self.client
    system_client_class = self.system_client_class_impl
    agent_dst = Configuration.system_server_agent_dst
    if self.is_selinux_on():
      client.patch_selinux()
    update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
    if update:
      self.create_dex_oat_dir(agent_dst)
      server_pid = client.get_process_pid('system_server')
      if server_pid > 0 and agent_dst in self.root_shell(f'cat /proc/{server_pid}/maps'):
        if self.brand == DeviceBrand.RedMi:
          self.reboot()
          time.sleep(40)
          raise DeviceReboot(f'reboot device {self.device_id}')
        else:
          self.restart_system_server()
        time.sleep(20)
        if self.brand in [DeviceBrand.RealMe, DeviceBrand.OnePlus]:
          time.sleep(20)
          self.back()
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
      system_client_class.albatross_init_flags, None, self.system_server_init_flags, timeout=30)
    if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
      system_server_address = client.get_address(server_pid)
      system_server_address = 'localabstract:' + system_server_address
      self.system_server_address = system_server_address
      port = self.get_forward_port(system_server_address)
      system_server = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
      system_server.init()
      system_server.add_close_listener(self.on_system_client_close, 'system_disconnect')
      if self.auto_subscribe_system_server:
        subscribe_client = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
        subscribe_client.add_close_listener(self.on_system_subscribe_close, 'system_subscribe_close')
        subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
        subscribe_client.subscribe()
        # system_server.set_intercept_app(None)
        cached_property.reset(self, 'system_server_subscriber', subscribe_client)
      if res == DexLoadResult.DEX_LOAD_SUCCESS:
        system_inject_callback = self.system_inject_callback
        if system_inject_callback:
          try:
            system_inject_callback(self, system_server)
          except:
            pass
      return system_server
    return cached_property.nil_value

  connect_callback = None
  system_inject_callback = None

  @cached_property
  def client(self):
    client = self.get_client()
    client.add_close_listener(self.__on_close, 'albatross server api')
    if self.connect_callback is not None:
      try:
        self.__dict__['client'] = client
        self.connect_callback(self, client)
      except:
        pass
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
  app_init_flags = AlbatrossInitFlags.FLAG_LOG | AlbatrossInitFlags.FLAG_CALL_CHAIN | AlbatrossInitFlags.FLAG_INIT_RPC

  def on_launch_process(self, uid: int, pid: int, pkg: str, process: str, process_info: dict) -> byte:
    print(f'launch process {uid}:{pid}:{process}', process_info)
    inject_record = self.process_launch_callback.get(uid)
    if inject_record:
      count = self.app_launch_count[uid]
      self.app_launch_count[uid] = count + 1
      if count < self.max_launch_count:
        plugin_dex, plugin_lib, plugin_class, arg_str, arg_int = inject_record
        self.attach(pid, plugin_dex, plugin_class, plugin_lib, arg_str, arg_int,
          self.app_init_flags | AlbatrossInitFlags.FLAG_INJECT)
      else:
        return -1
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

  system_server_init_flags = 3
  system_server_restart_callback = None

  @cached_property
  def init_plugin_env(self):
    try:
      client = self.client
      agent_dst = Configuration.system_server_agent_dst
      update = self.push_file(Configuration.system_server_agent_file, agent_dst, mode='444', file_type=self.file_type)
      system_server_restart_callback = None
      if update:
        self.create_dex_oat_dir(agent_dst)
        server_pid = client.get_process_pid('system_server')
        if self.update_kill_system_server and server_pid > 0 and agent_dst in self.root_shell(
            f'cat /proc/{server_pid}/maps'):
          if self.brand == DeviceBrand.RedMi:
            self.reboot()
            time.sleep(40)
            raise DeviceReboot(f'reboot device {self.device_id}')
          else:
            self.restart_system_server()
          time.sleep(20)
          if self.brand in [DeviceBrand.RealMe, DeviceBrand.OnePlus]:
            time.sleep(20)
            self.back()
          system_server_restart_callback = self.system_server_restart_callback
      client.set_system_server_agent(agent_dst, Configuration.system_server_init_class, "system_server",
        AlbatrossInitFlags.NONE, None, self.system_server_init_flags)
      client.set_app_agent(self.agent_dex, None, Configuration.albatross_class_name,
        Configuration.albatross_agent_class, Configuration.albatross_register_func, self.app_init_flags)
      if not client.patch_selinux():
        self.setenforce(False)
      if system_server_restart_callback is not None:
        system_server_restart_callback(self)
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
    plugin = self.register_plugin(plugin_dex, plugin_class, plugin_params, plugin_flags, plugin_lib)
    res = client.add_plugin_rule(plugin.plugin_id, uid, target_package if uid == SYSTEM_UID else None)
    if res == SetResult.MISS_INFO:
      client.set_app_info(uid, target_package + ":" + str(self.get_package_version_code(target_package)))
    self.stop_app(target_package)
    self.start_app(target_package)
    return True

  def launch_with_plugins(self, target_package, plugins):
    uid = self.get_package_uid(target_package)
    if not uid:
      return False
    client = self.client
    for plugin in plugins:
      res = client.add_plugin_rule(plugin.plugin_id, uid, target_package if uid == SYSTEM_UID else None)
      if res == SetResult.MISS_INFO:
        client.set_app_info(uid, target_package + ":" + str(self.get_package_version_code(target_package)))
      elif res not in [SetResult.SET_OK, SetResult.SET_ALREADY]:
        return False
    self.start_app(target_package)
    return True

  def attach_with_plugins(self, package_or_pid, plugins, init_flags=AlbatrossInitFlags.FLAG_LOG, extra_info=None):
    client = self.client
    uid = -1
    if isinstance(package_or_pid, str):
      uid = self.get_package_uid(package_or_pid)
      pids = client.get_java_processes_by_uid(uid)
    elif type(package_or_pid) == int:
      pids = [package_or_pid]
    else:
      pids = package_or_pid
    success = []
    if pids and plugins:
      agent_dex = self.agent_dex
      for pid in pids:
        res = client.inject_albatross(pid, self.app_inject_flags, None)
        if res >= 0:
          success_count = 0
          for plugin in plugins:
            res = client.load_plugin(pid, agent_dex, None, Configuration.albatross_class_name,
              Configuration.albatross_agent_class, Configuration.albatross_register_func,
              init_flags, extra_info, plugin.dex_device_dst, plugin.plugin_lib, plugin.plugin_class,
              plugin.plugin_params, plugin.plugin_flags)
            if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
              success.append((pid, plugin))
              success_count += 1
          if success_count:
            if uid < 0:
              uid = client.process_uid(pid)
            callbacks = client.launch_callback.get(uid)
            if callbacks:
              client.invoke_callbacks(callbacks, uid, pid, None)

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
    plugin_name = os.path.basename(plugin_dex)
    if Configuration.lib_name == 'random':
      dex_map = self.device_config['dex_maps']
      map_name = dex_map.get(plugin_name)
      if not map_name:
        map_name = plugin_name[:3] + generate_random_variable_name(max_length=6) + '.jar'
        dex_map[plugin_name] = map_name
        plugin_name = map_name
        self.update_count += 1
      else:
        plugin_name = map_name
    plugin_dex_device = Configuration.app_plugin_home + plugin_name
    is_update = self.push_file(plugin_dex, plugin_dex_device, mode='444', check=True)
    if plugin_lib:
      assert os.path.exists(plugin_lib)
      lib_name = os.path.basename(plugin_lib)
      is_64 = '64' in plugin_lib
      if is_64:
        lib_dst = self.lib_dir + lib_name
      else:
        lib_dst = self.lib32_dir + lib_name
      is_update += self.push_file(plugin_lib, lib_dst, file_type=self.file_type, check=True)
      plugin_lib = lib_dst

    plugin = Plugin.create(plugin_dex, plugin_class, plugin_lib, plugin_params, plugin_flags)
    plugin_id = plugin.plugin_id
    client.register_plugin(plugin_id, plugin_dex_device, plugin_lib, plugin_class, plugin_params, plugin_flags)
    if plugin_id == plugin.nil_plugin_id:
      plugin_id = client.get_plugin_id(plugin_dex_device, plugin_class)
      plugin.plugin_id = plugin_id
    plugin.dex_device_dst = plugin_dex_device
    if is_update:
      plugin.plugin_updated = True
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

  def add_plugin_rule(self, plugin: Plugin, target_package, uid=None):
    assert self.init_plugin_env
    if self.update_count:
      self.flush_config()
    if not uid:
      uid = self.get_package_uid(target_package)
    client = self.client
    res = client.add_plugin_rule(plugin.plugin_id, uid, target_package if uid == SYSTEM_UID else None)
    if res == SetResult.MISS_INFO:
      extra_info = target_package + ":" + str(self.get_package_version_code(target_package))
      client.set_app_info(uid, extra_info)
      return SetResult.SET_OK
    return res

  def attach(self, package_or_pid, plugin_dex, plugin_class, plugin_lib=None, plugin_params: str = None,
      plugin_flags: int = 0, init_flags=AlbatrossInitFlags.NONE, extra_info=None):
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
            init_flags, extra_info, plugin_dex_device, lib_dst_device, plugin_class, plugin_params,
            plugin_flags)
          if res in [DexLoadResult.DEX_LOAD_SUCCESS, DexLoadResult.DEX_ALREADY_LOAD]:
            success.append(pid)
    return success

  def forward_tcp(self, local_port, device_port=None):
    if device_port is None:
      device_port = local_port
    ret_code, _ = self.adb_cmd("forward", "tcp:%d" % local_port, "tcp:%d" % device_port)
    return ret_code

  def remote_ports(self, remote_port):
    device_name = self.device_id
    port_list = []
    if type(remote_port) == int:
      remote_port = 'tcp:' + str(remote_port)
    for s, lp, rp in self.forward_list():
      if rp == remote_port and s == device_name:
        local_port = int(lp[4:])
        port_list.append(local_port)
    return port_list

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

  def dumpui(self, path=None):
    try:
      ret_str = self.shell("uiautomator dump /data/local/tmp/uidump.xml")
      if not ret_str.startswith("UI hierchary dumped to"):
        return False
      if path:
        pull_cmd = self.cmd + "pull /data/local/tmp/uidump.xml {}".format(path)
        run_shell(pull_cmd)
        return True
      else:
        pull_cmd = self.shellcmd + " cat /data/local/tmp/uidump.xml"
        return run_shell(pull_cmd)[1]
    except:
      return False

  def get_app_main_activities(self, pkg):
    ret_str = self.run_as_shell(
      "dumpsys package " + pkg + " | grep -A20 android.intent.action.MAIN:")  # + " | grep android.intent.action.MAIN:"
    res = ret_str.split("android.intent.action.MAIN:")
    if len(res) > 1:
      activities = re.findall(pkg + r'/[\w.]+', res[1])
      return activities
      # str_list = (re.match("(\\s+[\\da-f]+\\s+[\\w/.]+)+", res[1]).group(0).strip().split())
      # activities = [val for idx, val in enumerate(str_list) if idx & 1]
      # return activities
    return []

  def get_app_main_activity(self, pkg):
    cmd = f"{{ cmd package resolve-activity --brief {pkg} 2>/dev/null || dumpsys package {pkg}; }} |  grep -E '^[a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+$' | head -n1"
    res = self.run_as_shell(cmd)
    return res.strip()

  def start_activity(self, pkg_activity, action=None):
    command = "am start -n {}".format(pkg_activity)
    if action:
      command += ' -a ' + action
    # command = self.cmd + 'shell am start -n {}/{}'.format(pkg_name, activity)
    ret_str = self.run_as_shell(command)
    if self.ret_code == 0 and "Error type" not in ret_str:
      return True
    else:
      return False

  def stop_app(self, target_package):
    command = self.run_as_shell("am force-stop " + target_package)
    if self.ret_code == 0:
      return True
    return False

  def get_package_info(self, package):
    info_string = self.run_as_shell(
      "dumpsys package " + package + " | grep -E 'userId|appId|versionCode|minSdk|targetSdk|versionName|dataDir' | head -n 20")
    if "Unable to find" in info_string:
      return None
    if 'Error with' in info_string:
      return None
    uid_s = re.findall(r'(?:userId|appId)=(\S*)', info_string)
    if len(uid_s) > 2:
      return None
    attrs = [
      "versionCode",
      "minSdk",
      "targetSdk",
      "versionName",
      "dataDir",
      # 'package',
    ]
    try:
      result = {'uid': uid_s[0]}
      for attr in attrs:
        val = re.search(attr + "=(\\S*)", info_string).groups()[0]
        result[attr] = val
      return result
    except:
      return None

  def package_apk_path(self, package):
    package_pattern = re.compile("package:(\\S+)")
    package_strs = self.shell("pm path " + package)
    return package_pattern.findall(package_strs)

  def dump_apk(self, package, output_path, overwrite=False):
    if not output_path.endswith(".apk"):
      package_info = self.get_package_info(package)
      versionName = package_info["versionName"]
      output_path = os.path.join(output_path, package + "_" + versionName + ".apk")
    paths = self.package_apk_path(package)
    if len(paths) == 1:
      dir_path = os.path.dirname(output_path)
      if not os.path.exists(dir_path):
        os.makedirs(dir_path)
      if not os.path.exists(output_path) or overwrite:
        self.pull_file(paths[0], output_path)
      return output_path
    else:
      if not os.path.exists(output_path):
        os.makedirs(output_path)
      elif not overwrite:
        return output_path.rstrip('/')
      if output_path[-1] != '/':
        output_path += "/"
      for path in paths:
        self.pull_file(path, output_path)
    return output_path[-1:]

  def start_app(self, target_package):
    main_activity = self.get_app_main_activity(target_package)
    if self.start_activity(main_activity):
      return True
    activities = self.get_app_main_activities(target_package)
    if activities:
      for activity in activities:
        if activity == main_activity:
          continue
        if self.start_activity(activity):
          return True
    else:
      return False

  def is_app_install(self, pkg):
    return pkg in self.get_user_packages(include_disabled=True)

  def install_if_not_exist(self, package, apk, version_code=None, ignore_gt=False):
    try:
      v = self.get_package_version_code(package)
    except:
      v = self.get_package_version_code(package)
    if v:
      if not version_code:
        return False
      if v == int(version_code):
        return False
      if ignore_gt and v > int(version_code):
        return False
    if not v and self.brand in [DeviceBrand.RealMe, DeviceBrand.OnePlus]:
      self.silence_install(apk)
    else:
      res = self.adb_cmd('install -r -d -t ' + apk)
    self.cached_versions.pop(package, None)
    return True

  def get_user_packages(self, include_disabled=False, include_system=False):
    if include_disabled:
      option = []
    else:
      option = ['-e']
    if not include_system:
      option.append('-3')
    pkgs = self.run_as_shell('pm list packages ' + ' '.join(option))
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

  base_activity_pattern = re.compile(
    r"Run\s#\d+:\sActivityRecord{\w+\s\w+\s([\w\.]+/[\w\.]+)"
  )

  def get_activity_stack(self, pkg=None):
    cmd = self.cmd + 'shell " dumpsys activity | grep -i run"'
    _, rstr = run_shell(cmd)
    if b"Illegal" in rstr:
      _, rstr = run_shell(cmd)
    rstr = rstr.decode("utf-8")
    if pkg:
      pattern = re.compile(
        r"Run\s#\d+:\sActivityRecord{\w+\s\w+\s(%s/[\w\.]+)" % (pkg)
      )
    else:
      pattern = self.base_activity_pattern
    result = pattern.findall(rstr)
    return result

  def top_app(self):
    res = self.shell("dumpsys window | grep mCurrentFocus")
    if res:
      result = re.findall(r'([\w.]+)/([\w.]+)', res)
      if result:
        return result[0]
    stack = self.get_activity_stack()
    if not stack:
      cmd = self.cmd + 'shell " dumpsys activity | grep -i mResumedActivity"'
      _, rstr = run_shell(cmd)
      stack = resume_activity_pattern.findall(rstr.decode())
    top_stack = stack[0].split("/")
    return top_stack[0], top_stack[1]

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
    command = "screencap -p  /sdcard/screen.png"
    self.run_as_shell(command)
    if self.ret_code:
      return False
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
      os.makedirs(dirpath)
    return self.pull_file("/sdcard/screen.png", path)

  def get_package_uid(self, pkg):
    ret_str = self.run_as_shell('dumpsys package ' + pkg + " | grep -E 'userId=|appId=' | head -n 20")  # uid=|
    res = re.findall(r'(?:appId|uid|userId)=(\d+)', ret_str)
    if res and len(set(res)) == 1:
      return int(res[0])
    return None

  def get_package_uid_and_version(self, pkg):
    ret_str = self.run_as_shell(
      'dumpsys package ' + pkg + " | grep -E 'userId=|appId=|versionCode=' | head -n 20")  # uid=|
    uid_match = re.findall(r'(?:appId|uid|userId)=(\d+)', ret_str)
    version_match = re.findall(r'versionCode=(\d+)', ret_str)
    if version_match and len(version_match) < 3 and uid_match:
      return int(uid_match[0]), int(version_match[0])
    return None, None

  @cached_property
  def cached_versions(self):
    return {}

  def get_package_version_code(self, pkg):
    cached_versions = self.cached_versions
    if pkg in cached_versions:
      return cached_versions[pkg]
    ret_str = self.run_as_shell('dumpsys package ' + pkg + " | grep versionCode= | head -n 10")
    if not ret_str:
      return False
    res = re.findall(r'versionCode=(\d+)', ret_str)
    if res and len(res) < 3:
      version = int(res[0])
      cached_versions[pkg] = version
      return version
    return None

  def uninstall_package(self, pkg):
    self.cached_versions.pop(pkg, None)
    self.adb_cmd(f'uninstall {pkg}')

  def __repr__(self):
    return "Device: {}".format(self.device_id)

  cached_public_ip_address = None

  def get_public_ip_address(self):
    ip = self.cached_public_ip_address
    if ip:
      return ip
    try:
      ip = self.shell(
        "echo -e 'GET /ip HTTP/1.1\nHost: ifconfig.me\nConnection: close\n\n' | nc ifconfig.me 80 | grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}'",
        timeout=15)
    except:
      return self.connect_ip
    if ip:
      self.cached_public_ip_address = ip
    else:
      return self.cached_public_ip_address
    return ip

  def get_device_ip(self):
    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    for cmd in ['ip addr show wlan0', 'ifconfig wlan0', 'ip addr']:
      ret_code, bs = run_shell(self.shellcmd + cmd)
      if ret_code:
        continue
      s = bs.decode()
      ips = re.findall(ip_pattern, s)
      # 过滤无效 IP（排除 0.0.0.0、127.0.0.1 等非局域网 IP）
      valid_ips = [
        ip for ip in ips
        if not ip.startswith("0.") and '.255' not in ip
           and not ip.startswith("127.") and 1 <= int(ip.split(".")[0]) <= 223
      ]
      if valid_ips:
        return valid_ips[0]
    return None

  connect_ip = None
  tcp_port = 5555

  def get_connect_device_id(self):
    if '.' not in self.cmd:
      return self.device_id
    return f'{self.connect_ip}:{self.tcp_port}'

  def update_ip(self):
    ip = self.get_device_ip()
    if ip and self.connect_ip != ip:
      self.connect_ip = ip
      return True
    return False

  def switch_to_ip_connect(self):
    if not self.usb_mode:
      return False
    ip = self.get_device_ip()
    if not ip:
      ip = self.connect_ip
    if not ip:
      return False
    run_shell(f'{adb_path} -s {self.device_id} tcpip {self.tcp_port}')
    for z in range(2):
      ret_code, bs = run_shell(adb_path + ' connect ' + ip + ":" + str(self.tcp_port))
      if b'failed' not in bs and b'connected to' in bs:
        cmd = f'{adb_path} -s {ip} '
        shell_cmd = cmd + 'shell '
        time.sleep(0.3)
        for i in range(2):
          _, ret = run_shell(shell_cmd + 'echo hello')
          if b'hello' in ret:
            self.shellcmd = shell_cmd
            self.shellcmd_list = shell_cmd.strip().split()
            self.cmd = cmd
            self.connect_ip = ip
            return True
          elif not i:
            time.sleep(1)
    return False

  def switch_to_usb_connect(self):
    if not self.usb_mode:
      return False
    if '.' in self.cmd:
      cmd = f'{adb_path} -s {self.device_id} '
      shellcmd = cmd + 'shell '
      ret_code, bs = run_shell(shellcmd + 'echo hello')
      if b'hello' in bs:
        self.cmd = cmd
        self.shellcmd = shellcmd
        self.shellcmd_list = shellcmd.strip().split()
        run_shell(f'{adb_path} disconnect {self.connect_ip}:{self.tcp_port}')
        return True
    return False

  def get_ram_size(self):
    ram_output = self.shell("cat /proc/meminfo | grep MemTotal")
    if not ram_output:
      return None
    # 提取数字（KB）
    ram_kb = re.findall(r'\d+', ram_output)
    if not ram_kb:
      print("未解析到RAM大小")
      return None
    # 转换为GB（1GB = 1024*1024 KB）
    ram_gb = int(ram_kb[0]) / (1024 * 1024)
    return round(ram_gb, 2)

  def get_rom_size(self):
    """
    获取设备ROM信息：返回总ROM大小、用户可用ROM大小（/data分区），单位：GB（保留两位小数）
    """
    rom_info = {
      "total_rom": None,
      "available_rom": None
    }
    df_output = self.shell('df -h /data | grep /data')
    if df_output:
      parts = df_output.split()
      if len(parts) >= 2:
        size_str = parts[1]
        # Size列（总可用分区大小）
        avail_size = parts[3]
        if 'G' in avail_size:
          rom_info["available_rom"] = int(avail_size.replace('G', ''))
        elif 'M' in avail_size:
          rom_info["available_rom"] = round(float(avail_size.replace('M', '')) / 1024, 2)
        rom_info['total_rom'] = size_str
        return rom_info
    # 1. 获取总ROM大小（通过分区总块数）
    total_rom_output = self.root_shell("cat /proc/partitions | grep -E 'mmcblk0$|sd[a-z]$'")
    if total_rom_output:
      # 提取数字（KB），取最后一列前的数字
      total_rom_kb = re.findall(r'\d+', total_rom_output)
      if total_rom_kb and len(total_rom_kb) >= 3:
        rom_info["total_rom"] = str(round(max([int(i) for i in total_rom_kb]) / (1024 * 1024), 2)) + "G"
    return rom_info

  def silence_install(self, pkg_path):
    assert os.path.exists(pkg_path)
    temp_path = '/data/local/tmp/' + os.path.basename(pkg_path)
    self.push_file(pkg_path, temp_path)
    self.root_shell('pm install -r ' + temp_path + " && rm " + temp_path)

  @cached_property
  def storage_info(self):
    rom_size = self.get_rom_size()
    return f'{self.get_ram_size()}+{rom_size["available_rom"]}/{rom_size["total_rom"]}'

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

  def get_cached_device(self, device_id):
    return self.devices.get(device_id)

  def remove_device(self, device_id):
    return self.devices.pop(device_id, None)

  def get_devices(self, device_id) -> AlbatrossDevice:
    if device_id and ":" in device_id:
      if device_id not in run_shell(adb_path + " devices")[1].decode():
        if "." in device_id or "localhost" in device_id:
          run_shell(adb_path + " connect " + device_id, timeout=default_connect_timeout)
        else:
          port = device_id.split(":")[1]
          run_shell(adb_path + " connect 127.0.0.1:" + port, timeout=2)
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
