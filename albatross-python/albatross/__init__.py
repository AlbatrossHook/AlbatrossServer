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


import atexit
import logging
import threading
import traceback
from typing import Optional
from . import device

__version__ = "3.6.0"

_destroy_lock = threading.RLock()
_destroying = False
_logger = logging.getLogger("albatross")


def get_device(device_id: Optional[str] = None) -> device.AlbatrossDevice:
  return device.get_device_manager().get_devices(device_id)


def get_cached_device(device_id: str) -> device.AlbatrossDevice | None:
  return device.get_device_manager().get_cached_device(device_id)


def remove_device(device_id: str) -> device.AlbatrossDevice | None:
  return device.get_device_manager().remove_device(device_id)


def get_device_ids():
  return device.get_devices()


def get_usb_devices():
  return device.get_usb_devices()


def get_health_snapshot():
  return {
    'connections': device.get_adb_connection_health(),
    'devices': device.get_device_health(),
  }


def destroy():
  """Release library-owned clients, forwards, sockets and plugin state.

  The function is idempotent and is also registered with :mod:`atexit` for
  normal interpreter shutdown.  It cannot run after SIGKILL, ``os._exit`` or
  a native crash.
  """
  global _destroying
  with _destroy_lock:
    if _destroying:
      return
    _destroying = True
  errors = []
  try:
    try:
      device.destroy_device()
    except BaseException as e:
      errors.append(e)
      _logger.exception("failed to destroy albatross devices")
    try:
      from . import rpc_client
      rpc_client.close_monitor()
    except BaseException as e:
      errors.append(e)
      _logger.exception("failed to close albatross socket monitor")
    try:
      from . import plugin
      plugin.clear_plugin()
    except BaseException as e:
      errors.append(e)
      _logger.exception("failed to clear albatross plugins")
  finally:
    with _destroy_lock:
      _destroying = False
  if errors:
    raise errors[0]


def _destroy_at_exit():
  try:
    destroy()
  except BaseException:
    # Cleanup must not turn a normal interpreter shutdown into a noisy
    # unhandled exception; details have already been logged above.
    traceback.print_exc()


atexit.register(_destroy_at_exit)
