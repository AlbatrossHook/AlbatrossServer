import time

import albatross
from albatross.app_client import AppClient
from albatross.common import Configuration


def main(device_id=None):
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()
  device.home()
  user_pkgs = device.get_user_packages()
  plugin_apk = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  client = device.client
  client.clear_plugins()
  for pkg in user_pkgs:
    if 'albatross' in pkg and 'inject_demo' not in pkg:
      continue
    print('try test', pkg)
    for i in range(2):
      if i == 0:
        device.launch_fast(pkg, plugin_apk, plugin_class, plugin_params=pkg)
      else:
        device.stop_app(pkg)
        device.start_app(pkg)
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
  client.clear_plugins()
  albatross.destroy()
  print('finish test')


if __name__ == '__main__':
  main()
