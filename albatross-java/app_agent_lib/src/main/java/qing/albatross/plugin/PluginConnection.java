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

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import qing.albatross.app.agent.AppInjectAgent;
import qing.albatross.app.agent.client.AlbatrossClient;
import qing.albatross.app.agent.client.Const;
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

  private PluginConnection(AlbatrossClient client) {
    this.client = client;
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
      appApgAgentDex = agentDex;
      systemAppAgentDex = systemAgent;
      client1.setAppAgent(agentDex, null, Albatross.class.getName(), AppInjectAgent.class.getName(), "albatross_load_init", Albatross.FLAG_INJECT | Albatross.FLAG_INIT_RPC);
      client1.setSystemServerAgent(systemAgent, SYSTEM_SERVER_ENTRY, "system_server", 0, null, 3);
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
      int ret = client.injectAlbatross(pid, 0x10 | 0x20, null);
      if (ret < 0)
        return -1;
      return client.loadPlugin(pid, appApgAgentDex, null, Albatross.class.getName(),
          AppInjectAgent.class.getName(), "albatross_load_init", albatrossInitFlags,
          pluginDex, null, pluginClass, param1, param2);
    }
    return -2;
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
        return client.addPluginRule(pluginId, Const.SYSTEM_UID);
      } else {
        ApplicationInfo applicationInfo = Albatross.currentApplication().getPackageManager().getApplicationInfo(pkg, 0);
        int uid = applicationInfo.uid;
        return client.addPluginRule(pluginId, uid);
      }
    } catch (PackageManager.NameNotFoundException e) {
      return 0;
    }
  }


  public byte deletePlugin(int pluginId) {
    return client.deletePlugin(pluginId);
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

  public boolean isLsposedInjected(){
    return client.isLsposedInjected();
  }

}
