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
package qing.albatross.android.system_server;

import static android.os.Process.SYSTEM_UID;
import static qing.albatross.agent.Const.DEX_LOAD_FAIL;
import static qing.albatross.agent.Const.FLAG_LOG;

import android.annotation.SuppressLint;
import android.app.ActivityManager;
import android.app.AppOpsManager;
import android.app.Application;
import android.content.ComponentName;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.os.Binder;
import android.os.Build;
import android.os.IInterface;
import android.os.UserHandle;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.agent.DynamicPluginManager;
import qing.albatross.agent.PluginMessage;
import qing.albatross.common.AppMetaInfo;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.server.JsonFormatter;
import qing.albatross.server.UnixRpcInstance;
import qing.albatross.server.UnixRpcServer;


public class SystemServerInjectAgent extends UnixRpcInstance implements SystemServerApi {

  public static final int AGENT_VERSION = 1;

  public static final String NO_FILTER = ":A";
  public static final String SPLIT = ":";

  static Map<Integer, String> interceptApps = new HashMap<>();

  static Map<Integer, String> watchApps = new HashMap<>();
  static boolean interceptAll = false;

  public static String shouldInterceptUid(int callingUid) {
    if (interceptAll)
      return NO_FILTER;
    return interceptApps.get(callingUid);
  }


  public String launcherApp;
  public static final String STRING_SUCCESS = "success";
  Application context;
  Context contextImpl;
  ActivityManager activityManager;

  @Override
  protected Class<?> getApi() {
    return SystemServerApi.class;
  }

  static class SingletonHolder {
    @SuppressLint("StaticFieldLeak")
    static SystemServerInjectAgent instance = new SystemServerInjectAgent();
  }


  public static SystemServerInjectAgent v() {
    return SingletonHolder.instance;
  }

  private SystemServerInjectAgent() {
  }

  public static boolean loadLibrary(String libpath, int albatrossInitFlags, String p1, int p2) {
    try {
      if (Albatross.loadLibrary(libpath, albatrossInitFlags & 0xffff))
        Albatross.initRpcClass(UnixRpcServer.class);
      SystemServerInjectAgent server = SystemServerInjectAgent.v();
      UnixRpcServer unixRpcServer = server.createServer(p1, true);
      AppMetaInfo.versionCode = Build.VERSION.SDK_INT;
      AppMetaInfo.packageName = "system_server";
      if (unixRpcServer != null) {
        server.context = Albatross.currentApplication();
        if ((albatrossInitFlags & FLAG_LOG) != 0) {
          try {
            PluginMessage.setMessageSender(server);
          } catch (Exception e) {
            throw new RuntimeException(e);
          }
        } else {
          PluginMessage.registerPluginMethod();
        }
        if ((p2 & 1) != 0) {
          if (!server.init())
            return false;
          if ((p2 & 2) != 0)
            server.initIntercept();
          return server.isInit;
        }
        return true;
      }
      return false;
    } catch (Exception e) {
      return false;
    }
  }


  @SuppressLint("MissingPermission")
  @Override
  public boolean setTopApp(String pkgName) {
    List<ActivityManager.RunningTaskInfo> runningTaskInfos = activityManager.getRunningTasks(100);

    for (ActivityManager.RunningTaskInfo taskInfo : runningTaskInfos) {
      //找到本应用的 task，并将它切换到前台
      ComponentName topActivity = taskInfo.topActivity;
      if (topActivity == null)
        continue;
      if (pkgName.equals(topActivity.getPackageName())) {
        activityManager.moveTaskToFront(taskInfo.id, 0);
        return true;
      }
    }
    return false;
  }

  @Override
  public boolean setInterceptAll(boolean intercept) {
    return interceptAll = intercept;
  }

  boolean isInit = false;


  @Override
  public String getFrontActivity() {
    ComponentName componentName = getFrontActivityComponent();
    if (componentName == null)
      return null;
    Object[] result = new Object[]{componentName.getPackageName(), componentName.getClassName(), getAppProcessList()};
    return JsonFormatter.fmt(result);
  }

  @Override
  public String getFrontActivityQuick() {
    ComponentName componentName = getFrontActivityComponent();
    return JsonFormatter.fmt(new Object[]{componentName.getPackageName(), componentName.getClassName()});
  }


  @Override
  public native byte launchProcess(int uid, int pid, String pkg, String processName, String data);


