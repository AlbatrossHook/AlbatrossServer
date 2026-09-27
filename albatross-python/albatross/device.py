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
import hashlib
import ipaddress
import json
import os
import random
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass

from .albatross_client import AlbatrossClient, DexLoadResult, InjectFlag, AlbatrossInitFlags, RunTimeISA, SetResult, \
  MountResult
from .common import Configuration, run_shell, lib_origin_name, generate_random_variable_name, SYSTEM_UID, \
  OUT_TIME_CODE, FAULT_CODE, logger
from .exceptions import DeviceOffline, NoDeviceFound, DeviceNoFindErr, DeviceNotRoot, PackageNotInstalled, DeviceReboot
from .plugin import Plugin
from .rpc_client import byte
from .system_server_client import SystemServerClient
from .wrapper import cached_property, cached_class_property


class DeviceBrand:
  OnePlus = 'OnePlus'
  RealMe = 'realme'
  Aosp = 'Android'
  Google = 'google'
  RedMi = 'Redmi'
  OPPO = 'OPPO'
  Xiaomi = 'Xiaomi'


def _infer_adb_server_port(args, device_id):
  if device_id is not None:
    return adb_server_port_for(device_id)
  if len(args) >= 2 and str(args[0]) in ('connect', 'disconnect'):
    return adb_server_port_for(args[1])
  return AdbConfig.adb_server_ports[0]


def run_adb(*args, device_id=None, server_port=None, **kwargs):
  if server_port is None:
    server_port = _infer_adb_server_port(args, device_id)
  command = [AdbConfig.adb_path, '-P', str(server_port)]
  if device_id is not None:
    command.extend(['-s', str(device_id)])
  command.extend(str(arg) for arg in args)
  return run_shell(command, shell=False, **kwargs)


class AdbErrorCode:
  OK = 'ok'
  TIMEOUT = 'adb_timeout'
  UNAVAILABLE = 'adb_unavailable'
  COMMAND_FAILED = 'adb_command_failed'
  DISCONNECT_FAILED = 'adb_disconnect_failed'
  TCP_UNREACHABLE = 'adb_tcp_unreachable'


@dataclass(frozen=True)
class AdbCommandResult:
  return_code: int
  output: bytes
  error_code: str
  elapsed_ms: float

  @property
  def ok(self):
    return self.error_code == AdbErrorCode.OK and self.return_code == 0


def run_adb_result(*args, device_id=None, server_port=None, **kwargs):
  started = time.monotonic()
  try:
    run_kwargs = dict(kwargs)
    if server_port is not None:
      run_kwargs['server_port'] = server_port
    return_code, output = run_adb(*args, device_id=device_id, **run_kwargs)
  except Exception as exc:
    # Keep callers on the structured error path even if a custom runner or
    # an unexpected subprocess wrapper raises instead of returning FAULT_CODE.
    return AdbCommandResult(
      FAULT_CODE,
      str(exc).encode('utf-8', errors='replace'),
      AdbErrorCode.UNAVAILABLE,
      (time.monotonic() - started) * 1000,
    )
  elapsed_ms = (time.monotonic() - started) * 1000
  if return_code == 0:
    error_code = AdbErrorCode.OK
  elif return_code == OUT_TIME_CODE:
    error_code = AdbErrorCode.TIMEOUT
  elif return_code == FAULT_CODE:
    error_code = AdbErrorCode.UNAVAILABLE
  else:
    error_code = AdbErrorCode.COMMAND_FAILED
  return AdbCommandResult(return_code, output or b'', error_code, elapsed_ms)


def _parse_device_lines(lines, usb_only=False):
  devices = []
  if not lines or 'Error' in lines:
    return devices
  for line in lines[1:]:
    fields = line.strip().split()
    if len(fields) != 2:
      continue
    device_id, status = fields
    if status in ('offline', 'unauthorized'):
      continue
    if usb_only and ('.' in device_id or ':' in device_id):
      continue
    devices.append(device_id)
  return devices


def _list_devices_on_server(server_port, usb_only=False):
  result = run_adb_result('devices', server_port=server_port)
  if not result.ok:
    return result, []
  try:
    lines = result.output.decode('utf-8', errors='replace').splitlines()
    if any(line.strip() == 'Error:' for line in lines):
      return AdbCommandResult(
        result.return_code, result.output, AdbErrorCode.COMMAND_FAILED, result.elapsed_ms,
      ), []
    return result, _parse_device_lines(lines, usb_only=usb_only)
  except (AttributeError, UnicodeError):
    return AdbCommandResult(
      result.return_code, result.output, AdbErrorCode.COMMAND_FAILED, result.elapsed_ms,
    ), []


def list_devices(usb_only=False, server_port=None):
  """Return an adb result and usable ids from one or all configured servers."""
  if server_port is not None:
    return _list_devices_on_server(server_port, usb_only=usb_only)

  ports = AdbConfig.adb_server_ports[:1] if usb_only else AdbConfig.adb_server_ports
  successful_results = []
  first_failure = None
  devices = []
  for port in ports:
    result, server_devices = _list_devices_on_server(port, usb_only=usb_only)
    if result.ok:
      successful_results.append(result)
      for device_id in server_devices:
        if device_id not in devices:
          devices.append(device_id)
    elif first_failure is None:
      first_failure = result

  if not successful_results:
    return first_failure, []
  if len(ports) == 1:
    return successful_results[0], devices
  output = 'List of devices attached\n' + ''.join(
    f'{device_id}\tdevice\n' for device_id in devices
  )
  return AdbCommandResult(
    0,
    output.encode('utf-8'),
    AdbErrorCode.OK,
    sum(result.elapsed_ms for result in successful_results),
  ), devices


