from albatross.rpc_client import RpcClient, rpc_api


class AppClient(RpcClient):
  def __init__(self, port, name=None, timeout=None):
    super(AppClient, self).__init__('127.0.0.1', port, name, timeout)

  @rpc_api
  def getuid(self) -> int:
    pass

  @rpc_api
  def get_package_name(self) -> str:
    pass
