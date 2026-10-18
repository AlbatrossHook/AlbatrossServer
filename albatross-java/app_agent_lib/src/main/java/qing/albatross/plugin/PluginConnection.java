/*
 * Copyright 2025 QingWan (qingwanmail@foxmail.com)
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package qing.albatross.plugin;

import static qing.albatross.app.agent.client.Const.MISS_INFO;

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import qing.albatross.app.agent.client.AlbatrossClient;
import qing.albatross.app.agent.client.Const;
import qing.albatross.app.agent.AppInjectAgent;
import qing.albatross.app.agent.client.DisconnectException;
import qing.albatross.app.agent.client.ShellExecResult;
import qing.albatross.core.Albatross;

public class PluginConnection {

  public static final String SYSTEM_SERVER_ENTRY = "qing.albatross.android.system_server.SystemServerInjectAgent";


  AlbatrossClient client;
  static PluginConnection instance;

  static String appApgAgentDex;
  static String systemAppAgentDex;
  static int albatrossInitFlags = 0;
  static int injectFlags = Const.INJECT_DEFAULT;

  private PluginConnection(AlbatrossClient client) {
    this.client = client;
  }

  /**
   * 设置注入目标进程时使用的 albatross init flags（如 FLAG_DISABLE_JIT、FLAG_ANTI_DETECTION）。
   * 只影响之后创建的连接与之后发起的注入。
   */
  public static void setInitFlags(int flags) {
    albatrossInitFlags = flags;
  }

  public static int getInitFlags() {
    return albatrossInitFlags;
  }

  /**
   * 设置注入方式flag（INJECT_KEEP/INJECT_UNIX/INJECT_MEMFD），同时下发给服务端作为后续
   * launch(规则)注入的默认值。只影响之后发起的注入。
   */
  public static void setInjectFlags(int flags) {
    injectFlags = flags;
  }

  public static int getInjectFlags() {
    return injectFlags;
  }

  public static PluginConnection create(String serverPath, String secondLibrary, String agentDex, String systemAgent) {
    if (instance != null)
      return instance;
    AlbatrossClient client1 = new AlbatrossClient();
    if (client1.createClient(serverPath, true) != null) {
      instance = new PluginConnection(client1);
      if (secondLibrary != null) {
        client1.set_2ndArchLib(secondLibrary);
      }
      client1.patchSelinux();
      try {
        //旧服务端可能没有该 handler，注册失败时该 native 方法不可调用，不能影响连接建立
        client1.setInjectFlags(injectFlags, null);
      } catch (Throwable e) {
        Albatross.log("set inject flags fail:" + e);
      }
      appApgAgentDex = agentDex;
      systemAppAgentDex = systemAgent;
      client1.setAppAgent(agentDex, null, Albatross.class.getName(), AppInjectAgent.class.getName(), "albatross_load_init", Albatross.FLAG_INJECT | Albatross.FLAG_INIT_RPC | albatrossInitFlags);
      client1.setSystemServerAgent(systemAgent, SYSTEM_SERVER_ENTRY, "system_server", albatrossInitFlags, null, 3);
      int client1Tid = client1.getTid();
      if (client1Tid > 0)
        return instance;
      client1.close();
      instance = null;
    }
    return null;
  }

  public int doInject(String pkg, String pluginDex, String pluginClass, String param1, int param2) {
    int pid = client.getProcessPid(pkg);
    if (pid > 0) {
      String tempDir = null;
      if ((injectFlags & Const.INJECT_MEMFD) != 0) {
        //memfd 注入需要临时目录名，由服务端在目标进程内创建
        tempDir = appApgAgentDex != null ? appApgAgentDex.substring(0, appApgAgentDex.lastIndexOf('/') + 1) : null;
      }
      int ret = client.injectAlbatross(pid, injectFlags, tempDir);
      if (ret < 0)
        return -1;
      return client.loadPlugin(pid, appApgAgentDex, null, Albatross.class.getName(),
          AppInjectAgent.class.getName(), "albatross_load_init", albatrossInitFlags,
          pluginDex, null, pluginClass, param1, param2);
    }
    return -2;
  }

  /**
   * 在已建立的连接上重新下发 agent/flags，不重连（运行选项变化时用；
   * 服务端只在路径变化时才重新注入 system_server）。
   */
  public void pushFlags() {
    client.setAppAgent(appApgAgentDex, null, Albatross.class.getName(), AppInjectAgent.class.getName(),
        "albatross_load_init", Albatross.FLAG_INJECT | Albatross.FLAG_INIT_RPC | albatrossInitFlags);
    client.setSystemServerAgent(systemAppAgentDex, SYSTEM_SERVER_ENTRY, "system_server", albatrossInitFlags,
        null, 3);
    try {
      client.setInjectFlags(injectFlags, null);
    } catch (Throwable e) {
      Albatross.log("set inject flags fail:" + e);
    }
  }

  /**
   * 内核模块隐藏（rwbp）：隐藏 agent dex/lib 等路径并对 libart/libc 做 smaps 归零。
   * 需要设备已加载 rwbp.ko，开启后不可撤销，返回是否可用。
   */
  public boolean supportExtendKpm() {
    return client.supportExtendKpm();
  }

  /**
   * 下发注入方式flag到服务端（作为后续 launch 注入的默认值），返回服务端是否接受
   */
  public boolean pushInjectFlags(int flags, String tempPath) {
    injectFlags = flags;
    return client.setInjectFlags(flags, tempPath);
  }


  public byte loadSystemPlugin(String pluginDex, String pluginClass, String param1, int param2) {
    return client.loadSystemPlugin(pluginDex, null, pluginClass, param1, param2);
  }


  public byte registerPlugin(int pluginId, String pluginDex, String pluginClass, String param1, int param2) {
    return client.registerPlugin(pluginId, pluginDex, null, pluginClass, param1, param2);
  }

  public byte modifyPlugin(int pluginId, String pluginClass, String param1, int param2) {
    return client.modifyPlugin(pluginId, pluginClass, param1, param2);
  }

  public boolean deletePluginRule(int pluginId, String pkg) {
    try {
      if (Const.PKG_SYSTEM_SERVER.equals(pkg))
        return client.deletePluginRule(pluginId, Const.SYSTEM_UID);
      PackageInfo packageInfo = Albatross.currentApplication().getPackageManager().getPackageInfo(pkg, 0);
      int uid = packageInfo.applicationInfo.uid;
      return client.deletePluginRule(pluginId, uid);
    } catch (PackageManager.NameNotFoundException e) {
      return false;
    }
  }

  public byte addPluginRule(int pluginId, String pkg) {
    try {
      if (Const.PKG_SYSTEM_SERVER.equals(pkg)) {
        return client.addPluginRule(pluginId, Const.SYSTEM_UID, null);
      } else {
        ApplicationInfo applicationInfo = Albatross.currentApplication().getPackageManager().getApplicationInfo(pkg, 0);
        int uid = applicationInfo.uid;
        byte res;
        if (Const.SYSTEM_UID == uid) {
          res = client.addPluginRule(pluginId, uid, pkg);
        } else {
          res = client.addPluginRule(pluginId, uid, null);
        }
        if (res == MISS_INFO) {
          PackageInfo packageInfo = Albatross.currentApplication().getPackageManager().getPackageInfo(pkg, 0);
          int versionCode = packageInfo.versionCode;
          String extraInfo = pkg + ":" + versionCode;
          client.setAppInfo(applicationInfo.uid, extraInfo);
          res = 0;
        }
        return res;
      }
    } catch (PackageManager.NameNotFoundException e) {
      return 0;
    }
  }


  public byte deletePlugin(int pluginId) {
    return client.deletePlugin(pluginId, false);
  }

  public void setAppInfo(int uid, String extraInfo) {
    client.setAppInfo(uid, extraInfo);
  }

  public void stopServer() {
    client.stop();
    client.close();
    instance = null;
  }

  public boolean isClosed() {
    return client.isClosed();
  }

  public ShellExecResult shell(String command) throws DisconnectException {
    return client.execShell(command);
  }

  public String getPackageProcess(String targetPackage) throws PackageManager.NameNotFoundException {
    ApplicationInfo applicationInfo = null;
    int uid;
    if (Const.PKG_SYSTEM_SERVER.equals(targetPackage))
      uid = Const.SYSTEM_UID;
    else {
      applicationInfo = Albatross.currentApplication().getPackageManager().getApplicationInfo(targetPackage, 0);
      uid = applicationInfo.uid;
    }
    return client.uidProcesses(uid, false);
  }

  public void disconnection() {
    client.close();
    instance = null;
  }

  public boolean isLsposedInjected() {
    return client.isLsposedInjected();
  }

}
