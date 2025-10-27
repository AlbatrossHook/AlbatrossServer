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

  byte deletePlugin(int pluginId);

  boolean deletePluginRule(int pluginId, int appId);

  byte addPluginRule(int pluginId, int appId);

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
