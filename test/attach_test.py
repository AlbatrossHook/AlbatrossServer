import time

import albatross
from albatross.common import Configuration


def main(device_id=None):
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()
  user_pkgs = device.get_user_packages()
  plugin_dex = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  for pkg in user_pkgs:
    if 'albatross' in pkg and 'inject_demo' not in pkg:
      continue
    print('try test', pkg)
    device.stop_app(pkg)
    device.start_app(pkg)
    time.sleep(5)
    device.attach(pkg, plugin_dex, plugin_class)
    device.home()
    for i in range(3):
      device.switch_app()
      time.sleep(1)
      device.switch_app()
      time.sleep(2)
  albatross.destroy()
  print('finish test')


if __name__ == '__main__':
  main()
