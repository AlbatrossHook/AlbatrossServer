# Copyright 2025 QingWan (qingwanmail@foxmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from enum import IntEnum, IntFlag
import json

from albatross.rpc_client import RpcClient
from albatross.rpc_common import read_string, read_long, long, ByteEnum, rpc_api, byte, void


def parse_hook_events(data: str):
  """解析 hook_events_pull 的返回：返回 (记录列表, 新游标 next_seq)。

  首行是 "#{" 开头的游标元信息（first_seq/next_seq/dropped/capacity/skipped），
  其余每行一条 JSON 记录（seq/ts/tid/thread/kind/phase/method/this/args/ret）。
  """
  events = []
  next_seq = 0
  for line in data.splitlines():
    if not line:
      continue
    if line.startswith('#'):
      info = json.loads(line[1:])
      next_seq = info.get('next_seq', 0)
      continue
    try:
      events.append(json.loads(line))
    except json.JSONDecodeError:
      continue
  return events, next_seq


class LoadLibResult(ByteEnum):
  LOAD_LIB_SUCCESS = 0
  LOAD_LIB_ARG_ERR = 1
  LOAD_LIB_OPEN_ERR = 2
  LOAD_LIB_SYMBOL_ERR = 3
  LOAD_LIB_INIT_ERR = 4
  LOAD_LIB_SEND_ERR = 5


class RegisterResult(ByteEnum):
  REGISTER_SUCCESS = 0
  REGISTER_ARG_ERR = 1
  REGISTER_OPEN_ERR = 2
  REGISTER_SYMBOL_ERR = 3
  REGISTER_INIT_ERR = 4


class JvmLoadResult(ByteEnum):
  """android_load_jvm 的返回码（src/injector/injector.h 的 JvmLoadResult）。"""
  JVM_SEND_ERR = 0
  JVM_ARG_ERR = 1
  JVM_NOT_SUPPORT = 2
  JVM_ALREADY_LOADED = 3
  JVM_ART_OPEN_FAIL = 4
  JVM_RUNTIME_OPEN_FAIL = 5
  JVM_SYMBOL_NOT_FOUND = 6
  JVM_CREATE_FAIL = 7
  JVM_FRAMEWORK_NATIVE_FAIL = 8
  JVM_ART_INIT_FAIL = 9
  JVM_AGENT_NOT_FOUND = 10
  JVM_NO_BOOTCLASSPATH = 11
  JVM_LOAD_SUCCESS = 20


class JvmFlag(IntFlag):
  """android_load_jvm 的 flags（include/albatross.h 的 JVM_FLAG_*）。"""
  INTERPRETER_ONLY = 1
  VERBOSE = 2
  CHECK_JNI = 4
  DEBUG = 8
  INIT_AGENT = 16


class InsHookResult(IntEnum):
  HOOK_SUCCESS = 0
  ALREADY_HOOK = 1
  CLASS_NOT_FIND = -1
  METHOD_NOT_FIND = -2
  HOOK_FAIL = -3


class ExecutionOption(IntFlag):
  JIT_OSR = 1
  JIT_BASELINE = 2
  JIT_OPTIMIZED = 4

  DO_NOTHING = 0
  DECOMPILE = 8
  INTERPRETER = DECOMPILE
  DEFAULT_OPTION = 0x10

  RECOMPILE_OSR = JIT_OSR | DECOMPILE
  RECOMPILE_BASELINE = JIT_BASELINE | DECOMPILE
  RECOMPILE_OPTIMIZED = JIT_OPTIMIZED | DECOMPILE
  DISABLE_AOT = 0x20
  DISABLE_JIT = 0x40
  AOT = 0x80
  NATIVE_CODE = AOT | JIT_OPTIMIZED


class MethodScope(IntFlag):
  Static = 1
  Instance = 2
  Constructor = 4