  public void notifyProcessLaunch(int uid, int pid, String pkg, String processName, String data) {
    byte ret = launchProcess(uid, pid, pkg, processName, data);
    if (ret == -1) {
      removeIntercept(uid, pkg);
    }
  }


  @Override
  public String getTargetProcess(String pkgName) {
    ComponentName topActivity = getFrontActivityComponent();
    if (topActivity == null)
      return null;
    StringBuilder builder = new StringBuilder();
    builder.append(topActivity.getPackageName()).append(",").append(topActivity.getClassName());
    builder.append("|");
    List<ActivityManager.RunningAppProcessInfo> appProcessInfos = activityManager.getRunningAppProcesses();
    for (ActivityManager.RunningAppProcessInfo info : appProcessInfos) {
      for (String pkg : info.pkgList) {
        if (pkg.equals(pkgName)) {
          builder.append(info.pid + ":" + info.importance + ":" + info.processName);
          ComponentName componentName = info.importanceReasonComponent;
          if (componentName != null) {
            builder.append(":" + componentName.getPackageName() + "/" + componentName.getClassName());
          }
          builder.append("&");
          break;
        }
      }
    }
    return builder.toString();
  }

  public ComponentName getFrontActivityComponent() {
    List<ActivityManager.RunningTaskInfo> runningTaskInfos = activityManager.getRunningTasks(1);
    if (runningTaskInfos.isEmpty())
      return null;
    ActivityManager.RunningTaskInfo taskInfo = runningTaskInfos.get(0);
    return taskInfo.topActivity;
  }


  @Override
  public String getTopActivity(boolean isDetail) {
    ComponentName topActivity = getFrontActivityComponent();
    if (topActivity == null)
      return null;
    StringBuilder builder = new StringBuilder();
    builder.append(topActivity.getPackageName()).append(",").append(topActivity.getClassName());
    try {
      if (isDetail) {
        builder.append("|");
        List<ActivityManager.RunningAppProcessInfo> appProcessInfos = activityManager.getRunningAppProcesses();
        for (ActivityManager.RunningAppProcessInfo info : appProcessInfos) {
          for (String pkg : info.pkgList) {
            if (pkg.equals(topActivity.getPackageName())) {
              builder.append(info.pid + ":" + info.importance + ":" + info.processName);
              builder.append("&");
              break;
            }
          }
        }
      }
    } catch (Exception e) {
      Albatross.log("getTopActivity", e);
    }
    return builder.toString();
  }

  @Override
  public String getLaunchPackage() {
    if (launcherApp != null)
      return launcherApp;
    Intent intent = new Intent();
    intent.addCategory(Intent.CATEGORY_HOME);
    List<ResolveInfo> resolveInfos = context.getPackageManager().queryIntentActivities(intent, 0);
    if (resolveInfos.isEmpty())
      return "";
    launcherApp = resolveInfos.get(0).activityInfo.packageName;
    return launcherApp;
  }


  @Override
  public String getAllProcesses() {
    Object[][] result = getAppProcessList();
    return JsonFormatter.fmt(result);
  }

  private Object[][] getAppProcessList() {
    List<ActivityManager.RunningAppProcessInfo> processes = activityManager.getRunningAppProcesses();
    Object[][] result = new Object[processes.size()][];
    for (int i = 0; i < processes.size(); i++) {
      ActivityManager.RunningAppProcessInfo process = processes.get(i);
      result[i] = new Object[]{process.pid, process.uid, process.importance, process.processName, process.pkgList};
    }
    return result;
  }

  @Override
  public String startActivity(String pkgName, String activity, int uid) {
    UserHandle user;
    Context ctx;
    PackageManager pm;
    if (uid != 0) {
      user = UserHandleH.of(uid);
      ctx = ContextImplH.createPackageContextAsUser(contextImpl, pkgName, 0, user);
      pm = ctx.getPackageManager();
    } else {
      user = null;
      pm = context.getPackageManager();
      ctx = context;
    }
    Intent intent = pm.getLaunchIntentForPackage(pkgName);
    if (intent == null) {
      intent = pm.getLeanbackLaunchIntentForPackage(pkgName);
    }
    if (intent == null) {
      if (activity == null)
        return "Unable to find a front-door activity for " + pkgName;
      intent = new Intent();
      intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }
    if (activity != null) {
      intent.setClassName(pkgName, activity);
    }
    if (user != null) {
      ContextWrapper contextWrapper = new ContextWrapper(ctx);
      ContextWrapperH.startActivityAsUser(contextWrapper, intent, user);
    } else {
      ctx.startActivity(intent);
    }
    return STRING_SUCCESS;
  }

