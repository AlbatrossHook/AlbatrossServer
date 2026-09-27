from albatross.albatross_client import InjectFlag, AlbatrossInitFlags


def check_client(anti_detection, device, app_client):
  maps = app_client.read_maps()
  if anti_detection:
    assert device.lib_dst not in maps
    assert device.agent_dex not in maps
    assert '/data/local/tmp' not in maps
  else:
    assert device.lib_dst in maps
    assert device.agent_dex in maps


def hide_albatross(device):
  device.anti_detection = True
  device.add_init_flags(AlbatrossInitFlags.FLAG_ANTI_DETECTION)
  # 加载无痕hook的代码逻辑
  # 需要加载配套的kpm过crc检测
  # device.load_kpm_impl=xxx
  if not device.support_kpm:
    # 没有加载kpm,则memfd注入隐藏,过不了crc检测
    device.add_inject_flags(InjectFlag.MEMFD)

