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
package qing.albatross.app.agent.client;

import qing.albatross.server.UnixRpcClientInstance;

public class AlbatrossClient extends UnixRpcClientInstance implements AlbatrossServerApi {
  @Override
  native public byte getProcessIsa(int pid);

  @Override
  native public byte getServiceIsa();

  @Override
  native public int getProcessPid(String processName);

  @Override
  native public byte injectAlbatross(int pid, int flags, String tempDir);

  @Override
  native public boolean set_2ndArchLib(String libPath);

  @Override
  native public boolean setArchLib(String libPath);

  @Override
  native public byte loadPlugin(int pid, String appAgentDex, String agentLib, String albatrossClass, String agentClass, String agentRegisterFunc, int dexFlag, String pluginDex, String pluginLib, String pluginClass, String argString, int argInt);

  @Override
  native public byte loadDex(int pid, String dexPath, String libPath, String registerClass, String className, String loaderFunc, int loadDexFlag, String param1, int param2);

  @Override
  public native byte registerPlugin(int pluginId, String pluginDex, String pluginLib, String pluginClass, String param1, int param2);

  @Override
  public native byte modifyPlugin(int pluginId, String pluginClass, String param1, int param2);

  @Override
  public native byte deletePlugin(int pluginId,boolean affectExist);

  @Override
  public native boolean deletePluginRule(int pluginId, int appId);

  @Override
  public native byte addPluginRule(int pluginId, int appId, String process);

  @Override
  public native void setAppInfo(int uid, String info);

  @Override
  public native byte disablePlugin(int pid, int pluginId);


  @Override
  public native byte loadSystemPlugin(String pluginDex, String pluginLib, String pluginClass, String param1, int param2);

  @Override
  public native String shell(String command);

  @Override
  public native String uidProcesses(int uid, boolean onlyJava);

  @Override
  public native boolean isLsposedInjected();

  @Override
  public native byte setAppAgent(String agentDex, String agentLib, String albatrossClass, String agentClass, String registerFunc, int albatrossInitFlags);

  @Override
  public native byte setSystemServerAgent(String agentDex, String agentClass, String serverName, int albatrossInitFlags, String serverAddress, int initFlags);

  @Override
  public native boolean removePlugin(int uid, String pluginDex);

  @Override
  native public boolean patchSelinux();

  @Override
  native public boolean isInjected();

  @Override
  native public int getTid();

  @Override
  public native void stop();

  @Override
  protected Class<?> getApi() {
    return AlbatrossServerApi.class;
  }

  @Override
  public void close() {
    super.close();
  }

  public ShellExecResult execShell(String command) throws DisconnectException {
    if (getTid() == 0) {
      close();
      throw new DisconnectException();
    }
    String s = shell(command);
    if (s == null)
      return null;
    int idx = s.indexOf(':');
    int exitCode = Integer.parseInt(s.substring(0, idx));
    int idx2 = s.indexOf(':', idx + 1);
    int stdoutLen = Integer.parseInt(s.substring(idx + 1, idx2));
    int idx3 = idx2 + 1 + stdoutLen;
    String stdout = s.substring(idx2 + 1, idx3);
    String stderr = s.substring(idx3 + 1);
    return new ShellExecResult(exitCode, stdout, stderr);
  }
}