class ShellExecResult(object):

  def __init__(self, exit_code, stdout, stderr):
    self.exit_code = exit_code
    self.stdout = stdout
    self.stderr = stderr

  @staticmethod
  def parse_value(data, result):
    s, _ = read_string(data, 0)
    if s:
      exit_code, stdout_len, shell_str = s.split(':', maxsplit=2)
      stdout_len = int(stdout_len)
      stdout = shell_str[:stdout_len]
      stderr = shell_str[stdout_len + 1:]
      return ShellExecResult(int(exit_code), stdout, stderr)
    return None

  def __repr__(self):
    return f'[{self.exit_code}]{self.stdout}\n{self.stderr}'


class CModuleRunResult(object):
  """cmodule_run / cmodule_call / cmodule_call_v 的结果。

  value 是脚本入口返回的机器字（32 位构建下零扩展为 64 位），output 是脚本写进
  out 缓冲的文本，error 非空表示编译失败或入口符号缺失。out_len 是 output 实际
  字节数；truncated 为真表示 out 缓冲被写满（脚本可能还有更多输出没写进来）——
  此时改用 cmodule_call_v(..., out_size=...) 放大缓冲再调。
  """

  def __init__(self, value, output, error, out_len=0, truncated=False):
    self.value = value
    self.output = output
    self.error = error
    self.out_len = out_len
    self.truncated = truncated

  @staticmethod
  def parse_value(data, result):
    value, idx = read_long(data, 0)
    output, idx = read_string(data, idx)
    error, idx = read_string(data, idx)
    # out_len/truncated 是 P4 追加字段：设备库比本客户端旧时载荷到 error 即止，
    # 此时按 output 长度降级（truncated 未知按 False），不要抛 struct.error
    try:
      out_len, idx = read_long(data, idx)
      truncated, idx = read_long(data, idx)
      out_len, truncated = out_len or 0, bool(truncated)
    except Exception:
      out_len, truncated = len(output or ''), False
    return CModuleRunResult(value, output or '', error or '', out_len, truncated)

  @property
  def ok(self):
    return not self.error

  def __repr__(self):
    return (f'CModuleRunResult(value={self.value}, output={self.output!r}, error={self.error!r}, '
            f'out_len={self.out_len}, truncated={self.truncated})')


class CModuleCompileResult(object):
  """cmodule_compile 的结果；handle 为 0 表示编译失败（原因在 error）。"""

  def __init__(self, handle, error):
    self.handle = handle
    self.error = error

  @staticmethod
  def parse_value(data, result):
    handle, idx = read_long(data, 0)
    error, idx = read_string(data, idx)
    return CModuleCompileResult(handle, error or '')

  @property
  def ok(self):
    return self.handle != 0

  def __repr__(self):
    return f'CModuleCompileResult(handle={self.handle}, error={self.error!r})'


class CModuleIsolatedRunResult(CModuleRunResult):
  """cmodule_run_isolated 的结果：在 CModuleRunResult 之上带子进程侧信息。

  run_ms 子进程实际运行毫秒；term_signal 子进程死亡信号（0 = 正常退出）；
  timed_out 为真表示子进程超时被 SIGKILL 收尸（error 里会说明）。
  崩溃时 error 带信号名/故障地址/PC 符号化/寄存器现场；崩溃前的 output 保留。
  """

  def __init__(self, value, output, error, out_len=0, truncated=False,
      run_ms=0, term_signal=0, timed_out=False):
    super().__init__(value, output, error, out_len, truncated)
    self.run_ms = run_ms
    self.term_signal = term_signal
    self.timed_out = timed_out

  @staticmethod
  def parse_value(data, result):
    base = CModuleRunResult.parse_value(data, result)
    # 尾部三字段：与设备端 alb_cmodule_write_run_isolated_reply 同序。
    # 字段短(极老服务端)时按未知降级，不要抛 struct.error 把结果整段丢掉。
    try:
      _value, idx = read_long(data, 0)
      _output, idx = read_string(data, idx)
      _error, idx = read_string(data, idx)
      _out_len, idx = read_long(data, idx)
      _truncated, idx = read_long(data, idx)
      run_ms, idx = read_long(data, idx)
      term_signal, idx = read_long(data, idx)
      timed_out, idx = read_long(data, idx)
      run_ms, term_signal, timed_out = run_ms or 0, term_signal or 0, bool(timed_out)
    except Exception:
      run_ms, term_signal, timed_out = 0, 0, False
    return CModuleIsolatedRunResult(base.value, base.output, base.error, base.out_len,
        base.truncated, run_ms, term_signal, timed_out)

  def __repr__(self):
    return (f'CModuleIsolatedRunResult(value={self.value}, output={self.output!r}, '
            f'error={self.error!r}, run_ms={self.run_ms}, term_signal={self.term_signal}, '
            f'timed_out={self.timed_out})')


