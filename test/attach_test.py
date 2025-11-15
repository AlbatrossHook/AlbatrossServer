import time

import albatross
from albatross.albatross_client import AlbatrossInitFlags
from albatross.app_client import AppClient
from albatross.common import Configuration


def main(device_id=None):
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()
  user_pkgs = device.get_user_packages()
  plugin_dex = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  client = device.client

  app_init_flags = AlbatrossInitFlags.FLAG_LOG | AlbatrossInitFlags.FLAG_CALL_CHAIN
  if not device.debuggable:
    app_init_flags |= AlbatrossInitFlags.REDIRECT_LOG
  for pkg in user_pkgs:
    # if 'albatross' in pkg and 'inject_demo' not in pkg:
    #   continue
    uid = device.get_package_uid(pkg)
    print('try test', pkg)
    device.stop_app(pkg)
    device.start_app(pkg)
    if not device.debuggable:
      device.delete_file(f'/data/data/{pkg}/files/log')
    time.sleep(3)
    try:
      pids = device.attach(pkg, plugin_dex, plugin_class, init_flags=app_init_flags)
    except Exception as e:
      print(f'attach {pkg} fail:{e}')
      continue
    if not pids:
      print(f'attach {pkg} fail')
      continue
    time.sleep(2)
    app_clients = []
    for pid in pids:
      try:
        address = client.get_address(pid)
        port = device.get_forward_port('localabstract:' + address)
        app_client = AppClient(None, port, pkg + ":" + str(pid))
        target_uid = app_client.getuid()
        assert uid == target_uid
        pkg_get = app_client.get_package_name()
        assert pkg == pkg_get
        app_client.create_subscriber()
        app_clients.append((app_client, port))
      except Exception as e:
        print(f'attach {pkg} fail: {e} ')
    device.home()
    for i in range(3):
      device.switch_app()
      time.sleep(1)
      device.switch_app()
      time.sleep(2)
    for app_client, port in app_clients:
      app_client.close()
      device.remove_forward_port(port)
  albatross.destroy()
  print('finish test')


if __name__ == '__main__':
  main()
