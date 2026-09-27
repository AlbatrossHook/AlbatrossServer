import os
import sys
import time

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _parent in (_repo_root, os.path.join(_repo_root, 'albatross-python')):
  if _parent not in sys.path:
    sys.path.insert(0, _parent)

import albatross
from albatross.app_client import AppClient
from albatross.common import Configuration


def main(device_id=None, anti_detection=False):
  print('launch mode is deprecated,use launch fast instead.')
  sys.exit(1)
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()
  device.home()
  if anti_detection:
    hide_albatross(device)

  user_pkgs = device.get_user_packages()
  plugin_apk = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  client = device.client
  if client.is_lsposed_injected():
    print("Lsposed injected,not support!")
    albatross.destroy()
    return
  for pkg in user_pkgs:
    if 'albatross' in pkg and 'inject_demo' not in pkg:
      continue
    print('try test', pkg)
    device.launch(pkg, plugin_apk, plugin_class)
    time.sleep(8)
    uid = device.get_package_uid(pkg)
    pids = client.get_java_processes_by_uid(uid)
    for pid in pids:
      address = client.get_address(pid)
      port = device.get_forward_port('localabstract:' + address)
      app_client = AppClient(None, port, pkg + ":" + str(pid))
      target_uid = app_client.getuid()
      assert uid == target_uid
      target_pkg = app_client.get_package_name()
      assert pkg == target_pkg
      app_client.close()
      device.remove_forward_port(port)
  albatross.destroy()
  print('finish test')


if __name__ == '__main__':
  if len(sys.argv) > 1:
    main(sys.argv[1])
  else:
    main()
