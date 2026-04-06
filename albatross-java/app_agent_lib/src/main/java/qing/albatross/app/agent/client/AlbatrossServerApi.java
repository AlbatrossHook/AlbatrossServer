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

public interface AlbatrossServerApi {

  byte getProcessIsa(int pid);


  byte getServiceIsa();

  int getProcessPid(String processName);

  byte injectAlbatross(int pid, int flags, String tempDir);

  boolean set_2ndArchLib(String libPath);

  boolean setArchLib(String libPath);


  byte loadPlugin(int pid, String appAgentDex, String agentLib, String albatrossClass, String agentClass,
                  String agentRegisterFunc, int albatrossInitFlags, String pluginDex, String pluginLib, String pluginClass,
                  String argString, int argInt);

  byte loadDex(int pid, String dexPath, String libPath, String registerClass, String className, String loaderFunc, int albatrossInitFlags, String param1, int param2);

  byte registerPlugin(int pluginId, String pluginDex, String pluginLib, String pluginClass, String param1, int param2);

  byte modifyPlugin(int pluginId, String pluginClass, String param1, int param2);

  byte deletePlugin(int pluginId,boolean affectExist);

  boolean deletePluginRule(int pluginId, int appId);

  byte addPluginRule(int pluginId, int appId, String process);

  void setAppInfo(int uid, String info);

  byte disablePlugin(int pid, int pluginId);

  byte setAppAgent(String agentDex, String agentLib, String albatrossClass, String agentClass, String registerFunc, int albatrossInitFlags);

  byte setSystemServerAgent(String agentDex, String agentClass, String serverName, int albatrossInitFlags, String serverAddress, int initFlags);


  boolean removePlugin(int uid, String pluginDex);

  boolean patchSelinux();

  boolean isInjected();

  int getTid();

  void stop();

  byte loadSystemPlugin(String pluginDex, String pluginLib, String pluginCLass, String pluginParams, int pluginFlags);


  String shell(String command);

  String uidProcesses(int uid, boolean onlyJava);

  boolean isLsposedInjected();

}
