import os
import time

import albatross
from albatross.app_client import AppClient


def main(attach, device_id=None):
  plugin_dex = (os.path.dirname(__file__)
                + "/../albatross-java/plugin_demo/build/outputs/apk/debug/plugin_demo-debug.apk")
  assert os.path.exists(plugin_dex)
  device = albatross.get_device(device_id)
  device.update_kill = False
  device.wake_up()
  device.clear_plugins()
  user_pkgs = device.get_user_packages()
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  plugin = device.register_plugin(plugin_dex, plugin_class)
  client = device.client

  for test_app in user_pkgs:
    uid = device.get_package_uid(test_app)
    for i in range(5):
      if not attach:
        device.launch_with_plugins(test_app, [plugin])
      else:
        device.stop_app(test_app)
        device.start_app(test_app)
        time.sleep(3)
        device.attach_with_plugin_ids(test_app, [plugin])
      time.sleep(4)
      pids = client.get_java_processes_by_uid(uid)
      for pid in pids:
        address = client.get_address(pid)
        port = device.get_forward_port('localabstract:' + address)
        app_client = AppClient(port, test_app + ":" + str(pid))
        target_uid = app_client.getuid()
        assert uid == target_uid
        pkg = app_client.get_package_name()
        assert pkg == test_app
        app_client.close()
        device.remove_forward_port(port)
      device.watch_plugin(test_app, plugin, attach=i % 1 != 0)

  time.sleep(12)
  albatross.destroy()


if __name__ == '__main__':
  main(False, )