def check_socket_port(ip, port):
  try:
    port = int(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
      s.settimeout(2)
      result = s.connect_ex((ip, port))
    return result == 0
  except:
    return False


def is_socket_port_open(ip, port):
  return check_socket_port(ip, port)


def parse_tcp_endpoint(endpoint):
  """Return ``(host, port)`` for an adb TCP endpoint, otherwise ``None``."""
  endpoint = str(endpoint or '').strip()
  if not endpoint:
    return None
  if endpoint.startswith('['):
    closing = endpoint.find(']')
    if closing <= 1 or endpoint[closing + 1:closing + 2] != ':':
      return None
    host = endpoint[1:closing]
    port_text = endpoint[closing + 2:]
  else:
    host, separator, port_text = endpoint.rpartition(':')
    if not separator or not host:
      return None
  try:
    port = int(port_text)
  except (TypeError, ValueError):
    return None
  if not 1 <= port <= 65535:
    return None
  return host, port


def normalize_tcp_endpoint(endpoint):
  """Return a stable textual form for hashing an adb TCP endpoint."""
  target = parse_tcp_endpoint(endpoint)
  if target is None:
    return None
  host, port = target
  host = host.strip().lower().rstrip('.')
  try:
    host = ipaddress.ip_address(host).compressed
  except ValueError:
    pass
  if ':' in host:
    host = f'[{host}]'
  return f'{host}:{port}'


def adb_server_port_for(device_id):
  ports = AdbConfig.adb_server_ports
  endpoint = normalize_tcp_endpoint(device_id)
  if endpoint is None:
    return ports[0]
  shard = zlib.crc32(endpoint.encode('utf-8')) % len(ports)
  return ports[shard]


def probe_tcp_endpoint(endpoint, timeout):
  target = parse_tcp_endpoint(endpoint)
  if target is None:
    return None
  try:
    with socket.create_connection(target, timeout=timeout):
      return True
  except (OSError, TypeError, ValueError):
    return False


@contextmanager
def get_available_port():
  """
  安全获取一个可用端口，并在 with 块内保持占用
  退出 with 块后**自动释放**，崩溃也会释放
  """
  temp_sock = None
  try:
    # 创建 socket
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 端口复用，避免 TIME_WAIT 报错
    temp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # 绑定系统分配的空闲端口（会直接占用，别人无法抢）
    temp_sock.bind(("", 0))
    # 获取端口号
    port = temp_sock.getsockname()[1]
    # 把端口返回给 with 语句使用
    yield port
  finally:
    # 无论是否崩溃、报错、正常退出，都会执行关闭！
    if temp_sock:
      temp_sock.close()


def get_devices():
  return list_devices()[1]


def get_usb_devices():
  return list_devices(usb_only=True)[1]


default_connect_timeout = 5


def _env_positive_int(name, default):
  try:
    value = int(os.environ.get(name, default))
    return value if value > 0 else default
  except (TypeError, ValueError):
    return default


def _env_non_negative_float(name, default):
  try:
    value = float(os.environ.get(name, default))
    return value if value >= 0 else default
  except (TypeError, ValueError):
    return default


def _env_bool(name, default):
  value = os.environ.get(name)
  if value is None:
    return default
  return value.strip().lower() not in ('0', 'false', 'no', 'off')


def _valid_adb_server_port(value):
  try:
    port = int(value)
  except (TypeError, ValueError):
    return None
  return port if 1024 <= port <= 65535 else None


def _env_adb_server_ports():
  configured = os.environ.get('ALBATROSS_ADB_SERVER_PORTS')
  values = configured.split(',') if configured else [os.environ.get('ADB_SERVER_PORT', 5037)]
  ports = []
  for value in values:
    port = _valid_adb_server_port(str(value).strip())
    if port is not None and port not in ports:
      ports.append(port)
  if ports:
    return tuple(ports)
  legacy_port = _valid_adb_server_port(os.environ.get('ADB_SERVER_PORT', 5037))
  return (legacy_port or 5037,)


class AdbConfig(object):
  @cached_class_property
  def adb_server_ports(self):
    return _env_adb_server_ports()

  @cached_class_property
  def adb_connect_enabled(self):
    return _env_bool('ALBATROSS_ADB_CONNECT_ENABLED', True)

  @cached_class_property
  def adb_transport_owner(self):
    return _env_bool('ALBATROSS_ADB_TRANSPORT_OWNER', self.adb_connect_enabled)

  @cached_class_property
  def adb_tcp_probe_enabled(self):
    return _env_bool('ADB_TCP_PROBE_ENABLED', True)

  @cached_class_property
  def adb_tcp_probe_timeout(self):
    return _env_non_negative_float('ADB_TCP_PROBE_TIMEOUT', 0.7)

  @cached_class_property
  def adb_connect_concurrency(self):
    return _env_positive_int('ADB_CONNECT_CONCURRENCY', 4)

  @cached_class_property
  def adb_connect_failure_quarantine(self):
    return _env_non_negative_float('ADB_CONNECT_FAILURE_QUARANTINE', 360)

  @cached_class_property
  def adb_connect_cooldown(self):
    return _env_non_negative_float('ADB_CONNECT_COOLDOWN', 45)

  @cached_class_property
  def adb_connect_recovery_probe_interval(self):
    return _env_non_negative_float('ADB_CONNECT_RECOVERY_PROBE_INTERVAL', 5)

  @cached_class_property
  def adb_connect_recovery_probe_max_interval(self):
    return _env_non_negative_float('ADB_CONNECT_RECOVERY_PROBE_MAX_INTERVAL', 60)

  @cached_class_property
  def adb_disconnect_retry_cooldown(self):
    return _env_non_negative_float('ADB_DISCONNECT_RETRY_COOLDOWN', 45)

  @cached_class_property
  def device_health_ttl(self):
    return _env_non_negative_float('ADB_DEVICE_HEALTH_TTL', 3)

  @cached_class_property
  def connection_coordinator(self) -> '_AdbConnectionCoordinator':
    return _AdbConnectionCoordinator(
      self.adb_connect_concurrency,
      self.adb_connect_cooldown,
      self.adb_connect_failure_quarantine,
      self.adb_disconnect_retry_cooldown,
      self.adb_connect_recovery_probe_interval,
      self.adb_connect_recovery_probe_max_interval,
    )

  @cached_class_property
  def adb_path(self):
    return Configuration.adb


class _AdbConnectionCoordinator:

  def __init__(
      self, concurrency, cooldown, failure_quarantine, disconnect_cooldown=None,
      recovery_probe_interval=5, recovery_probe_max_interval=60):
    self.concurrency = concurrency
    self.semaphore = threading.BoundedSemaphore(concurrency)
    self.cooldown = cooldown
    self.disconnect_cooldown = cooldown if disconnect_cooldown is None else disconnect_cooldown
    self.failure_quarantine = failure_quarantine
    self.recovery_probe_interval = recovery_probe_interval
    self.recovery_probe_max_interval = max(
      recovery_probe_interval, recovery_probe_max_interval,
    )
    self._guard = threading.Lock()
    self._endpoint_locks = {}
    self._states = {}
    self._server_metrics = {}
    self._metrics = {
      'tcp_probe_attempts': 0,
      'tcp_probe_successes': 0,
      'tcp_probe_failures': 0,
      'recovery_probe_attempts': 0,
      'recovery_probe_successes': 0,
      'recovery_probe_failures': 0,
      'recovery_probe_skips': 0,
      'connect_attempts': 0,
      'connect_successes': 0,
      'connect_failures': 0,
      'connect_cooldown_skips': 0,
      'connect_cooldown_reuses': 0,
      'disconnect_attempts': 0,
      'disconnect_successes': 0,
      'disconnect_failures': 0,
    }

  @contextmanager
  def endpoint_lock(self, endpoint):
    with self._guard:
      entry = self._endpoint_locks.get(endpoint)
      if entry is None:
        entry = {'lock': threading.Lock(), 'users': 0}
        self._endpoint_locks[endpoint] = entry
      entry['users'] += 1
      lock = entry['lock']
    try:
      with lock:
        yield
    finally:
      with self._guard:
        entry['users'] -= 1
        if entry['users'] == 0 and self._endpoint_locks.get(endpoint) is entry:
          self._endpoint_locks.pop(endpoint, None)

  def in_cooldown(self, endpoint, now):
    with self._guard:
      state = self._states.get(endpoint)
      if not state:
        return False, 0
      remaining = state['retry_after'] - now
      return remaining > 0, max(remaining, 0)

  def in_connect_quarantine(self, endpoint, now):
    with self._guard:
      state = self._states.get(endpoint)
      if not state or state['failures'] <= 0:
        return False
      return state['retry_after'] > now

  def recovery_probe_due(self, endpoint, now):
    with self._guard:
      state = self._states.get(endpoint)
      if not state or state['failures'] <= 0 or state['retry_after'] <= now:
        return False, 0
      remaining = state.get('next_recovery_probe_after', now) - now
      return remaining <= 0, max(remaining, 0)

  # Backward-compatible internal name; connect quarantine is the only
  # quarantine represented by this predicate.
  def in_failure_quarantine(self, endpoint, now):
    return self.in_connect_quarantine(endpoint, now)

  def disconnect_cleanup_due(self, endpoint, now):
    """Return whether an owner should try to remove a stale transport."""
    with self._guard:
      state = self._states.get(endpoint)
      if state is None or state.get('last_disconnect_attempt') is None:
        return True
      if state.get('last_disconnect_ok'):
        return False
      return state.get('disconnect_retry_after', 0) <= now

  def recent_connection_is_usable(self, endpoint, now):
    with self._guard:
      state = self._states.get(endpoint)
      return bool(
        state and state.get('failures') == 0
        and state.get('transport_registered')
        and state.get('retry_after', 0) > now
      )

  def _recovery_probe_delay(self, attempts):
    exponent = min(max(int(attempts), 0), 30)
    return min(
      self.recovery_probe_interval * (2 ** exponent),
      self.recovery_probe_max_interval,
    )

  def record_metric(self, name, endpoint=None):
    with self._guard:
      self._metrics[name] = self._metrics.get(name, 0) + 1
      if endpoint is not None:
        port = adb_server_port_for(endpoint)
        metrics = self._server_metrics.setdefault(port, {})
        metrics[name] = metrics.get(name, 0) + 1

  def record_success(self, endpoint, now, error_code=AdbErrorCode.OK, elapsed_ms=None):
    with self._guard:
      self._states[endpoint] = {
        'last_attempt': now,
        'retry_after': now + self.cooldown,
        'failures': 0,
        'last_error': error_code,
        'last_elapsed_ms': elapsed_ms,
        'server_port': adb_server_port_for(endpoint),
        'transport_registered': True,
        'last_disconnect_attempt': None,
        'disconnect_retry_after': 0,
        'last_disconnect_ok': None,
        'recovery_probe_attempts': 0,
        'next_recovery_probe_after': 0,
        'last_recovery_probe_ok': None,
      }

  def record_failure(self, endpoint, now, error_code=AdbErrorCode.COMMAND_FAILED, elapsed_ms=None):
    with self._guard:
      state = self._states.get(endpoint)
      new_quarantine = bool(
        state is None or state.get('failures', 0) <= 0
        or state.get('retry_after', 0) <= now
      )
      if state is None:
        state = {}
        self._states[endpoint] = state
      if new_quarantine:
        state['recovery_probe_attempts'] = 0
        state['next_recovery_probe_after'] = (
            now + self._recovery_probe_delay(0)
        )
        state['last_recovery_probe_ok'] = None
      else:
        recovery_attempts = state.get('recovery_probe_attempts', 0)
        state['next_recovery_probe_after'] = max(
          state.get('next_recovery_probe_after', 0),
          now + self._recovery_probe_delay(recovery_attempts),
        )
      state['last_attempt'] = now
      state['retry_after'] = now + self.failure_quarantine
      state['failures'] = state.get('failures', 0) + 1
      state['last_error'] = error_code
      state['last_elapsed_ms'] = elapsed_ms
      state['server_port'] = adb_server_port_for(endpoint)
      state['transport_registered'] = False
      return state['failures']

  def record_recovery_probe(self, endpoint, now, succeeded, elapsed_ms=None):
    """Consume one recovery probe slot without clearing connect quarantine."""
    with self._guard:
      state = self._states.get(endpoint)
      if not state or state.get('failures', 0) <= 0:
        return 0, 0
      attempts = state.get('recovery_probe_attempts', 0) + 1
      delay = self._recovery_probe_delay(attempts)
      state['recovery_probe_attempts'] = attempts
      state['next_recovery_probe_after'] = now + delay
      state['last_recovery_probe_ok'] = bool(succeeded)
      state['last_recovery_probe_elapsed_ms'] = elapsed_ms
      return attempts, delay

  def record_transport_disconnect(self, endpoint, now, succeeded):
    with self._guard:
      state = self._states.setdefault(endpoint, {
        'last_attempt': now,
        'retry_after': now,
        'failures': 0,
        'last_error': AdbErrorCode.OK,
        'last_elapsed_ms': None,
        'server_port': adb_server_port_for(endpoint),
        'transport_registered': False,
      })
      state['last_disconnect_attempt'] = now
      state['last_disconnect_ok'] = bool(succeeded)
      state['disconnect_retry_after'] = 0 if succeeded else now + self.disconnect_cooldown
      state['server_port'] = adb_server_port_for(endpoint)
      if succeeded:
        state['transport_registered'] = False

  def has_registered_transport(self, endpoint):
    with self._guard:
      state = self._states.get(endpoint)
      return bool(state and state.get('transport_registered'))

  def mark_transport_disconnected(self, endpoint):
    with self._guard:
      state = self._states.get(endpoint)
      if state is not None:
        state['transport_registered'] = False

  def forget(self, endpoint):
    with self._guard:
      self._states.pop(endpoint, None)

  def snapshot(self, now=None):
    if now is None:
      now = time.monotonic()
    with self._guard:
      endpoints = {
        endpoint: {
          'failures': state['failures'],
          'retry_after': state['retry_after'],
          'quarantined': state['retry_after'] > now and state['failures'] > 0,
          'cooldown_remaining': max(0, state['retry_after'] - now),
          'last_error': state.get('last_error'),
          'last_elapsed_ms': state.get('last_elapsed_ms'),
          'server_port': state.get('server_port', adb_server_port_for(endpoint)),
          'transport_registered': bool(state.get('transport_registered')),
          'last_disconnect_ok': state.get('last_disconnect_ok'),
          'recovery_probe_attempts': state.get('recovery_probe_attempts', 0),
          'recovery_probe_remaining': max(
            0, state.get('next_recovery_probe_after', 0) - now,
          ),
          'last_recovery_probe_ok': state.get('last_recovery_probe_ok'),
          'disconnect_retry_remaining': max(
            0, state.get('disconnect_retry_after', 0) - now,
          ),
        }
        for endpoint, state in self._states.items()
      }
      servers = {}
      for port in AdbConfig.adb_server_ports:
        server_endpoints = [state for state in endpoints.values() if state['server_port'] == port]
        servers[port] = {
          'metrics': dict(self._server_metrics.get(port, {})),
          'endpoint_count': len(server_endpoints),
          'transport_count': sum(
            1 for state in server_endpoints if state['transport_registered']
          ),
          'quarantined_count': sum(1 for state in server_endpoints if state['quarantined']),
        }
      return {
        'metrics': dict(self._metrics),
        'endpoints': endpoints,
        'servers': servers,
        'concurrency_limit': self.concurrency,
      }


def get_adb_connection_health():
  """Return process-local connection metrics and endpoint retry state."""
  return AdbConfig.connection_coordinator.snapshot()


def _adb_disconnect(device_name, timeout=None):
  kwargs = {'timeout': timeout} if timeout is not None else {}
  coordinator = AdbConfig.connection_coordinator
  with coordinator.semaphore:
    coordinator.record_metric('disconnect_attempts', device_name)
    result = run_adb_result("disconnect", device_name, **kwargs)
  coordinator.record_metric(
    'disconnect_successes' if result.ok else 'disconnect_failures', device_name,
  )
  coordinator.record_transport_disconnect(device_name, time.monotonic(), result.ok)
  return result.return_code, result.output


def _connect_response_matches(endpoint, ret_code, response):
  """Accept only the explicit success line emitted by ``adb connect``."""
  if ret_code != 0:
    return False
  if isinstance(response, bytes):
    response = response.decode('utf-8', errors='replace')
  else:
    response = str(response or '')
  success = re.compile(
    r'^(?:connected to|already connected to)\s+' + re.escape(endpoint) + r'$',
    re.IGNORECASE,
  )
  return any(success.fullmatch(line.strip()) for line in response.splitlines())


def _verify_transport(endpoint):
  token = 'albatross_adb_ready'
  result = run_adb_result('shell', f'echo {token}', device_id=endpoint, timeout=default_connect_timeout)
  if not result.ok:
    return result
  return AdbCommandResult(
    result.return_code,
    result.output,
    AdbErrorCode.OK if token in result.output.decode('utf-8', errors='replace').split()
    else AdbErrorCode.COMMAND_FAILED,
    result.elapsed_ms,
  )


def _clear_transport(device_name):
  if not device_name:
    return
  manager = _device_manager
  if manager is not None:
    with manager.endpoint_lock(device_name):
      device = manager.pop_cached_device(device_name)
      if parse_tcp_endpoint(device_name) is not None and not AdbConfig.adb_transport_owner:
        logger.info(f'adb disconnect {device_name} skipped in non-owner process')
        if device is not None:
          try:
            device.prevent_new_forwards()
            ports = device.close_rpc_clients()
            device.cleanup_forwards(ports, timeout=2)
          except Exception:
            logger.exception('failed to clean local resources for %s', device_name)
        return None
      return _clear_cached_transport(device_name, device)
  if parse_tcp_endpoint(device_name) is not None and not AdbConfig.adb_transport_owner:
    logger.info(f'adb disconnect {device_name} skipped in non-owner process')
    return None
  return _clear_cached_transport(device_name, None)


def _clear_cached_transport(device_name, device):
  ports = set()
  if device is not None:
    try:
      device.prevent_new_forwards()
      # Close local sockets and suppress their callbacks before adb-server
      # tears down the transport. This step deliberately issues no adb command.
      ports = device.close_rpc_clients()
    except Exception:
      ports = set(getattr(device, '_owned_forward_ports', set()))
  # A failed TCP transport must leave adb-server before any best-effort forward
  # cleanup can issue another device-scoped adb command.
  disconnect_ok = False
  try:
    disconnect_result = _adb_disconnect(device_name, timeout=default_connect_timeout)
    ret_code = disconnect_result[0] if isinstance(disconnect_result, tuple) else 0
    disconnect_ok = ret_code == 0
  except Exception:
    logger.info(f'adb disconnect {device_name} cleanup failed')
  if device is None:
    return disconnect_ok
  try:
    device.cleanup_forwards(ports, timeout=2)
  except Exception:
    logger.info(f'known forward cleanup for {device_name} failed')
  return disconnect_ok


def _record_disconnect_outcome(endpoint, disconnected):
  if disconnected:
    AdbConfig.connection_coordinator.forget(endpoint)
  else:
    AdbConfig.connection_coordinator.record_failure(
      endpoint, time.monotonic(), AdbErrorCode.DISCONNECT_FAILED,
    )


def try_connect(device_name, try_time=2):
  # Kept for API compatibility.  A connection attempt is deliberately one-shot
  # to avoid multiplying adb transport churn in callers that pass try_time > 1.
  del try_time
  endpoint = str(device_name).strip()
  adb_connect_enabled = AdbConfig.adb_connect_enabled
  if not endpoint or not adb_connect_enabled:
    if endpoint and not adb_connect_enabled:
      logger.info(f'adb connect {endpoint} disabled in this process')
    return False
  coordinator = AdbConfig.connection_coordinator
  with coordinator.endpoint_lock(endpoint):
    now = time.monotonic()
    cooling_down, remaining = coordinator.in_cooldown(endpoint, now)
    if cooling_down:
      if coordinator.recent_connection_is_usable(endpoint, now):
        coordinator.record_metric('connect_cooldown_reuses', endpoint)
        logger.info(f'adb connect {endpoint} reused recent connection ({remaining:.1f}s remaining)')
        return True

      if not coordinator.in_connect_quarantine(endpoint, now):
        coordinator.record_metric('connect_cooldown_skips', endpoint)
        logger.info(f'adb connect {endpoint} skipped during cooldown ({remaining:.1f}s remaining)')
        return False

      recovery_due, probe_remaining = coordinator.recovery_probe_due(endpoint, now)
      if (not AdbConfig.adb_tcp_probe_enabled
          or parse_tcp_endpoint(endpoint) is None
          or not recovery_due):
        coordinator.record_metric('connect_cooldown_skips', endpoint)
        coordinator.record_metric('recovery_probe_skips', endpoint)
        logger.info(
          f'adb connect {endpoint} remains quarantined '
          f'({remaining:.1f}s quarantine, {probe_remaining:.1f}s recovery probe)'
        )
        return False
      recovery_probe = True
    else:
      recovery_probe = False

    if AdbConfig.adb_tcp_probe_enabled:
      probe_started = time.monotonic()
      tcp_open = probe_tcp_endpoint(endpoint, AdbConfig.adb_tcp_probe_timeout)
      probe_elapsed_ms = (time.monotonic() - probe_started) * 1000
      if tcp_open is not None:
        coordinator.record_metric('tcp_probe_attempts', endpoint)
        coordinator.record_metric(
          'tcp_probe_successes' if tcp_open else 'tcp_probe_failures', endpoint,
        )
      if recovery_probe:
        coordinator.record_metric('recovery_probe_attempts', endpoint)
        coordinator.record_metric(
          'recovery_probe_successes' if tcp_open else 'recovery_probe_failures', endpoint,
        )
        attempts, delay = coordinator.record_recovery_probe(
          endpoint, time.monotonic(), tcp_open is True, probe_elapsed_ms,
        )
        if tcp_open is not True:
          logger.info(
            f'adb connect {endpoint} remains quarantined: recovery TCP probe failed '
            f'(attempt {attempts}, next probe in {delay:.1f}s)'
          )
          return False
      if tcp_open is False:
        failures = coordinator.record_failure(
          endpoint, time.monotonic(), AdbErrorCode.TCP_UNREACHABLE, probe_elapsed_ms,
        )
        logger.info(
          f'adb connect {endpoint} skipped: TCP probe failed '
          f'({failures} consecutive failures); '
          f'quarantined for {coordinator.failure_quarantine:.0f}s'
        )
        if AdbConfig.adb_transport_owner:
          _clear_transport(endpoint)
        return False

    with coordinator.semaphore:
      coordinator.record_metric('connect_attempts', endpoint)
      connect_result = run_adb_result("connect", endpoint, timeout=default_connect_timeout)
      connected = _connect_response_matches(
        endpoint, connect_result.return_code, connect_result.output,
      )
      verification = _verify_transport(endpoint) if connected else None
      verified = connected and verification.ok

    now = time.monotonic()
    if connected and verified:
      coordinator.record_success(
        endpoint, now, elapsed_ms=connect_result.elapsed_ms + verification.elapsed_ms,
      )
      coordinator.record_metric('connect_successes', endpoint)
      return True

    error_code = (
      (connect_result.error_code if connect_result.error_code != AdbErrorCode.OK
       else AdbErrorCode.COMMAND_FAILED)
      if not connected else verification.error_code
    )
    elapsed_ms = connect_result.elapsed_ms + (verification.elapsed_ms if verification else 0)
    failures = coordinator.record_failure(endpoint, now, error_code, elapsed_ms)
    coordinator.record_metric('connect_failures', endpoint)
    reason = 'connect response' if not connected else 'transport verification'
    logger.info(
      f'adb connect {endpoint} failed during {reason} error={error_code} '
      f'({failures} consecutive failures); '
      f'quarantined for {coordinator.failure_quarantine:.0f}s'
    )
    _clear_transport(endpoint)
    return False


def disconnect(device_name):
  endpoint = str(device_name).strip()
  if not endpoint:
    return
  device = _device_manager.get_cached_device(endpoint) if _device_manager is not None else None
  if device is not None:
    logger.info(f'disconnect cached device and clean known forwards: {endpoint}')
  disconnected = _clear_transport(endpoint)
  if disconnected is not None:
    _record_disconnect_outcome(endpoint, disconnected)
  return bool(disconnected)


default_try_time = 3
default_timeout = 2


def probe_device_alive(device_name, try_time=None):
  if not try_time:
    try_time = default_try_time
  if parse_tcp_endpoint(device_name) is not None:
    timeout = min(default_timeout * 2, 10)
  else:
    timeout = default_timeout
  last_result = None
  for i in range(try_time):
    last_result = run_adb_result("shell", "echo ping", device_id=device_name, timeout=timeout)
    if last_result.ok and last_result.output.startswith(b'ping'):
      return True, last_result
    if i < try_time - 1:
      time.sleep(0.5)
  return False, last_result


def check_device_alive(device_name, try_time=None):
  return probe_device_alive(device_name, try_time)[0]


def invalidate_device_health(device_name, reason='device_event'):
  manager = _device_manager
  if manager is not None:
    manager.invalidate_health(device_name, reason)


def file_md5(file_path):
  md5 = hashlib.md5()
  try:
    with open(file_path, 'rb') as f:
      while chunk := f.read(8192):
        md5.update(chunk)
    return md5.hexdigest()
  except IOError as e:
    return None


pkg_pattern = re.compile(r"package:([\w.]+)(?:\s+|$)")

resume_activity_pattern = re.compile(r"mResumedActivity: ActivityRecord{\w+\s\w+\s([\w\.]+/[\w\.$]+)")


class AlbatrossDevice(object):
  anti_detection = False
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
  load_kpm_impl = None
  support_kpm = False

  @cached_class_property
  def adb(self):
    return Configuration.adb

  def __init__(self, device_id):
    self.device_id = device_id
    self._owned_forward_ports = set()
    self._forward_lock = threading.RLock()
    self._forward_closed = False
    self._set_adb_transport(device_id)
    self.process_launch_callback = {}
    self.app_launch_count = {}
    endpoint = parse_tcp_endpoint(device_id)
    self.usb_mode = endpoint is None
    if endpoint is not None:
      self.usb_mode = False
      self.connect_ip, self.tcp_port = endpoint
    else:
      if AlbatrossDevice.cached_ip:
        self.connect_ip = self.get_device_ip()
        port = self.getprop('service.adb.tcp.port')
        if port:
          self.tcp_port = int(port)

  def _set_adb_transport(self, device_id, server_port=None):
    if server_port is None:
      server_port = adb_server_port_for(device_id)
    self.adb_device_id = device_id
    self.adb_server_port = server_port
    prefix = [AdbConfig.adb_path, '-P', str(server_port), '-s', device_id]
    self.cmd = ' '.join(prefix) + ' '
    self.shellcmd_list = prefix + ['shell']
    self.shellcmd = ' '.join(self.shellcmd_list) + ' '

  @cached_property
  def mount_paths(self):
    return {}

  def shell(self, cmd, timeout=None, su_cmd=False, return_code=False) -> list | str | tuple:
    start_time = time.time()
    for i in range(4):
      shell_prefix = self.shellcmd_list
      if su_cmd:
        if sys.platform == 'win32' or "'" not in cmd:
          command = shell_prefix + [f"{self.su_file} -c '{cmd}'"]
        else:
          # command = shell_prefix + "'{} -c \"".format(self.su_file) + cmd + "\"'"
          # command = f"{self.shellcmd} {self.su_file} -c \"{cmd}\""
          cmd = cmd.replace('"', '\\"')
          command = shell_prefix + [f"{self.su_file} -c \"{cmd}\""]
      else:
        command = shell_prefix + [cmd]
      if timeout:
        ret = run_shell(command, timeout=timeout, shell=False)
      else:
        ret = run_shell(command, shell=False)
      ret_code = ret[0]
      result = ret[1].decode().strip()
      if 'not found' in result:
        transport_id = getattr(self, 'adb_device_id', self.device_id)
        if f"device '{transport_id}' not found" in result:
          if i < 1:
            continue
          if i < 2:
            time.sleep(0.2)
            continue
          invalidate_device_health(self.device_id, 'device_not_found')
          raise DeviceOffline(self)
      elif 'error: device offline' in result:
        invalidate_device_health(self.device_id, 'device_offline')
        raise DeviceOffline(self)
      end_time = time.time()
      cost = end_time - start_time
      if cost > 10:
        logger.info(f'device {self.device_id} run {cmd[:32]} cost {cost}s')
      if return_code:
        return ret_code, result
      self.ret_code = ret_code
      return result

    raise DeviceOffline(self)

  @cached_property
  def serial_no(self):
    return self.get_serial()

  def get_serial(self):
    device_id = self.device_id
    if parse_tcp_endpoint(device_id) is None:
      return device_id
    return self.getprop('ro.serialno')

  def device_alive(self, try_time=2):
    if self.usb_mode:
      return check_device_alive(self.device_id, try_time)
    return check_device_alive(self.get_connect_device_id(), try_time)

  # ime_server=pkg/class
  def set_ime(self, ime_service, enable=True):
    if enable:
      self.root_shell(f"ime enable {ime_service} && ime set {ime_service}")
    else:
      self.root_shell("ime disable " + ime_service)

  @property
  def is_screen_on(self):
    for i in range(3):
      ret_str = self.run_as_shell("dumpsys power | grep -E 'mWakefulness=|Display Power'")
      if 'Error' in ret_str:
        if "Can't find service" in ret_str:
          return None
        return True
      if 'mWakefulness=' in ret_str:
        return 'mWakefulness=Awake' in ret_str
      match = re.search(r"Display Power: state=(\w+)", ret_str)
      if not match:
        continue
      return match.group(1) == 'ON'
    self.reboot('power service dead')
    raise DeviceReboot(f'device {self.device_id} power dead')

  def wake_up(self):
    ret = self.is_screen_on
    if not ret:
      if ret is None:
        self.reboot('power service dead')
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
    self.shell('input keyevent 4')

  reboot_callback = None

  def reboot(self, reason=None, wait_time=0):
    try:
      time_id = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
      if reason:
        logger.info(f'reboot device {self.device_id} by {reason}, wait {wait_time}')
        self.shell(f"echo '{time_id} {reason} {wait_time}' >> /data/local/tmp/reboot")
      else:
        self.shell(f"echo '{time_id} {wait_time}' >> /data/local/tmp/reboot")
    except:
      pass
    if self.reboot_callback:
      try:
        self.reboot_callback(self, reason)
      except:
        pass
    self.adb_cmd('reboot')
    if wait_time > 0:
      time.sleep(wait_time)

  def screen_size(self, size=None):
    if size is None:
      lines: str = self.shell("wm size")
      lines = lines.rsplit(':', maxsplit=1)[-1]
      width, height = re.findall("(\\d+)", lines)
      return int(width), int(height)
    else:
      return self.shell('wm size ' + size)

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

  def swipe(self, x1, y1, x2, y2, t=None):
    cmd = "input swipe {} {} {} {}".format(int(x1), int(y1), int(x2), int(y2))
    if t:
      cmd += " {}".format(t)
    return self.shell(cmd)

  def swipe_to(self, direction='up'):
    dirdict = self.swipe_direction
    return self.swipe(*dirdict[direction])

  def check_alive(self):
    if not self.device_alive(2 if self.usb_mode else 3):
      raise DeviceOffline(self.device_id)
    return True

  def adb_cmd(self, *args, **kwargs):
    device_id = self.adb_device_id
    server_port = getattr(self, 'adb_server_port', adb_server_port_for(device_id))
    return run_adb(*args, device_id=device_id, server_port=server_port, **kwargs)

  def forward_list(self, timeout=10):
    ret_code, output = self.adb_cmd("forward", "--list", timeout=timeout)
    if ret_code != 0:
      return []
    ports = []
    for line in output.decode("utf-8", errors="replace").strip().splitlines():
      fields = line.strip().split()
      if len(fields) != 3:
        continue
      s, l, r = fields
      if s == getattr(self, 'adb_device_id', self.device_id):
        ports.append([s, l, r])
    return ports

  def forward(self, local_port, remote, tcp=True, keep=False):
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      if getattr(self, '_forward_closed', False):
        raise RuntimeError(f'device {self.device_id} is closed')
      if tcp:
        local = "tcp:%d" % local_port
      else:
        local = "udp:%d" % local_port
      ret_code, _ = self.adb_cmd("forward", local, remote)
      if ret_code == 0 and not keep:
        self._owned_forward_ports.add(local_port)
      return ret_code

  def connect(self):
    return try_connect(self.device_id)

  def is_online(self):
    server_port = getattr(self, 'adb_server_port', adb_server_port_for(self.device_id))
    devices = list_devices(server_port=server_port)[1]
    return getattr(self, 'adb_device_id', self.device_id) in devices

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
    try:
      result = self.shell(cmd, timeout)
      return result
    finally:
      if on:
        try:
          self.setenforce(True)
        except:
          pass

  run_as_shell = shell

  def is_shell_root(self):
    touch_result = self.su_shell("touch /data/local/file_test")
    if 'inaccessible' in touch_result:
      return False
    is_not_root = "Permission" in touch_result
    remove_result = self.su_shell("rm /data/local/file_test")
    ret = "Permission" not in remove_result
    return ret

  @cached_property
  def su_file(self):
    su_file = self.shell('which su')
    if su_file:
      return su_file
    for i in ["/system/bin/su", "/system/xbin/su", "/sbin/su", "/system/su", "/system/bin/.ext/su",
      "/system/usr/we-need-root/su", "/data/local/xbin/su", "/data/local/bin/su", "/data/local/su"]:
      ret_code, _ = self.shell('ls ' + i, return_code=True)
      if ret_code == 0:
        return i
    return 'su'

  def check_is_root(self):
    adb_root = self.is_adb_root()
    if adb_root:
      self.shell_user = 'root'
      self.root_shell = self.shell
      if self.sdk_version >= 34:
        self.run_as_shell = self.switch_shell_run
      return True
    shell_root = self.is_shell_root()
    if shell_root:
      self.root_shell = self.su_shell
    return shell_root

  @cached_property
  def is_root(self):
    return self.check_is_root()

  def getprop(self, prop):
    return self.shell(f'getprop {prop}')

  @cached_property
  def debuggable(self):
    return self.shell('getprop ro.debuggable') == '1'

  @cached_property
  def magisk_install_cmd(self):
    res = self.root_shell('which apd')
    if res:
      return 'apd module install'
    else:
      res = self.root_shell('which ksud')
      if res:
        return 'ksud module install'
      return 'magisk --install-module'

  def is_vpn_on(self):
    return 'encap' in self.shell('ifconfig | grep tun0')

  app_agent_updated = False

  @cached_property
  def device_config_path(self):
    device_dir = Configuration.config_dir + "device/"
    os.makedirs(device_dir, exist_ok=True)
    return device_dir + f"device_{self.serial_no}_config.json"

  def save_device_data(self, key, value):
    if 'data' not in self.device_config:
      self.device_config['data'] = {key: value}
      self.update_count += 1
    else:
      old = self.device_config.get('data', {}).get(key)
      if old != value:
        self.device_config['data'][key] = value
        self.update_count += 1

  def pop_device_data(self, key):
    if 'data' in self.device_config:
      data = self.device_config.get('data', {})
      if key in data:
        data.pop(key, None)
        self.update_count += 1

  def reload_data(self):
    cached_property.delete(self, 'device_config')

  def get_device_data(self, key, def_value=None):
    return self.device_config.get('data', {}).get(key, def_value)

  def get_temp_data(self, data_key, def_value=None):
    file_path = f'/data/local/tmp/key_{data_key}'
    try:
      res = self.shell(f'cat {file_path}', timeout=10)
    except:
      return def_value
    if 'No such' in res:
      return def_value
    return res.strip()

  def save_temp_data(self, data_key, value):
    file_path = f'/data/local/tmp/key_{data_key}'
    try:
      self.shell(f'echo {value} > {file_path}', timeout=10)
    except:
      pass

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
        try:
          device_config = json.load(fp)
        except:
          device_config = {}
    else:
      device_config = {}
    if not device_config:
      lib_name = 'lib' + generate_random_variable_name(min_length=2, max_length=5) + '.so'
      app_agent_name = 'framework-' + generate_random_variable_name(min_length=2, max_length=6) + '.jar'
      device_config = {'lib_name': lib_name, 'app_agent_name': app_agent_name,
        'server_port': 'localabstract:' + generate_random_variable_name(min_length=2,
          max_length=8), 'dex_maps': {}, 'data': {}, 'server_port_num': 6000 + random.randint(0, 2000)}
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
    res = self.push_file(Configuration.app_agent_file, dst, mode='444', file_type=self.file_type, check=True)
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

  def push_file(self, file, dst, check=False, mode=None, file_type=None, owner=None, timeout=120):
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
    # command = self.cmd + ' push "{}" "{}"'.format(file, dst)
    ret_code, s = self.adb_cmd('push', file, dst, timeout=timeout)
    res = ret_code == 0
    if res:
      if extra_cmds:
        self.root_shell(';'.join(extra_cmds))
      logger.info(s)
      return res
    elif b'pushed' in s:
      new_md5 = self.get_file_md5(dst)
      if new_md5 == md5_dst:
        return True
    if self.is_root and self.shell_user == 'shell':
      tmp_path = '/data/local/tmp/' + md5_dst
      # command = self.cmd + ' push "{}" "{}"'.format(file, tmp_path)
      ret_code, s = self.adb_cmd('push', file, tmp_path, timeout=120)
      res = ret_code == 0
      if res:
        command = self.root_shell(f'mkdir -p {os.path.dirname(dst)} && mv {tmp_path} {dst}')
        if not command:
          logger.info(s)
          if extra_cmds:
            self.root_shell(';'.join(extra_cmds))
          return True
    return False

  def pidofs(self, cmd_line):
    pids = []
    ret_code, ret = self.shell(f'ps -ef | grep "{cmd_line}"')
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

  def kill_process(self, process, reason=None, reboot_count: int = 0):
    pids = self.pidof(process)
    if pids:
      if reboot_count and len(pids) >= reboot_count:
        self.reboot(f'{self.device_id} find much process {process}:{pids}')
        return
      for pid in pids:
        self.kill_pid(pid)
      if not reason:
        logger.info(f'{self.device_id} kill {process} {pids}')
      else:
        logger.info(f'{self.device_id} kill {process}:{pids} by {reason}')
    return pids

  def kill_pid(self, pid, sig=9):
    if pid:
      self.root_shell(f"kill -{sig} {pid}")

  def __on_close(self, client):
    cached_property.delete(self, 'client')
    self._remove_forward_if_unused(getattr(client, 'port', None))
    invalidate_device_health(self.device_id, 'rpc_client_closed')
    logger.info('albatross server disconnected')

  def _remove_forward_if_unused(self, port, timeout=10):
    if port is None or getattr(self, '_closing', False):
      return False
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      if port not in self._owned_forward_ports:
        return False
      for attr in ('client', 'system_server_client', 'system_server_subscriber'):
        other = cached_property.get(self, attr)
        if other is cached_property.nil_value or other is None:
          continue
        if getattr(other, 'port', None) == port and getattr(other, 'sock', None):
          return False
      return self.remove_forward_port(port, timeout=timeout)

  def _cleanup_failed_forward(self, port, reason):
    try:
      removed = self._remove_forward_if_unused(port, timeout=2)
      if removed:
        logger.info('removed unused forward tcp:%s after %s on %s', port, reason, self.device_id)
    except Exception:
      logger.warning('failed to remove forward tcp:%s after %s on %s', port, reason, self.device_id)

  def close_rpc_clients(self):
    """Close cached local sockets without issuing device-scoped adb commands."""
    self.reconnect = False
    self._closing = True
    cached_clients = []
    for attr in ('system_server_subscriber', 'system_server_client', 'client'):
      client = cached_property.pop(self, attr)
      if client is not cached_property.nil_value and client is not None:
        cached_clients.append(client)
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      ports = set(self._owned_forward_ports)
    try:
      for client in cached_clients:
        port = getattr(client, 'port', None)
        if port is not None:
          ports.add(port)
        callbacks = getattr(client, 'on_close_callbacks', None)
        if isinstance(callbacks, dict):
          callbacks.clear()
        try:
          client.shutdown()
        except Exception:
          try:
            client.close()
          except Exception:
            pass
    finally:
      self._closing = False
    return ports

  def cleanup_forwards(self, ports=None, timeout=None):
    """Best-effort cleanup for forwards whose local ports are already known."""
    ports = set(self._owned_forward_ports if ports is None else ports)
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      for port in ports:
        try:
          if timeout is None:
            removed = self.remove_forward_port(port)
          else:
            removed = self.remove_forward_port(port, timeout=timeout)
          if removed is not False:
            try:
              owned_port = port if isinstance(port, int) else int(str(port).split(':', 1)[1])
              self._owned_forward_ports.discard(owned_port)
            except (TypeError, ValueError, IndexError):
              pass
        except Exception:
          # remove_forward_port deliberately keeps failed ports owned. Keep
          # cleanup best-effort so one bad transport does not block others.
          continue

  def prevent_new_forwards(self):
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      self._forward_closed = True

  def is_closed(self):
    return self._forward_closed

  def close(self):
    """Close cached RPC clients and remove all forwards owned by this device."""
    self.prevent_new_forwards()
    ports = self.close_rpc_clients()
    self.cleanup_forwards(ports)
    try:
      self.remove_albatross_port()
    except Exception:
      pass

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

  @cached_property
  def copy_script(self):
    file_path = os.path.dirname(__file__) + "/copy_with_selinux.sh"
    dst = '/data/local/tmp/copy_with_selinux.sh'
    self.push_file(file_path, dst, mode=700, owner='root')
    return dst

  def get_battery_level(self):
    result = self.shell('dumpsys battery | grep level')
    return int(result.split(':')[1])

  def kill_client(self, reason=None):
    self.kill_process(os.path.basename(Configuration.server_dst_path), reason)

  albatross_client_impl = AlbatrossClient
  enable_kpm = True
  hide_file = False

  def get_client(self) -> AlbatrossClient:
    if not self.is_root:
      raise DeviceNotRoot(self)
    server_dst_basename = Configuration.server_dst_path
    server_dst_path = '/data/local/tmp/' + server_dst_basename
    server_port = Configuration.server_port
    if server_port == 'random':
      # res = re.findall(r'albatross_server (\w+)', self.shell('ps -ef | grep albatross_server'))
      # if res and res[0] and len(res) < 16:
      #   server_port = 'localabstract:' + res[0]
      # else:
      server_port = self.device_config.get('server_port', 'localabstract:albatross_manager')
    if self.usb_mode or not os.environ.get('ALBATROSS_SOCKET_CONNECT'):
      # Allocate the forward only after the device files and libraries have
      # been prepared; failures in those steps must not leave a stale rule.
      local_port = None
      host = '127.0.0.1'
    else:
      host = self.connect_ip
      try:
        server_port = int(server_port)
      except:
        pids = self.root_shell('ps -ef | grep ' + server_port.split(':')[-1])
        if pids and server_dst_basename in pids:
          pids = pids.splitlines()
          for pid in pids:
            if server_dst_basename not in pid:
              continue
            pid = pid.split()[1]
            self.kill_pid(pid)
            logger.info(f'kill {self.device_id} old client {server_port}')
        server_port = self.device_config.get('server_port_num', 7000)
      local_port = server_port
    device_abi = self.cpu_abi
    server_file, abi_lib, abi_lib32 = Configuration.get_server_path(device_abi)
    assert os.path.exists(server_file), server_file
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

    if local_port is None:
      local_port = self.get_forward_port(server_port)
      if local_port is None:
        raise RuntimeError(f'failed to allocate adb forward for {self.device_id}')

    def sync_lib():
      if self.anti_detection:
        if not self.enable_kpm:
          support_kpm = False
        else:
          support_kpm = client.support_extend_kpm()
          if not support_kpm and self.load_kpm_impl:
            try:
              self.load_kpm_impl(self, client)
              support_kpm = client.support_extend_kpm()
            except:
              pass
        self.support_kpm = support_kpm
        if self.sdk_version >= 29 and not support_kpm and self.hide_file:
          owner = 'root'
          lib_file_type = 'system_lib_file'
          jar_file_type = 'system_file'
          ori_file_md5 = self.get_file_md5(app_lib_dst)
          mount_path_dirs = ['/system_ext/', '/system/product/', '/vendor/']
          mount_path_dir = None
          libs = []
          for m_dir in mount_path_dirs:
            ret_code, ret_str = self.shell('ls -al ' + m_dir, return_code=True)
            if ret_code == 0:
              exists = []
              for i in ['lib64', 'lib']:
                ret_code, ret_str = self.shell('ls -Zd ' + m_dir + i, return_code=True)
                if ret_code != 0:
                  continue
                res = re.findall('u:object_r:(\\w+):s0', ret_str)
                exists.append(i)
                if res:
                  lib_file_type = res[0]
                  break
              if exists:
                ret_code, ret_str = self.shell('ls -Zd ' + m_dir + 'framework', return_code=True)
                if ret_code == 0:
                  res = re.findall('u:object_r:(\\w+):s0', ret_str)
                  if res:
                    jar_file_type = res[0]
                    if len(res) < 10:
                      libs.append('framework')
                  else:
                    libs.append('framework')
                mount_path_dir = m_dir
                break
          else:
            if Configuration.mount_path.startswith('/data/'):
              mount_path_dir = Configuration.mount_path
            owner = 'system'
          if mount_path_dir:
            use_nsenter = '/system/' in mount_path_dir or '/vendor/' in mount_path_dir
            # use_nsenter = True
            # if 'vendor' in mount_path_dir:
            #   lib_file_type = 'vendor_file'
            #   jar_file_type = 'vendor_framework_file'
            cmds = []
            new_lib_dst_32 = None
            if '64' in self.cpu_abi:
              libs.append('lib64')
              new_app_lib_dst = mount_path_dir + 'lib64/' + lib_name
              if lib_dst_32:
                new_lib_dst_32 = mount_path_dir + 'lib/' + lib_name
                libs.append('lib')
            else:
              new_app_lib_dst = mount_path_dir + 'lib/' + lib_name
              libs.append('lib')

            agent_dex = self.agent_dex
            dex_lib_dir = mount_path_dir + "framework/"
            new_agent_dex = dex_lib_dir + os.path.basename(agent_dex)

            def check_file():
              new_file_md5 = self.get_file_md5(new_app_lib_dst)
              dirname = os.path.dirname(new_app_lib_dst)
              if ori_file_md5 == new_file_md5:
                self.lib_dst = new_app_lib_dst
                self.mount_paths[dirname] = True
                self.lib_dir = dirname + "/"
              elif self.push_file(abi_lib, new_app_lib_dst, mode='644', file_type=lib_file_type, owner=owner):
                self.lib_dst = new_app_lib_dst
                self.mount_paths[dirname] = True
                self.lib_dir = dirname + "/"
              if lib_dst_32:
                path_dir = os.path.dirname(new_lib_dst_32)
                if self.get_file_md5(lib_dst_32) == self.get_file_md5(new_lib_dst_32):
                  self.lib32_dst = new_lib_dst_32
                  self.lib32_dir = path_dir + "/"
                  self.mount_paths[path_dir] = True
                elif self.push_file(lib_src_32, new_lib_dst_32, mode='644', file_type=lib_file_type, owner=owner):
                  self.lib32_dst = new_lib_dst_32
                  self.lib32_dir = path_dir + "/"
                  self.mount_paths[path_dir] = True
              self.push_file(Configuration.app_agent_file, new_agent_dex, mode='644', file_type=jar_file_type,
                owner=owner)
              if self.get_file_md5(agent_dex) == self.get_file_md5(new_agent_dex):
                Configuration.app_plugin_home = dex_lib_dir
                cached_property.reset(self, 'agent_dex', new_agent_dex)
                jar_dir = dex_lib_dir[:-1]
                self.mount_paths[jar_dir] = True

            new_file_md5 = self.get_file_md5(new_app_lib_dst)
            if not new_file_md5:
              self.push_file(abi_lib, new_app_lib_dst, mode='644', file_type=lib_file_type, owner=owner)
              new_file_md5 = self.get_file_md5(new_app_lib_dst)
            if new_file_md5:
              check_file()
            else:
              use_mount = not mount_path_dir.startswith('/data/') and not new_file_md5
              if not use_mount:
                cmds.append('mkdir -p ' + mount_path_dir)
              cp_command = self.copy_script
              # cmds.append('mount -t tmpfs -o size=512M,mode=0755,exec,dev,suid  tmpfs ' + new_lib_dir)
              for i in libs:
                dst_dir = mount_path_dir + i
                if use_mount:
                  tmp_dir = '/data/local/tmp/albatross/' + i + '/'
                  cmds.append(f'rm -rf {tmp_dir} && mkdir -p ' + tmp_dir)
                  staged_agent = None
                  if i == 'lib64':
                    staged_agent = tmp_dir + lib_name
                    cmds.append(f'cp {app_lib_dst} {tmp_dir}')
                    cmds.append(f'chcon  u:object_r:{lib_file_type}:s0 {staged_agent}')
                  elif i == 'lib':
                    if lib_dst_32:
                      staged_agent = tmp_dir + lib_name
                      cmds.append(f'cp {lib_dst_32} {tmp_dir}')
                      cmds.append(f'chcon  u:object_r:{lib_file_type}:s0 {staged_agent}')
                  else:
                    staged_agent = tmp_dir + os.path.basename(agent_dex)
                    cmds.append(f'cp {agent_dex} {tmp_dir}')
                    cmds.append(f'chcon  u:object_r:{jar_file_type}:s0 {staged_agent}')
                  # 把原始目录内容(含 oplus-framework-res.apk 等系统文件)连同各自的 SELinux 上下文复制进暂存目录
                  cmds.append(f'{cp_command} {dst_dir} {tmp_dir[:-1]}')
                  # 只对新加入的 agent 文件设置属主/权限，原始文件保持 copy_with_selinux 复制时的原状
                  if staged_agent:
                    cmds.append(f'chown {owner}:{owner} {staged_agent}')
                    cmds.append(f'chmod 644 {staged_agent}')
                  # bind 不改变 inode 的 SELinux 标签：bind 后该目录沿用它在 /data 下创建时的默认标签
                  # (如 shell_data_file)，zygote 等域对这种类型的目录没有 dir{search} 权限，会读不到目录内的
                  # 框架资源而崩溃。copy_with_selinux 只为目录内的文件/子目录恢复了上下文，遗漏了顶层目录本身，
                  # 这里按原始系统目录的类型(framework→jar_file_type，lib→lib_file_type)补上顶层目录的上下文。
                  dir_file_type = lib_file_type if 'lib' in i else jar_file_type
                  cmds.append(f'chcon u:object_r:{dir_file_type}:s0 {tmp_dir[:-1]}')
                  if use_nsenter:
                    # if 'lib' in i:
                    #   cmds.append(f'chcon -R u:object_r:{lib_file_type}:s0 {tmp_dir}*')
                    # else:
                    #   cmds.append(f'chcon -R u:object_r:{jar_file_type}:s0 {tmp_dir}*')
                    # cmds.append(f'chown -R {owner}:{owner} {tmp_dir}*')
                    # cmds.append(f'chmod -R 644  {tmp_dir}*')
                    cmds.append(f'for daemon in zygote zygote64 adbd; '
                                f'do pids=$(pidof "$daemon") || continue; '
                                f'for z in $pids; '
                                f'do echo "proc:$z"; '
                                f'nsenter --mount=/proc/"$z"/ns/mnt --  /bin/mount --bind {tmp_dir}  {dst_dir}; '
                                f'done; '
                                f'done')
                    cmds.append('wait')
                    if 'lib' in i:
                      cmds.append(f'chcon  u:object_r:{lib_file_type}:s0 {dst_dir}')
                    else:
                      cmds.append(f'chcon  u:object_r:{jar_file_type}:s0 {dst_dir}')
                    # cmds.append('sleep 1')
                  else:
                    # 暂存目录此时已是“原始内容 + agent”的完整副本，直接整体 bind 到目标，
                    # 一步原子替换：替换前 dst 仍是完整的原始系统目录、替换后立刻是完整副本，
                    # 不存在原先“先挂空 tmpfs，再 mv/chmod -R/chcon -R 慢慢填”过程中
                    # zygote fork 读不到 oplus-framework-res.apk 而 ENOENT 致命的空窗。
                    # 权限与 SELinux 上下文已在暂存目录里按文件设好，这里不再对目标做 -R 递归修改
                    # (避免 chmod -R 644 抹掉子目录可进入位、chcon -R 覆盖原始文件标签)。
                    cmds.append(f'mkdir -p {dst_dir}')
                    cmds.append(f'mount --bind {tmp_dir[:-1]} {dst_dir}')
                else:
                  cmds.append('mkdir -p ' + dst_dir)
                  if i == 'lib64':
                    cmds.append(f'cp {app_lib_dst} {dst_dir}')
                    cmds.append(f'chcon -R u:object_r:{lib_file_type}:s0 {dst_dir}')
                  elif i == 'lib':
                    if lib_dst_32:
                      cmds.append(f'cp {lib_dst_32} {dst_dir}')
                      cmds.append(f'chcon -R u:object_r:{lib_file_type}:s0 {dst_dir}')
                  else:
                    cmds.append(f'cp {self.agent_dex} {dst_dir}')
                    cmds.append(f'chcon -R u:object_r:{jar_file_type}:s0 {dst_dir}')
                  cmds.append(f'chown -R {owner}:{owner} {dst_dir}/*')
                  cmds.append(f'chmod 644  {dst_dir}/*')
              # if use_nsenter:
              #   cmds.append(f'chcon  u:object_r:{jar_file_type}:s0 {new_agent_dex}')
              cmds.append('wait')
              cmds.append('echo finish bind')
              shell_command = ' && '.join(cmds)
              script_tmp = tempfile.gettempdir() + '/bind.sh'
              with open(script_tmp, 'w') as fp:
                fp.write(shell_command)
              self.push_file(script_tmp, '/data/local/tmp/script.sh', mode='700')
              res = self.root_shell('/data/local/tmp/script.sh', timeout=120)
              # os.remove(script_tmp)
              time.sleep(1)
              check_file()
      client.set_arch_lib(self.lib_dst)
      if lib_dst_32:
        client.set_2nd_arch_lib(self.lib32_dst)

    if update and self.update_kill:
      self.kill_process(server_dst_basename, 'update lib', reboot_count=5)
    else:
      client = None
      try:
        client = self.albatross_client_impl(local_port, host, 'albatross-' + device_id, 1500)
        sync_lib()
        return client
      except Exception as e:
        if client is not None:
          client.close()
        old_pids = self.kill_process(server_dst_basename, 'connect fail:' + str(e), reboot_count=5)
        if old_pids:
          pids = self.pidof(server_dst_basename)
          if pids and old_pids == pids:
            self._cleanup_failed_forward(local_port, 'server restart failure')
            self.reboot('kill albatross server fail')
            raise DeviceReboot(f'device {self.device_id} kill server fail')
    if type(server_port) == str and server_port.startswith('localabstract:'):
      server_port = server_port.split(':')[1]
    if self.shell_user == 'shell':
      cmd_prefix = "nohup su -c "
      if sys.platform == 'win32':
        cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dir} {cmd_prefix} \'{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &\'"'
      else:
        cmd = f'{self.shellcmd} \'LD_LIBRARY_PATH={lib_dir} {cmd_prefix} "{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"\''
      server_command = f'{server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &'
      remote_command = f"LD_LIBRARY_PATH={lib_dir} nohup su -c '{server_command}'"
    else:
      cmd_prefix = "nohup "
      cmd = f'{self.shellcmd} "LD_LIBRARY_PATH={lib_dir} {cmd_prefix} {server_dst_path} {server_port} >/data/local/tmp/albatross.log 2>&1 &"'
      remote_command = (
        f'LD_LIBRARY_PATH={lib_dir} nohup {server_dst_path} {server_port} '
        '>/data/local/tmp/albatross.log 2>&1 &')
    # process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    command = self.shellcmd_list + [remote_command]
    try:
      process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, start_new_session=(os.name == 'posix'))
    except BaseException:
      self._cleanup_failed_forward(local_port, 'server process launch failure')
      raise
    client = None
    client_connect_failed = True
    try:
      if self.usb_mode:
        time.sleep(2)
        client = self.albatross_client_impl(local_port, host, 'albatross-' + device_id, 500)
      else:
        client = None
        for i in range(5):
          time.sleep(4)
          try:
            client = self.albatross_client_impl(local_port, host, 'albatross-' + device_id, 500)
            break
          except TimeoutError as e:
            raise
          except OSError as e:
            if str(e) == 'Socket closed':
              continue
            raise
        else:
          client = self.albatross_client_impl(local_port, host, 'albatross-' + device_id, 500)
      client_connect_failed = False
    finally:
      if client_connect_failed:
        if client is not None:
          try:
            client.close()
          except Exception:
            pass
        self._cleanup_failed_forward(local_port, 'client connection failure')
      try:
        if os.name == 'posix':
          os.killpg(process.pid, signal.SIGTERM)
        else:
          process.terminate()
      except (ProcessLookupError, OSError):
        pass
      try:
        process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        try:
          if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
          else:
            process.kill()
        except (ProcessLookupError, OSError):
          pass
        process.wait()
      finally:
        for stream in (process.stdin, process.stdout, process.stderr):
          if stream is not None:
            stream.close()
    try:
      if self.is_selinux_on():
        client.patch_selinux()
      sync_lib()
      if self.anti_detection:
        self.hide_mount(client)
      return client
    except BaseException:
      try:
        client.close()
      finally:
        self._cleanup_failed_forward(local_port, 'client initialization failure')
      raise

  def hide_mount(self, client=None):
    if client is None:
      client = self.client
    if 'apd' in self.magisk_install_cmd:
      for p in ['zygote64', 'zygote']:
        carry_on = True
        for pid in self.pidof(p):
          mount_result = client.umount(pid, '/debug_ramdisk/pts:/debug_ramdisk')
          if mount_result != MountResult.MOUNT_SUCCESS:
            carry_on = False
            break
        if not carry_on:
          break
    # if self.support_kpm:
    #   for p in ['ap', 'apd', 'modules', 'service.d']:
    #     client.hide_path('/data/adb/' + p)
    mount_paths = cached_property.get(self, 'mount_paths')
    if mount_paths and len(mount_paths) > 1:
      client.add_launch_umount(':'.join(mount_paths.keys()))

  restart_system_callback = None

  def restart_system_server(self, reason=''):
    logger.info(f'{self.device_id} try restart system server:' + reason)
    if self.restart_system_callback:
      try:
        self.restart_system_callback(self, reason)
      except:
        pass
    desc = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    if reason:
      desc = desc + " " + reason
    try:
      self.shell(f'echo "{desc}" >> /data/local/tmp/reboot_system_server')
    except:
      pass
    self.root_shell('stop')
    time.sleep(0.5)
    self.root_shell('start')
    time.sleep(1)

  def on_system_subscribe_close(self, client):
    if self.reconnect:
      logger.info('system_server subscriber close')
      try:
        if client.reconnect():
          client.subscribe()
          return
      except:
        pass
    cached_property.delete(self, "system_server_subscriber")
    self._remove_forward_if_unused(getattr(client, 'port', None))

  def on_system_client_close(self, client):
    if self.reconnect:
      logger.info('system_server client close')
      if not client.reconnect():
        cached_property.delete(self, "system_server_client")
        self._remove_forward_if_unused(getattr(client, 'port', None))

  @cached_property
  def brand(self):
    return self.shell('getprop ro.product.brand')

  system_server_address = None

  @cached_property
  def system_server_subscriber(self) -> SystemServerClient:
    port = self.get_forward_port(self.system_server_address)
    if port is None:
      raise RuntimeError(f'failed to allocate system-server forward for {self.device_id}')
    system_client_class = self.system_client_class_impl
    subscribe_client = None
    try:
      subscribe_client = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
      subscribe_client.add_close_listener(self.on_system_subscribe_close, 'system_subscribe')
      subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
      subscribe_client.subscribe()
      return subscribe_client
    except BaseException:
      if subscribe_client is not None:
        try:
          subscribe_client.close()
        except Exception:
          pass
      self._cleanup_failed_forward(port, 'system subscriber initialization failure')
      raise

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
        if self.brand in [DeviceBrand.RedMi, DeviceBrand.Xiaomi]:
          self.reboot('agent update', 40)
          raise DeviceReboot(f'reboot device {self.device_id}')
        else:
          self.restart_system_server('agent update')
        time.sleep(20)
        if self.brand in [DeviceBrand.RealMe, DeviceBrand.OnePlus]:
          time.sleep(20)
          self.back()
    server_pid = client.get_process_pid('system_server')
    if server_pid <= 0:
      self.restart_system_server('system server dead')
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
      if port is None:
        raise RuntimeError(f'failed to allocate system-server forward for {self.device_id}')
      system_server = None
      try:
        system_server = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
        system_server.init()
      except BaseException:
        if system_server is not None:
          try:
            system_server.close()
          except Exception:
            pass
        self._cleanup_failed_forward(port, 'system client initialization failure')
        raise
      if self.auto_subscribe_system_server:
        subscribe_client = None
        try:
          subscribe_client = system_client_class(port, '127.0.0.1', 'system-' + self.device_id)
          subscribe_client.register_broadcast_handler(subscribe_client.launch_process, self.on_launch_process)
          subscribe_client.subscribe()
          subscribe_client.add_close_listener(self.on_system_subscribe_close, 'system_subscribe_close')
          # system_server.set_intercept_app(None)
          cached_property.reset(self, 'system_server_subscriber', subscribe_client)
        except BaseException:
          logger.exception(f'device {self.device_id} get system server subscriber fail')
      system_server.add_close_listener(self.on_system_client_close, 'system_disconnect')
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
    if cpu_abi and cpu_abi in ['arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86']:
      return cpu_abi
    file_type = self.shell('file /system/bin/sh')
    if 'arm64' in file_type:
      return 'arm64-v8a'
    if 'arm' in file_type:
      return 'armeabi-v7a'
    if 'x86' in file_type:
      if '64' in file_type:
        return 'x86_64'
      return 'x86'
    return cached_property.nil_value

  app_inject_flags = InjectFlag.KEEP | InjectFlag.UNIX
  app_init_flags = AlbatrossInitFlags.FLAG_LOG | AlbatrossInitFlags.FLAG_CALL_CHAIN | AlbatrossInitFlags.FLAG_INIT_RPC

  def add_init_flags(self, flag: AlbatrossInitFlags):
    self.app_init_flags = self.app_init_flags | flag

  def add_inject_flags(self, flag: InjectFlag):
    old_flags = self.app_inject_flags
    app_inject_flags = old_flags | flag
    if old_flags != app_inject_flags:
      self.app_inject_flags = app_inject_flags
      client: AlbatrossClient = cached_property.get(self, 'client')
      if client:
        client.set_inject_flags(app_inject_flags, self.temp_path)

  def on_launch_process(self, uid: int, pid: int, pkg: str, process: str, process_info: dict) -> byte:
    logger.info(f'launch process {uid}:{pid}:{process} {process_info}')
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
  temp_path = 'jit-cache'

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
          if self.brand in [DeviceBrand.RedMi, DeviceBrand.Xiaomi]:
            self.reboot('system server agent update', 40)
            raise DeviceReboot(f'reboot device {self.device_id}')
          else:
            self.restart_system_server('system server agent update')
          time.sleep(20)
          if self.brand in [DeviceBrand.RealMe, DeviceBrand.OnePlus]:
            time.sleep(20)
            self.back()
          system_server_restart_callback = self.system_server_restart_callback
      client.set_system_server_agent(agent_dst, Configuration.system_server_init_class, "system_server",
        AlbatrossInitFlags.NONE, None, self.system_server_init_flags)
      client.set_app_agent(self.agent_dex, None, Configuration.albatross_class_name,
        Configuration.albatross_agent_class, Configuration.albatross_register_func, self.app_init_flags)
      if self.app_inject_flags != InjectFlag.KEEP | InjectFlag.UNIX:
        client.set_inject_flags(self.app_inject_flags, self.temp_path)
      if not client.patch_selinux():
        self.setenforce(False)
      if system_server_restart_callback is not None:
        system_server_restart_callback(self)
      return True
    except Exception as e:
      logger.error('init plugin env fail:' + str(e))
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

  def attach_with_plugins(self, package_or_pid, plugins, init_flags=None, extra_info=None, inject_flags=None):
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
      if inject_flags is None:
        inject_flags = self.app_inject_flags
      temp_dir = None
      if inject_flags & InjectFlag.MEMFD:
        temp_dir = self.temp_path
      for pid in pids:
        res = client.inject_albatross(pid, inject_flags, temp_dir)
        if res >= 0:
          if init_flags is None:
            init_flags = self.app_init_flags
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
    assert os.path.exists(plugin_dex), plugin_dex
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
    is_update = self.push_file(plugin_dex, plugin_dex_device, file_type=self.file_type, mode='444', check=True)
    if plugin_lib:
      assert os.path.exists(plugin_lib), plugin_lib
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
    assert os.path.exists(plugin_dex), plugin_dex
    assert self.init_plugin_env
    client = self.client
    plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
    self.push_file(plugin_dex, plugin_dex_device, mode='444')
    if plugin_lib:
      assert os.path.exists(plugin_lib), plugin_lib
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
    res = client.add_plugin_rule(plugin.plugin_id, uid, target_package if uid == SYSTEM_UID else None, timeout=30)
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
      assert os.path.exists(plugin_dex), plugin_dex
      plugin_dex_device = Configuration.app_plugin_home + os.path.basename(plugin_dex)
      self.push_file(plugin_dex, plugin_dex_device, mode='444')
      for pid in pids:
        # pid_int = int(pid)
        res = client.inject_albatross(pid, self.app_inject_flags, self.temp_path)
        if res >= 0:
          if plugin_lib:
            assert os.path.exists(plugin_lib), plugin_lib
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

  def forward_tcp(self, local_port, device_port=None, keep=False):
    if device_port is None:
      device_port = local_port
    return self.forward(local_port, "tcp:%d" % device_port, keep=keep)

  def remote_ports(self, remote_port):
    device_name = getattr(self, 'adb_device_id', self.device_id)
    port_list = []
    if type(remote_port) == int:
      remote_port = 'tcp:' + str(remote_port)
    for s, lp, rp in self.forward_list():
      if rp == remote_port and s == device_name:
        if not lp.startswith(('tcp:', 'udp:')):
          continue
        try:
          local_port = int(lp[4:])
        except ValueError:
          continue
        port_list.append(local_port)
    return port_list

  def get_forward_port(self, remote_port, not_check=True):
    if isinstance(remote_port, int):
      remote_port = 'tcp:' + str(remote_port)
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      if getattr(self, '_forward_closed', False):
        raise RuntimeError(f'device {self.device_id} is closed')
      transport_id = getattr(self, 'adb_device_id', self.device_id)
      for s, lp, rp in self.forward_list():
        if rp != remote_port or s != transport_id or not lp.startswith('tcp:'):
          continue
        try:
          local_port = int(lp[4:])
        except ValueError:
          continue
        if not_check or is_socket_port_open("127.0.0.1", local_port):
          return local_port

      ret_code, output = self.adb_cmd('forward', 'tcp:0', remote_port, timeout=10)
      if ret_code == 0:
        text = output.decode('utf-8', errors='replace').strip()
        for line in reversed(text.splitlines()):
          match = re.fullmatch(r'(?:tcp:)?(\d+)', line.strip())
          if match:
            local_port = int(match.group(1))
            self._owned_forward_ports.add(local_port)
            return local_port
        for s, lp, rp in reversed(self.forward_list()):
          if s == transport_id and rp == remote_port and lp.startswith('tcp:'):
            try:
              local_port = int(lp[4:])
            except ValueError:
              continue
            self._owned_forward_ports.add(local_port)
            return local_port
        logger.warning('adb allocated a forward for %s but returned no local port', self.device_id)
        return None

      # Older adb versions may not support tcp:0. Release the reservation before
      # invoking adb and retry only failed local binds a bounded number of times.
      for _ in range(3):
        with get_available_port() as local_port:
          pass
        if self.forward(local_port, remote_port) == 0:
          return local_port
      logger.warning('failed to allocate forward for %s', self.device_id)
      return None

  def remove_albatross_port(self, timeout=None):
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      if timeout is None:
        forwards = self.forward_list()
      else:
        ret_code, output = self.adb_cmd("forward", "--list", timeout=timeout)
        if ret_code != 0:
          return
        forwards = []
        transport_id = getattr(self, 'adb_device_id', self.device_id)
        for line in output.decode("utf-8", errors="replace").strip().splitlines():
          fields = line.strip().split()
          if len(fields) == 3 and fields[0] == transport_id:
            forwards.append(fields)
      transport_id = getattr(self, 'adb_device_id', self.device_id)
      for s, lp, rp in forwards:
        if re.findall('localabstract:albatross_\\d+', rp) and s == transport_id:
          kwargs = {'timeout': timeout} if timeout is not None else {}
          ret_code, _ = self.adb_cmd('forward', '--remove', lp, **kwargs)
          if ret_code != 0:
            continue
          if lp.startswith('tcp:'):
            try:
              self._owned_forward_ports.discard(int(lp[4:]))
            except ValueError:
              pass

  def remove_forward_port(self, port, timeout=10):
    forward_lock = getattr(self, '_forward_lock', None)
    if forward_lock is None:
      forward_lock = self._forward_lock = threading.RLock()
    with forward_lock:
      if isinstance(port, int):
        port = 'tcp:' + str(port)
      kwargs = {'timeout': timeout} if timeout is not None else {}
      ret_code, _ = self.adb_cmd('forward', '--remove', port, **kwargs)
      if ret_code != 0:
        return False
      if isinstance(port, str) and ':' in port:
        try:
          self._owned_forward_ports.discard(int(port.split(':', 1)[1]))
        except ValueError:
          pass
      return True

  def dumpui(self, path=None):
    try:
      ret_str = self.shell("uiautomator dump /data/local/tmp/uidump.xml")
      if not ret_str.startswith("UI hierchary dumped to"):
        return False
      if path:
        return self.adb_cmd('pull', '/data/local/tmp/uidump.xml', path)[0] == 0
      else:
        return self.shell('cat /data/local/tmp/uidump.xml')
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
      if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
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
      if v > int(version_code):
        if ignore_gt:
          return False
        else:
          self.uninstall_package(package, f'version to is greater than target {version_code}')
    if self.brand not in [DeviceBrand.Aosp, DeviceBrand.Google]:
      self.silence_install(apk)
    else:
      res = self.adb_cmd('install', '-r', '-d', '-t', apk)
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
    return self.shell("input keyevent 3")

  def switch_app(self):
    return self.shell('input keyevent KEYCODE_APP_SWITCH')

  @cached_property
  def sdk_version(self):
    try:
      sdk = int(self.shell("getprop ro.build.version.sdk"))
      return sdk
    except:
      return cached_property.nil_value

  base_activity_pattern = re.compile(
    r"Run\s#\d+:\sActivityRecord{\w+\s\w+\s([\w\.]+/[\w\.]+)"
  )

  def get_activity_stack(self, pkg=None):
    rstr = self.shell("dumpsys activity | grep -i run")
    if "Illegal" in rstr:
      rstr = self.shell('dumpsys activity | grep -i run')
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
      result = re.findall(r'([\w.]+)/([\w.$]+)', res)
      if result:
        # dumpsys window can print both a global/current value and one or more
        # display-scoped mCurrentFocus values.  The first line may therefore be
        # stale or from another focus owner; keep the last non-null window focus
        # reported by WindowManager.
        return result[-1]
    # cmd = self.cmd + 'shell "dumpsys activity | grep mFoc"'
    # cmd = self.cmd + 'shell  "dumpsys window | grep mCurrentFocus"'
    stack = self.get_activity_stack()
    if not stack:
      # cmd = self.cmd + 'shell " dumpsys activity | grep -i mResumedActivity"'
      rstr = self.shell('dumpsys activity | grep -i mResumedActivity')
      stack = resume_activity_pattern.findall(rstr)
    if stack:
      top_stack = stack[0].split("/")
      return top_stack[0], top_stack[1]
    return None, None

  def pull_file(self, src_android, dst_pc, is_del=False):
    # command = self.cmd + ' pull "{}" "{}"'.format(src_android, dst_pc)
    ret_code, res = self.adb_cmd('pull', src_android, dst_pc)
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
        # command = self.cmd + ' pull "{}" "{}"'.format(dst_mv, dst_pc)
        ret_code, res = self.adb_cmd('pull', dst_mv, dst_pc)
        self.root_shell('rm -rf {}'.format(dst_mv))
        if is_del:
          self.root_shell('rm -rf {}'.format(src_android))
        return ret_code == 0
      return False
    if not is_del:
      return True
    ret_code, _ = self.shell('rm -rf ' + src_android, return_code=True)
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
    ret_str = self.run_as_shell(
      'dumpsys package ' + pkg + " | grep -E 'userId=|appId=' | head -n 20 ; pm list package | grep " + pkg)  # uid=|
    res = re.findall(r'(?:appId|uid|userId)=(\d+)', ret_str)
    if res and len(set(res)) == 1 and 'package:' + pkg in ret_str:
      return int(res[0])
    return None

  def get_package_uid_and_version(self, pkg):
    ret_str = self.run_as_shell(
      'dumpsys package ' + pkg + " | grep -E 'userId=|appId=|versionCode=' | head -n 20; pm list package | grep " + pkg)  # uid=|
    uid_match = re.findall(r'(?:appId|uid|userId)=(\d+)', ret_str)
    version_match = re.findall(r'versionCode=(\d+)', ret_str)
    if version_match and len(version_match) < 3 and uid_match and 'package:' + pkg in ret_str:
      return int(uid_match[0]), int(version_match[0])
    return None, None

  def get_package_version_code(self, pkg, cached=True, uninstall_corrupt=False):
    ret_str = self.run_as_shell(
      'dumpsys package ' + pkg + " | grep versionCode= | head -n 10 ; pm list package | grep " + pkg)
    if not ret_str:
      return False
    res = re.findall(r'versionCode=(\d+)', ret_str)
    if res and len(res) < 3:
      version = int(res[0])
      if 'package:' + pkg not in ret_str.split():
        if uninstall_corrupt:
          self.shell('pm uninstall ' + pkg)
        return None
      return version
    return None

  def uninstall_package(self, pkg, reason=None):
    logger.info(f'device {self.device_id}  uninstall {pkg} by {reason}')
    self.adb_cmd(f'uninstall', pkg)

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
      result = self.shell(cmd)
      if self.ret_code:
        continue
      ips = re.findall(ip_pattern, result)
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
    return self.adb_device_id

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
    usb_server_port = AdbConfig.adb_server_ports[0]
    run_adb(
      'tcpip', str(self.tcp_port), device_id=self.device_id,
      server_port=usb_server_port,
    )
    for z in range(2):
      endpoint = ip + ":" + str(self.tcp_port)
      if try_connect(endpoint):
        time.sleep(0.3)
        for i in range(2):
          server_port = adb_server_port_for(endpoint)
          _, ret = run_adb(
            'shell', 'echo hello', device_id=endpoint, server_port=server_port,
          )
          if b'hello' in ret:
            self._set_adb_transport(endpoint, server_port)
            self.connect_ip = ip
            return True
          elif not i:
            time.sleep(1)
    return False

  def switch_to_usb_connect(self):
    if not self.usb_mode:
      return False
    if self.adb_device_id != self.device_id:
      usb_server_port = AdbConfig.adb_server_ports[0]
      ret_code, bs = run_adb(
        'shell', 'echo hello', device_id=self.device_id,
        server_port=usb_server_port,
      )
      if b'hello' in bs:
        self._set_adb_transport(self.device_id, usb_server_port)
        endpoint = f'{self.connect_ip}:{self.tcp_port}'
        if AdbConfig.adb_transport_owner:
          disconnect_code, _ = _adb_disconnect(endpoint)
          _record_disconnect_outcome(endpoint, disconnect_code == 0)
        else:
          logger.info(f'adb disconnect {endpoint} skipped in non-owner process')
        return True
    return False

  def get_ram_size(self):
    ram_output = self.shell("cat /proc/meminfo | grep MemTotal")
    if not ram_output:
      return None
    # 提取数字（KB）
    ram_kb = re.findall(r'\d+', ram_output)
    if not ram_kb:
      logger.info("未解析到RAM大小")
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

  def silence_install(self, pkg_path, clear_cache=False, use_root=True, timeout=120):
    assert os.path.exists(pkg_path), pkg_path
    temp_path = '/data/local/tmp/' + os.path.basename(pkg_path)
    self.push_file(pkg_path, temp_path, timeout=timeout + 120)
    if use_root:
      shell = self.root_shell
    else:
      shell = self.shell
    if clear_cache:
      return shell('pm install -r -t ' + temp_path + " && rm " + temp_path, timeout=timeout)
    else:
      return shell('pm install -r -t ' + temp_path, timeout=timeout)

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

  def list_opened_files_by_pid(self, pid):
    """通过 PID 获取所有打开的文件路径"""

    # 列出 fd 目录下所有文件描述符
    fd_list = self.root_shell(f"ls /proc/{pid}/fd/").split()
    if not fd_list:
      logger.info("无法读取 fd 目录（可能权限不足）")
      return []

    opened_files = []
    invalid_prefixes = ("pipe:", "/dev", "/proc", "anon_inode:")  # "socket:",

    for fd in fd_list:
      # 读取软链接真实路径
      path = self.root_shell(f"readlink /proc/{pid}/fd/{fd}")
      if not path:
        continue

      # 过滤无效路径
      if path.startswith(invalid_prefixes):
        continue
      if path in opened_files:
        continue

      opened_files.append(path)

    return opened_files

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
          logger.error(f"\n更新插件失败: {str(e)}")

      def on_modified(self, event):
        """处理文件修改事件"""
        if not event.is_directory and event.src_path == os.path.abspath(plugin_dex):
          self.handle_plugin_change()

      def on_created(self, event):
        """处理文件创建事件（针对文件被删除后重新创建的情况）"""
        if not event.is_directory and event.src_path == os.path.abspath(plugin_dex):
          logger.info("检测到版本文件重新创建")
          self.handle_plugin_change()

    event_handler = FileChangeHandler()
    from watchdog.observers import Observer
    observer = Observer()
    observer.schedule(event_handler, plugin_dex, recursive=False)
    observer.start()
    logger.info(f"开始监控插件: {Observer} ")
    logger.info("按Ctrl+C停止监控")
    try:
      while True:
        time.sleep(5)
    except KeyboardInterrupt:
      observer.stop()
      logger.info("\n监控已停止")
    observer.join()