class BaseClient(RpcClient):
  @rpc_api
  def load_lib(self, path: str, entry_symbol: str) -> LoadLibResult:
    pass

  @rpc_api
  def load_jvm(self, libart_path: str = None, classpath: str = None,
      library_path: str = None, flags: JvmFlag = JvmFlag(0)) -> JvmLoadResult:
    """
    在没有 Java VM 的进程里创建 JVM（Android；成功后 load_dex / load_plugin /
    Java hook 等能力才可用）。进程里已有 VM 时返回 JVM_ALREADY_LOADED（幂等）。

    Args:
        libart_path (str): libart 路径，None/空 用设备默认 "libart.so"
        classpath (str): JVM classpath（':' 分隔的 dex/apk/jar 列表），可为 None
        library_path (str): -Djava.library.path（System.loadLibrary 的查找目录），可为 None
        flags (JvmFlag): JVM_FLAG_*：默认解释器执行；INIT_AGENT 会顺带注册
            qing/albatross/core/Albatross 的 native（classpath 里要有该类）

    Returns:
        JvmLoadResult: JVM_LOAD_SUCCESS / JVM_ALREADY_LOADED / 具体失败码
    """

  @rpc_api
  def register_native_handler(self, call_name: str, over_write: bool, lib_path: str, symbol: str, args: str,
      return_type: byte) -> RegisterResult:
    pass

  def register_api(self, cls: RpcClient, name, lib, symbol):
    api_info = cls.register_apis.get(name)
    if not api_info:
      return False
    return self.register_native_handler(name, False, lib, symbol, api_info.args, api_info.ret.encode())

  @rpc_api
  def shell(self, command: str) -> ShellExecResult:
    pass

  @rpc_api(arm=True)
  def cmodule_run(self, source: str, options: str | None = None, entry: str | None = None,
      arg: str | None = None) -> CModuleRunResult:
    """
    在目标进程里现场编译并运行一段 C 源码（tcc，对齐 frida CModule）：编译 → 调用
    入口 → **释放模块**（一次性脚本语义，不留引用）。

    入口约定 `usize alb_main(const char *arg, char *out, int out_size)`（entry 省略
    时就用 "alb_main"）：arg 为字符串入参（结构化数据传 JSON 文本），返回值按机器字
    读（32 位构建下零扩展），文本结果写进 out 回传（默认 8KB，结果里的
    out_len/truncated 给出实际长度与截断标志）。脚本里可直接调用
    albatross.h 的全部 API（AlbDlopen/AlbDlsym/AlbGetModuleBase/AlbStalker*/
    AlbatrossHookFunc 等）与常见 libc 函数；编译期参数用 options（如 "-DFOO=1"）。

    本调用带**默认 30s 非合作式超时**（脚本死循环会被中断并返回 error，不再把
    agent 端点带走）；需要更久的脚本用 cmodule_compile + cmodule_call（可配
    cmodule_set_timeout）。脚本崩溃（SIGSEGV 等）会被框架兜下，error 里带
    信号名/故障地址/PC 符号化/寄存器现场，目标进程不受影响。

    注意：模块运行后会被释放——脚本里装过 hook / 用 AlbatrossRegisterRpcServer 注册过
    RPC / 导出函数之后还要调用，必须改用 cmodule_compile 保活，否则残留引用指向已释放
    的代码页。

    Args:
        source (str): C 源码
        options (str): 附加 tcc 选项（如 "-DFOO=1"），可为 None
        entry (str): 入口符号名，默认 "alb_main"
        arg (str): 传给入口的字符串参数，可为 None/空

    Returns:
        CModuleRunResult: value/output 为脚本结果，error 非空表示编译失败或入口缺失
    """

  @rpc_api(arm=True)
  def cmodule_compile(self, source: str, options: str | None = None) -> CModuleCompileResult:
    """
    编译 C 源码并保留模块句柄（常驻场景：脚本里装 hook、用 AlbatrossRegisterRpcServer
    注册自己的 RPC 方法、之后还要用 cmodule_get_symbol 取多个导出函数来调）。
    相同 (源码, 选项) 命中编译缓存时返回共享句柄（引用计数 +1），每次成功编译都要对应
    一次 cmodule_free；释放前必须先卸载脚本在 C 侧装的 hook。

    Args:
        source (str): C 源码
        options (str): 附加 tcc 选项，可为 None

    Returns:
        CModuleCompileResult: handle 为 0 表示失败（原因在 error）
    """

  @rpc_api(arm=True)
  def cmodule_call(self, handle: long, entry: str | None = None, arg: str | None = None) -> CModuleRunResult:
    """
    调用已编译模块（cmodule_compile 保活）里的导出函数；模块不释放，释放用
    cmodule_free。入口约定与 cmodule_run 相同（`usize alb_main(const char *arg,
    char *out, int out_size)`，entry 省略时用 "alb_main"）。

    用途：脚本里用 AlbatrossRegisterRpcServer(AlbatrossGetRpcServer(), ...) 注册了
    自己的 RPC 方法、或导出多个函数要分多次调用（含安装 hook 的那一次）——一次性
    执行且不保留的脚本直接用 cmodule_run。

    本调用同样受故障守卫（脚本崩在 SIGSEGV 一类信号上返回 error + 现场，目标进程
    不崩），但**默认不带超时**（常驻模块可能就是要长跑）：要防脚本死循环挂死端点，
    先 cmodule_set_timeout(handle, ms)。

    Args:
        handle (int): cmodule_compile 返回的模块句柄
        entry (str): 入口符号名，默认 "alb_main"
        arg (str): 传给入口的字符串参数，可为 None/空

    Returns:
        CModuleRunResult: value/output 为脚本结果，error 非空表示入口缺失等
    """

  @rpc_api
  def cmodule_get_symbol(self, handle: long, name: str) -> long:
    """
    取已编译模块里导出符号（函数或全局变量）的地址；不存在返回 0。

    必须在 cmodule_free 之前调用（释放后模块代码页失效）。

    Returns:
        int: 符号地址（0 = 不存在）
    """

  @rpc_api
  def cmodule_free(self, handle: long) -> bool:
    """
    释放一次模块引用（缓存共享模块在最后一个引用释放时才真正销毁）。

    Returns:
        bool: 句柄非 0 并已释放返回 True
    """

  @rpc_api(arm=True)
  def cmodule_call_v(self, handle: long, entry: str | None = None, args: str | None = None,
      out_size: int = 0) -> CModuleRunResult:
    """调用 argv 形态入口（多参数/大输出）：脚本导出

        long <entry>(const unsigned long *argv, int argc, char *out, int out_size)

    args 传 "0x1234,4096 7" 这类整数表（逗号/空白分隔，0x 前缀与负号可用，最多
    16 个）；out_size=0 用默认 8KB，可放大到 256KB。返回值/输出语义与 cmodule_call
    相同，另外 result.out_len / result.truncated 给出实际长度与截断标志。

    Args:
        handle (int): cmodule_compile 返回的模块句柄
        entry (str): 入口符号名，默认 "alb_main_v"
        args (str): 整数参数表，可为 None/空
        out_size (int): out 缓冲大小，0 = 默认 8KB
    """

  @rpc_api
  def cmodule_layout(self, handle: long) -> str:
    """模块台账（P0 崩溃归因）：一行头部（cmodule#id / handle / 源码哈希 / 引用数 /
    备注 / 代码页区间）+ 逐区间一行 + 导出符号表（name +0x偏移）。
    tombstone/backtrace 里的 PC 用 cmodule_symbolize 或对着这里的区间+符号离线归因。"""

  @rpc_api
  def cmodule_list(self) -> str:
    """存活模块清单（P1 盘点）：每模块一行头部（不含符号表）。用于跨会话接手时
    查"进程里现在有哪些脚本、谁装的（note）、还被引用几次"。"""

  @rpc_api
  def cmodule_source(self, handle: long) -> str:
    """模块源码回读（P1）：编译时保存的源码副本（释放前有效）。别人装的脚本也
    能读懂它在干什么。"""

  @rpc_api
  def cmodule_symbols(self, handle: long) -> str:
    """模块导出符号表文本（P1）："name +0x偏移" 每行一个（tcc 内部段边界符号已滤），
    取地址仍用 cmodule_get_symbol。"""

  @rpc_api
  def cmodule_capabilities(self) -> str:
    """内置能力清单（P1）：构建模式（libc/nolibc、是否有 dlsym 兜底）、入口约定、
    虚拟头清单、框架 API 名、内置 libc 符号名——写脚本前查它，不用试错。"""

  @rpc_api
  def cmodule_annotate(self, handle: long, note: str | None = None) -> bool:
    """给模块写备注（属主/用途，P1）：多会话/多 agent 并发时靠它互相识别，
    cmodule_list / cmodule_layout 会带出来。传 None/空清除。"""

  @rpc_api
  def cmodule_audit(self, handle: long) -> str:
    """引用审计（P5）：代码页里是否还挂着 hook 回调 / 延迟钩 / 已注册 RPC 方法。
    返回文本含 mask=<位掩码>（1=hook、2=延迟钩、4=RPC；mask=0 表示干净）与明细。
    free 前查一次，避免"释放后回调悬空"。"""

  @rpc_api
  def cmodule_cancel(self, handle: long) -> bool:
    """合作式取消（P3）：置位模块的取消标志。脚本在长循环里调
    AlbatrossCModuleCheckpoint()（返回 1 即该退出）——脚本不调检查点则无法打断。"""

  @rpc_api
  def cmodule_deadline(self, handle: long, ms: int) -> bool:
    """给模块设软死线（P3）：毫秒，<=0 清除。脚本的 AlbatrossCModuleCheckpoint()
    超时后返回 2。与取消一样是合作式（脚本需按返回值退出）。"""

  @rpc_api(arm=True)
  def cmodule_set_timeout(self, handle: long, ms: int) -> bool:
    """给模块设**非合作式**运行超时（毫秒，<=0 关闭）：对之后每次 cmodule_call /
    cmodule_call_v 生效，到点由框架中断该次调用并返回错误（脚本不必自己调
    Checkpoint）——脚本死循环不再把 RPC 端点带走。

    与合作式的 cmodule_deadline 互补：deadline 要脚本主动查询，本超时由框架强制
    打断（best-effort：跳出点可能在任意指令上，故障后模块标记 faulted 并从编译
    缓存剔除，建议重新编译再跑）。cmodule_run 由 RPC 侧默认带 30s 超时；
    cmodule_call/cmodule_call_v 默认不设，需要时用本方法打开。"""

  @rpc_api(arm=True)
  def cmodule_run_isolated(self, source: str, options: str | None = None, entry: str | None = None,
      arg: str | None = None, timeout_ms: long = 0, out_size: long = 8192) -> CModuleIsolatedRunResult:
    """隔离执行（一次性脚本的"试跑"通道）：fork 一个子进程，在子进程里跑
    alb_module_init(若有) -> 入口(默认 alb_main) -> alb_module_fini(若有)，父进程
    等它结束（超时 SIGKILL 收尸）。

    - 脚本崩溃：目标进程不受影响，返回错误（error 带信号名/故障地址/PC 符号化/
      寄存器现场），崩溃前的 output 保留在 result.output；
    - 脚本死循环：到点杀掉子进程，result.timed_out 为真；
    - 副作用隔离：脚本的内存写入只落在子进程副本 —— **装 hook / 改目标内存这类
      脚本在隔离模式里不会对目标进程生效**：验证逻辑/查内存用本方法，要改状态
      用 cmodule_compile + cmodule_call。

    timeout_ms <= 0 用默认 30s，上限 60s（本调用同步占用 agent 循环线程）。

    Args:
        source (str): C 源码（父进程侧编译，编译错误直接返回）
        options (str): 附加 tcc 选项，可为 None
        entry (str): 入口符号名，默认 "alb_main"
        arg (str): 传给入口的字符串参数，可为 None
        timeout_ms (int): 子进程超时（毫秒），0 = 默认 30s
        out_size (int): out 缓冲大小，默认 8KB（上限 256KB）

    Returns:
        CModuleIsolatedRunResult: value/output 为脚本结果，另带 run_ms/term_signal/timed_out
    """

  @rpc_api
  def cmodule_symbolize(self, addr: long) -> str:
    """地址 -> "cmodule#id 符号+0x偏移"（P0）：把 tombstone/backtrace 里的 PC 归因
    到脚本符号；不在任何存活模块内返回 "not in any cmodule: 0x.."。"""

  @rpc_api
  def find_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> str:
    pass

  @rpc_api(arm=True)
  def hook_method(self, class_name: str, method_name: str, num_args: int, args: str = None,
      min_dex_pc: int = 0, max_dex_pc: int = 128, safe_string: bool = False) -> InsHookResult:
    """
    钩子方法，用于拦截和修改方法调用

    Args:
        class_name (str): 类名
        method_name (str): 方法名
        num_args (int): 参数数量
        args (str): 参数信息
        min_dex_pc (int): 最小的DEX程序计数器
        max_dex_pc (int): 最大的DEX程序计数器
        safe_string(bool): 参数是否可以安全的转换成字符串

    Returns:
        int: 监听器ID
    """

  @rpc_api
  def unhook_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> bool:
    """
    取消方法钩子

    Returns:
        bool: 是否成功取消钩子
    """

  @rpc_api(arm=True)
  def dyn_hook_method(self, class_name: str, method_name: str, num_args: int, args: str = None,
      safe_string: bool = False) -> InsHookResult:
    """
    免签名动态 hook 单个方法（trampoline 路线，不去优化；beforeCall/afterCall
    两段式日志：Enter 记录参数与调用栈、Leave 记录返回值）。构造器不支持。

    Returns:
        InsHookResult: 与 hook_method 相同的状态码
    """

  @rpc_api(arm=True)
  def dyn_hook_method_return(self, class_name: str, method_name: str, num_args: int, args: str = None,
      result_value: str = None) -> InsHookResult:
    """
    动态 hook 并跳过原方法、返回固定值。result_value 按目标方法返回类型解析：
    基本类型按字面量、String 原样、"null" 或其它引用类型返回 null、void 仅跳过。

    Returns:
        InsHookResult: 与 hook_method 相同的状态码
    """

  @rpc_api
  def dyn_unhook_method(self, class_name: str, method_name: str, num_args: int, args: str = None) -> bool:
    """
    取消 dyn_hook_method / dyn_hook_method_return 安装的动态 hook

    Returns:
        bool: 是否成功取消
    """

  @rpc_api(arm=True)
  def dyn_hook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance,
      safe_string: bool = False) -> str:
    """
    免签名动态 hook 整个类（scope 同 hook_class；构造器位当前不支持会被忽略）。
    返回成功 hook 的方法描述（";"分隔）。
    """

  @rpc_api
  def dyn_unhook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance) -> str:
    """
    取消 dyn_hook_class 安装的动态 hook（scope 同 hook_class）
    """

  @rpc_api(arm=True)
  def hook_events_enable(self, max_records: int = 0) -> bool:
    """
    开启 hook 命中记录（结构化取数通道）：之后 hook_method/dyn_hook_method/
    hook_class/dyn_hook_class 的每次命中写进进程内环形缓冲，用 hook_events_pull 拉取。

    Args:
        max_records (int): 环容量（条）：>0 设置容量并开启，0 用默认（4096）并开启，
            <0 关闭。换容量会清空已积累记录。
    """

  @rpc_api
  def hook_events_status(self) -> str:
    """命中记录状态（JSON）：enabled/capacity/appended/dropped/next_seq/readable"""
    pass

  @rpc_api
  def hook_events_pull(self, cursor: long = 0, max_bytes: int = 0) -> str:
    """
    拉取 cursor 之后的命中记录。返回首行 "#{" 开头的游标元信息
    （first_seq/next_seq/dropped/capacity/skipped），随后每行一条 JSON 记录
    （seq/ts/tid/thread/kind/phase/method/this/args/ret）。
    用 parse_hook_events 解析；max_bytes>0 按行边界截断。
    """
    pass

  @rpc_api
  def hook_events_clear(self) -> bool:
    """清空已积累的命中记录（游标不回退）"""
    pass

  def hook_events(self, cursor: long = 0, max_bytes: int = 0):
    """便捷拉取：返回 (记录列表, 新游标)；配合循环可实现持续拉取。

    示例::

        cursor = 0
        while True:
            events, cursor = client.hook_events(cursor)
            for e in events:
                print(e)
            if not events:
                break
    """
    return parse_hook_events(self.hook_events_pull(cursor, max_bytes))

  @rpc_api
  def getuid(self) -> int:
    """
    获取当前进程的用户ID

    Returns:
        int: 用户ID
    """

  @rpc_api
  def decompile_all(self) -> void:
    pass

  @rpc_api
  def print_all_class_loader(self) -> str:
    pass

  @rpc_api
  def dump_all_threads(self) -> str:
    pass

  @rpc_api
  def find_class(self, cls_name: str, application: bool = True,
      exec_mode: ExecutionOption = ExecutionOption.DO_NOTHING) -> str:
    pass

  @rpc_api
  def find_sub_class(self, cls_name: str, application: bool = True) -> str:
    pass

  @rpc_api(arm=True)
  def hook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance,
      safe_tostring: bool = False) -> str:
    pass

  @rpc_api
  def unhook_class(self, class_name: str, application: bool = True, scope: MethodScope = MethodScope.Instance) -> str:
    pass

  @rpc_api
  def get_functions(self, lib_path: str) -> list:
    pass

  @rpc_api
  def set_to_string_config(self, max_length: int, show_bytes: bool = True) -> void:
    pass

  @rpc_api
  def read_file(self, path: str) -> str:
    pass

  @rpc_api
  def get_class_methods(self, cls_name: str, application: bool) -> str:
    pass

  @rpc_api
  def get_class_fields(self, cls_name: str, application: bool) -> str:
    pass

  def read_maps(self):
    return self.read_file('/proc/self/maps')

  def read_smaps(self):
    return self.read_file('/proc/self/smaps')
