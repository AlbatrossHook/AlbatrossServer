import time

import albatross
from albatross.albatross_client import AlbatrossInitFlags, InjectFlag
from albatross.app_client import AppClient
from albatross.common import Configuration
from albatross.rpc_common import rpc_api, void


class DemoClient(AppClient):

  @rpc_api
  def toast_msg(self, msg: str) -> void:
    pass


def main(device_id=None, anti_detection=False):
  device = albatross.get_device(device_id)
  assert device.is_root
  device.wake_up()

  app_init_flags = AlbatrossInitFlags.FLAG_LOG | AlbatrossInitFlags.FLAG_CALL_CHAIN
  if not device.debuggable:
    app_init_flags |= AlbatrossInitFlags.REDIRECT_LOG
  if anti_detection:
    app_init_flags |= AlbatrossInitFlags.FLAG_ANTI_DETECTION
    device.anti_detection = True
    device.add_init_flags(AlbatrossInitFlags.FLAG_ANTI_DETECTION)
    # 加载无痕hook的代码逻辑
    # device.load_kpm_impl=xxx
    if not device.support_kpm:
      device.add_inject_flags(InjectFlag.MEMFD)

  user_pkgs = device.get_user_packages()
  plugin_dex = Configuration.resource_dir + "plugins/plugin_demo.dex"
  plugin_class = "qing.albatross.plugin.app.DemoPlugin"
  client = device.client

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
        app_client = DemoClient(port, None, pkg + ":" + str(pid))
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
      app_client.toast_msg('finish attach test:' + pkg)
      app_client.close()
      device.remove_forward_port(port)
  albatross.destroy()
  print('finish test')


if __name__ == '__main__':
  main(anti_detection=True)