class DeviceManager:

  def __init__(self):
    self.devices = {}
    self._lock = threading.RLock()
    self._endpoint_locks = {}
    self._health = {}
    self._closed = False
    self._metrics = {
      'health_checks': 0,
      'health_cache_hits': 0,
      'health_failures': 0,
      'health_invalidations': 0,
      'device_creations': 0,
    }

  @contextmanager
  def endpoint_lock(self, device_id):
    with self._lock:
      entry = self._endpoint_locks.get(device_id)
      if entry is None:
        entry = {'lock': threading.Lock(), 'users': 0}
        self._endpoint_locks[device_id] = entry
      entry['users'] += 1
      lock = entry['lock']
    try:
      with lock:
        yield
    finally:
      with self._lock:
        entry['users'] -= 1
        if entry['users'] == 0 and self._endpoint_locks.get(device_id) is entry:
          self._endpoint_locks.pop(device_id, None)

  def _record_health(self, device_id, alive, result=None, reason='probe'):
    now = time.monotonic()
    with self._lock:
      self._metrics['health_checks'] += 1
      if not alive:
        self._metrics['health_failures'] += 1
      self._health[device_id] = {
        'alive': bool(alive),
        'checked_at': now,
        'expires_at': now + AdbConfig.device_health_ttl,
        'error_code': result.error_code if result is not None else (
          AdbErrorCode.OK if alive else AdbErrorCode.COMMAND_FAILED),
        'return_code': result.return_code if result is not None else None,
        'elapsed_ms': result.elapsed_ms if result is not None else None,
        'reason': reason,
        'server_port': adb_server_port_for(device_id),
      }

  def invalidate_health(self, device_id, reason='device_event'):
    now = time.monotonic()
    with self._lock:
      self._metrics['health_invalidations'] += 1
      previous = self._health.get(device_id, {})
      self._health[device_id] = {
        'alive': False,
        'checked_at': now,
        'expires_at': now,
        'error_code': AdbErrorCode.COMMAND_FAILED,
        'return_code': previous.get('return_code'),
        'elapsed_ms': previous.get('elapsed_ms'),
        'reason': reason,
        'server_port': adb_server_port_for(device_id),
      }

  def _cached_health(self, device_id, now):
    with self._lock:
      device = self.devices.get(device_id)
      health = self._health.get(device_id)
      if health and health['expires_at'] > now:
        self._metrics['health_cache_hits'] += 1
        return health, device
      return None, device

  def health_snapshot(self):
    now = time.monotonic()
    with self._lock:
      devices = {
        device_id: {
          'alive': health['alive'],
          'age_seconds': max(0, now - health['checked_at']),
          'ttl_remaining': max(0, health['expires_at'] - now),
          'error_code': health['error_code'],
          'return_code': health['return_code'],
          'elapsed_ms': health['elapsed_ms'],
          'reason': health.get('reason'),
          'server_port': health.get('server_port', adb_server_port_for(device_id)),
        }
        for device_id, health in self._health.items()
      }
      servers = {}
      for port in AdbConfig.adb_server_ports:
        shard_devices = [health for health in devices.values() if health['server_port'] == port]
        servers[port] = {
          'device_count': len(shard_devices),
          'alive_count': sum(1 for health in shard_devices if health['alive']),
          'health_failures': sum(
            1 for health in shard_devices if not health['alive']
          ),
        }
      return {'metrics': dict(self._metrics), 'devices': devices, 'servers': servers}

  def get_cached_device(self, device_id):
    with self._lock:
      return self.devices.get(device_id)

  def pop_cached_device(self, device_id, clear_health=True):
    with self._lock:
      if clear_health:
        self._health.pop(device_id, None)
      return self.devices.pop(device_id, None)

  def remove_device(self, device_id):
    with self.endpoint_lock(device_id):
      device: AlbatrossDevice = self.pop_cached_device(device_id)
      if device is not None:
        device.close()
      return device

  def _evict_offline_device(self, device_id, probe_id):
    stale = self.pop_cached_device(device_id, clear_health=False)
    if AdbConfig.adb_transport_owner and parse_tcp_endpoint(probe_id) is not None:
      coordinator = AdbConfig.connection_coordinator
      if coordinator.disconnect_cleanup_due(probe_id, time.monotonic()):
        disconnected = _clear_cached_transport(probe_id, stale)
        if disconnected:
          coordinator.record_failure(
            probe_id, time.monotonic(), AdbErrorCode.COMMAND_FAILED,
          )
        else:
          _record_disconnect_outcome(probe_id, False)
        return
    if stale is not None:
      try:
        stale.prevent_new_forwards()
        ports = stale.close_rpc_clients()
        stale.cleanup_forwards(ports, timeout=2)
      except Exception:
        logger.exception('failed to clean offline device %s', device_id)

  def _get_device_singleflight(self, device_id, validate_transport):
    with self._lock:
      if self._closed:
        raise RuntimeError('device manager is closed')
    health, cached = self._cached_health(device_id, time.monotonic())
    if health is not None:
      if health['alive'] and cached is not None:
        return cached
      if not health['alive']:
        raise DeviceOffline(device_id)
    probe_id = device_id
    if cached is not None and not cached.usb_mode:
      probe_id = cached.get_connect_device_id()
    if validate_transport:
      list_result, devices = list_devices(
        server_port=adb_server_port_for(probe_id),
      )
      if not list_result.ok:
        logger.warning(
          'adb devices failed error=%s code=%s elapsed_ms=%.1f',
          list_result.error_code, list_result.return_code, list_result.elapsed_ms,
        )
        raise NoDeviceFound()
      if not devices:
        self._record_health(device_id, False, reason='adb_devices_missing')
        self._evict_offline_device(device_id, probe_id)
        raise NoDeviceFound()
      if device_id not in devices:
        self._record_health(device_id, False, reason='adb_devices_missing')
        self._evict_offline_device(device_id, probe_id)
        raise DeviceNoFindErr(device_id)
    with self._lock:
      cached = self.devices.get(device_id)
    alive, result = probe_device_alive(probe_id, 2 if cached is None or cached.usb_mode else 3)
    self._record_health(device_id, alive, result)
    with self._lock:
      if self._closed:
        raise RuntimeError('device manager is closed')
    if not alive:
      self._evict_offline_device(device_id, probe_id)
      raise DeviceOffline(device_id)
    if cached is not None:
      return cached
    device = AlbatrossDevice(device_id)
    with self._lock:
      if self._closed:
        should_close = True
      else:
        should_close = False
        self.devices[device_id] = device
        self._metrics['device_creations'] += 1
    if should_close:
      try:
        device.close_rpc_clients()
      except Exception:
        pass
      raise RuntimeError('device manager is closed')
    return device

  def get_devices(self, device_id) -> AlbatrossDevice:
    if device_id:
      with self.endpoint_lock(device_id):
        return self._get_device_singleflight(device_id, AdbConfig.adb_connect_enabled)

    list_result, devices = list_devices()
    if not list_result.ok:
      logger.warning(
        'adb devices failed error=%s code=%s elapsed_ms=%.1f',
        list_result.error_code, list_result.return_code, list_result.elapsed_ms,
      )
      raise NoDeviceFound()
    if not devices:
      raise NoDeviceFound()
    device_id = devices[0]
    if len(devices) > 1:
      logger.info("more than one device,default choose device " + device_id)
    with self.endpoint_lock(device_id):
      return self._get_device_singleflight(device_id, False)

  def close_all(self):
    with self._lock:
      self._closed = True
      devices = list(self.devices.values())
      self.devices.clear()
      self._health.clear()
    for device in devices:
      try:
        device.close()
      except Exception:
        logger.exception('failed to close cached device %s', device.device_id)


_device_manager: DeviceManager | None = None
_device_manager_lock = threading.RLock()


def get_device_manager() -> "DeviceManager":
  global _device_manager
  with _device_manager_lock:
    if _device_manager is None:
      _device_manager = DeviceManager()
    return _device_manager


def get_device_health():
  manager = _device_manager
  if manager is None:
    return {
      'metrics': {},
      'devices': {},
      'servers': {
        port: {'device_count': 0, 'alive_count': 0, 'health_failures': 0}
        for port in AdbConfig.adb_server_ports
      },
    }
  return manager.health_snapshot()


def destroy_device():
  global _device_manager
  with _device_manager_lock:
    manager = _device_manager
    _device_manager = None
  if manager is not None:
    manager.close_all()
