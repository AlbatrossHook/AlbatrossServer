import time

import albatross
from albatross.albatross_client import AlbatrossInitFlags
from albatross.app_client import AppClient
from albatross.common import Configuration
from albatross.rpc_common import void, rpc_api


class DemoClient(AppClient):

  @rpc_api
  def toast_msg(self, msg: str) -> void:
    pass


def main(device_id=None):
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()
  device.home()
  device.remove_albatross_port()
  user_pkgs = device.get_user_packages()
  plugin_apk = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  client = device.client
  if client.is_lsposed_injected():
    print("Lsposed injected,not support!")
    albatross.destroy()
    return
  if not device.debuggable:
    device.app_init_flags |= AlbatrossInitFlags.REDIRECT_LOG
  client.create_subscriber()
  client.clear_plugins()

  fail_launch_pkgs = set()

  for pkg in user_pkgs:
    if pkg == 'com.coloros.backuprestore':
      continue
    # if 'albatross' in pkg and 'inject_demo' not in pkg:
    #   continue
    print('try test', pkg)
    if device.debuggable:
      device.delete_file(f'/data/data/{pkg}/files/log')
    for i in range(2):
      if i == 0:
        device.launch_fast(pkg, plugin_apk, plugin_class, plugin_params=pkg)
      else:
        device.stop_app(pkg)
        device.start_app(pkg)
      time.sleep(6)
      uid = device.get_package_uid(pkg)
      pids = client.get_java_processes_by_uid(uid)
      app_clients = []
      for pid in pids:
        try:
          address = client.get_address(pid)
          port = device.get_forward_port('localabstract:' + address)
          app_client = DemoClient(port, None, pkg + ":" + str(pid))
          target_uid = app_client.getuid()
          assert uid == target_uid
          target_pkg = app_client.get_package_name()
          assert pkg == target_pkg
          app_clients.append(app_client)
        except Exception as e:
          print(f'test app {pkg} fail:{e}')
          fail_launch_pkgs.add(pkg)
      time.sleep(5)
      for app_client in app_clients:
        try:
          app_client.toast_msg('finish launch test:' + pkg)
          app_client.close()
          device.remove_forward_port(app_client.port)
          time.sleep(1)
        except:
          fail_launch_pkgs.add(pkg)
  client.clear_plugins()
  print('finish test')
  if fail_launch_pkgs:
    print(f'fail to launch packages:{list(fail_launch_pkgs)}')
  device.remove_albatross_port()
  albatross.destroy()


if __name__ == '__main__':
  main()