  @Override
  public String sendBroadcast(String pkgName, String receiver, String action, int uid) {
    Intent intent = new Intent();
    intent.setComponent(new ComponentName(pkgName, receiver));
    intent.setAction(action);
    context.sendBroadcast(intent);
    return STRING_SUCCESS;
  }


  @Override
  public int initIntercept() {
    if (isInit)
      return -1;
    int count = 0;
    try {
      int level = Albatross.transactionBegin();
      assert level == 1;
      count += Albatross.hookClass(ActivityManagerServiceH.PidMapH.class);
      count += Albatross.hookClass(ActivityManagerServiceH.class);
      if (count > 0)
        isInit = true;
    } catch (AlbatrossErr e) {
      Albatross.log("initIntercept", e);
      return 0;
    } finally {
      Albatross.transactionEnd(isInit, false);
    }
    return count;
  }


  @Override
  public boolean init() {
    if (activityManager != null)
      return true;
    try {
      Albatross.transactionBegin();
      Albatross.hookClass(ProcessRecordH.class);
      if (ProcessRecordH.hostingNameStr == null) {
        if (Build.VERSION.SDK_INT >= 29) {
          Albatross.hookClass(HostingRecordH.class);
          if (ProcessRecordH.hostingRecord == null) {
            ProcessRecordH.hostingRecord = ProcessRecordH.mHostingRecord;
          }
        }
      } else {
        Albatross.log("android old version which not have HostingRecord");
      }
      if (Albatross.hookClass(ContextImplH.class) <= 0)
        return false;
      if (Albatross.hookClass(UserHandleH.class) <= 0)
        return false;
      if (Albatross.hookClass(ContextWrapperH.class) <= 0)
        return false;
      if (Albatross.hookClass(ActivityManagerH.class) <= 0)
        return false;
      context = Albatross.currentApplication();
      activityManager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
      return true;
    } catch (AlbatrossErr e) {
      Albatross.log("init server", e);
      return false;
    } finally {
      Albatross.transactionEnd(context != null, false);
    }
  }


  @Override
  public int setInterceptApp(String pkg, boolean clear) {
    try {
      if (clear)
        interceptApps.clear();
      if (pkg == null)
        return 0;
      if ("all".equals(pkg)) {
        interceptAll = true;
        return 0;
      }
      PackageManager packageManager = context.getPackageManager();
      ApplicationInfo appInfo;
      appInfo = packageManager.getApplicationInfo(pkg, PackageManager.GET_META_DATA);
      int uid = appInfo.uid;
      if (uid <= SYSTEM_UID) {
        String pkgs = interceptApps.get(uid);
        String insert_item = SPLIT + pkg;
        if (pkgs != null) {
          if (!pkgs.contains(insert_item)) {
            pkgs += insert_item;
            interceptApps.put(uid, pkgs);
          }
        } else {
          interceptApps.put(uid, insert_item);
        }
      } else
        interceptApps.put(uid, pkg);
      return uid;
    } catch (PackageManager.NameNotFoundException e) {
      Albatross.log("setInterceptApp fail", e);
      return 0;
    }
  }

  @Override
  public int addWatchApp(String packageName, boolean clear) {
    if (clear)
      watchApps.clear();
    PackageManager packageManager = context.getPackageManager();
    ApplicationInfo appInfo;
    try {
      appInfo = packageManager.getApplicationInfo(packageName, 0);
    } catch (PackageManager.NameNotFoundException e) {
      return -1;
    }
    int uid = appInfo.uid;
    watchApps.put(uid, packageName);
    return watchApps.size();
  }

  @Override
  public void setIntercept(int uid, String process) {
    if (process == null)
      interceptApps.put(uid, NO_FILTER);
    else {
      String pkgs = interceptApps.get(uid);
      String insertItem = SPLIT + process;
      if (pkgs != null) {
        if (!pkgs.contains(insertItem)) {
          pkgs += insertItem;
          interceptApps.put(uid, pkgs);
        }
      } else
        interceptApps.put(uid, insertItem);
    }
  }

