from enum import IntFlag

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

  @rpc_api
  def hook_method(self, class_name: str, method_name: str, num_args: int, args: str, dex_pc: int) -> int:
    """
    钩子方法，用于拦截和修改方法调用

    Args:
        class_name (str): 类名
        method_name (str): 方法名
        num_args (int): 参数数量
        args (str): 参数信息
        dex_pc (int): DEX程序计数器

    Returns:
        int: 监听器ID
    """

  @rpc_api
  def unhook_method(self, listener_id: int) -> bool:
    """
    取消方法钩子

    Args:
        listener_id (int): 监听器ID

    Returns:
        bool: 是否成功取消钩子
    """

  @rpc_api
  def print_all_class_loader(self) -> str:
    pass

  @rpc_api
  def redirect_app_log(self, file_name: str = 'app') -> bool:
    pass

  @rpc_api
  def finish_redirect_app_log(self) -> bool:
    pass

  @rpc_api
  def set_logger(self, log_dir: str, log_file_name: str) -> void:
    pass

  @broadcast_api
  def send(self, content: str, exception: str) -> void:
    if exception:
      print("[#]", content, exception)
    else:
      print("[*] " + content)
