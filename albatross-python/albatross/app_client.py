from albatross.rpc_client import RpcClient, rpc_api, void, broadcast_api


class AppClient(RpcClient):

  @rpc_api
  def getuid(self) -> int:
    """
    获取当前进程的用户ID

    Returns:
        int: 用户ID
    """

  @rpc_api
  def get_package_name(self) -> str:
    """
    获取当前应用的包名

    Returns:
        str: 应用包名
    """

  @broadcast_api
  def send(self, content: str, exception: str) -> void:
    if exception:
      print("[#]", content, exception)
    else:
      print("[*] " + content)