  @Override
  public void removeIntercept(int uid, String pkg) {
    if (uid > SYSTEM_UID)
      interceptApps.remove(uid);
    else {
      String pkgs = interceptApps.get(uid);
      if (pkgs != null) {
        String insertItem = SPLIT + pkg;
        pkgs = pkgs.replace(insertItem, "");
        if (pkgs.isEmpty()) {
          interceptApps.remove(uid);
        } else {
          interceptApps.put(uid, pkgs);
        }
      }
    }
  }

  @Override
  public void clearIntercept() {
    interceptApps.clear();
  }


  @Override
  public boolean forceStopApp(String pkgName) {
    ActivityManagerH.forceStopPackageAsUser(activityManager, pkgName, 0);
    return true;
  }

  @Override
  public String getAppProcesses() {
    return JsonFormatter.fmt(getAppProcessList(), false);
  }


  public static int appendPlugin(String pluginDex, String pluginLib, String pluginClass, String pluginParams, int pluginFlags) {
    int[] reason = new int[1];
    AlbatrossPlugin plugin = DynamicPluginManager.getInstance().appendPlugin(pluginDex, pluginLib, pluginClass, pluginParams, pluginFlags, reason);
    if (plugin != null) {
      if (plugin.load(SystemServerInjectAgent.v())) {
        plugin.onAttachSystem(Albatross.currentApplication());
      } else
        return DEX_LOAD_FAIL;
      return 0;
    }
    return reason[0];
  }

  public static boolean disablePlugin(String pluginDexPath, String pluginClassName) {
    return DynamicPluginManager.getInstance().disablePlugin(pluginDexPath, pluginClassName);
  }

  static final int flagMask = 75;//FLAG_PERMISSION_REVIEW_REQUIRED + FLAG_PERMISSION_REVOKE_ON_UPGRADE + FLAG_PERMISSION_USER_FIXED + FLAG_PERMISSION_USER_SET
  static final int flagValues = 1;//FLAG_PERMISSION_USER_SET

  @Override
  public String allowAppPermission(String pkgName, String permissionName, int uid) {
    PackageManager packageManager = context.getPackageManager();
    AppOpsManager appOpsManager = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
    if (uid <= 0) {
      try {
        PackageInfo packageInfo = packageManager.getPackageInfo(pkgName, 0);
        uid = packageInfo.applicationInfo.uid;
      } catch (PackageManager.NameNotFoundException e) {
        return "app not find";
      }
    }
    if (ApplicationPackageManagerH.getPermissionManager != null) {
      if ("android.permission.SYSTEM_ALERT_WINDOW".equals(permissionName)) {
        AppOpsManagerH.setMode(appOpsManager, AppOpsManagerH.OP_SYSTEM_ALERT_WINDOW, uid, pkgName, AppOpsManager.MODE_ALLOWED);
        AppOpsManagerH.setMode(appOpsManager, AppOpsManagerH.OP_RUN_ANY_IN_BACKGROUND, uid, pkgName, AppOpsManager.MODE_ALLOWED);
        AppOpsManagerH.setMode(appOpsManager, AppOpsManagerH.OP_RUN_IN_BACKGROUND, uid, pkgName, AppOpsManager.MODE_ALLOWED);
        return STRING_SUCCESS;
      }
      Object manager = ApplicationPackageManagerH.getPermissionManager.invoke(packageManager);
      Object pm = ApplicationPackageManagerH.PermissionManager.mPermissionManager.get(manager);
      ApplicationPackageManagerH.IPermissionManager.grantRuntimePermission.invoke(pm, pkgName, permissionName, 0);
      ApplicationPackageManagerH.IPermissionManager.updatePermissionFlags.invoke(pm, pkgName, permissionName, flagMask, flagValues, true, 0);
    } else {
      IInterface pm = ApplicationPackageManagerH.mPM.get(packageManager);
      ApplicationPackageManagerH.IPackageManager.grantRuntimePermission.invoke(pm, pkgName, permissionName, 0);
      ApplicationPackageManagerH.IPackageManager.updatePermissionFlags.invoke(pm, permissionName, pkgName, flagMask, flagValues, true, 0);
    }
    String appOp = AppOpsManager.permissionToOp(permissionName);
    AppOpsManagerH.setUidMode(appOpsManager, appOp, uid, 0);
    return STRING_SUCCESS;
  }


  @Override
  public int getVersion() {
    return AGENT_VERSION;
  }


}
