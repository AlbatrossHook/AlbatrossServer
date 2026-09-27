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
package qing.albatross.agent;

import android.app.Application;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.concurrent.LinkedBlockingQueue;

import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.common.AppMetaInfo;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.server.UnixRpcInstance;
import qing.albatross.common.ThreadConfig;

public class PluginMessage {

  static final String TAG = "PluginMessage";

  public static void silenceMessage() {
    try {
      Albatross.disableMethod(AlbatrossPlugin.class.getDeclaredMethod("send", String.class, Throwable.class));
      Albatross.disableMethod(AlbatrossPlugin.class.getDeclaredMethod("send", String.class));
      Albatross.disableMethod(AlbatrossPlugin.class.getDeclaredMethod("log", String.class));
    } catch (NoSuchMethodException e) {
      throw new RuntimeException(e);
    }
  }

  static class PluginLocalImpl {
    @MethodHook
    private static void send(AlbatrossPlugin plugin, String msg) {
      String name = plugin.getClass().getSimpleName();
      if (name.isEmpty())
        Albatross.log(msg);
      else
        Albatross.log(name + ": " + msg);
    }

    @MethodHook
    private static void send(AlbatrossPlugin plugin, String msg, Throwable tr) {
      String name = plugin.getClass().getSimpleName();
      if (name.isEmpty())
        Albatross.log(msg, tr);
      else
        Albatross.log(name + ": " + msg, tr);
    }

    @MethodHook
    private static void log(AlbatrossPlugin plugin, String msg) {
      BufferedDailyRollingLogger rolling = rollingLogger;
      if (rolling != null) {
        rolling.log(plugin.getClass().getName() + ": " + msg);
      } else {
        BufferedDailyRollingLogger app = appLogger;
        if (app != null) {
          app.log(plugin.getClass().getName() + ": " + msg);
        }
      }
    }
  }

  public static void registerPluginMethod() {
    try {
      Albatross.hookClass(PluginLocalImpl.class, AlbatrossPlugin.class);
    } catch (AlbatrossErr e) {
      throw new RuntimeException(e);
    }
  }

  static UnixRpcInstance instance;
  private static final Object LOGGER_CONFIG_LOCK = new Object();
  static volatile BufferedDailyRollingLogger rollingLogger;
  static volatile BufferedDailyRollingLogger appLogger;

  public static boolean isLogInit() {
    BufferedDailyRollingLogger logger = rollingLogger;
    return logger != null && !logger.isClosed();
  }


  static LinkedBlockingQueue<Object> messages = new LinkedBlockingQueue<>(8192);

  @TargetClass(AlbatrossPlugin.class)
  static class PluginSendImpl {

    @MethodHook
    private static void send(Object plugin, String msg) {
      PluginMessage.send(msg);
    }

    @MethodHook
    private static void send(Object plugin, String msg, Throwable tr) {
      PluginMessage.send(msg, tr);
    }

    @MethodHook
    private static void log(Object plugin, String msg) {
      BufferedDailyRollingLogger rolling = rollingLogger;
      if (rolling != null) {
        rolling.log(plugin.getClass().getName() + ":" + msg);
      }
    }
  }

  public static void send(String msg) {
    if (instance != null && instance.getSubscriberSize() > 0) {
      boolean result = messages.offer(msg);
      if (!result) {
        Log.i(TAG, "[!] " + msg);
      }
    } else
      log(msg);
  }

  public static void log(String msg) {
    BufferedDailyRollingLogger rolling = rollingLogger;
    if (rolling != null) {
      rolling.log(msg);
    } else {
      Log.i(TAG, msg);
    }
  }

  public static void appLog(String msg) {
    BufferedDailyRollingLogger app = appLogger;
    if (app != null) {
      app.log(msg);
    } else {
      BufferedDailyRollingLogger rolling = rollingLogger;
      if (rolling != null) {
        rolling.log(msg);
      }
    }
  }

  public static void send(String msg, Throwable tr) {
    if (instance == null || instance.getSubscriberSize() <= 0) {
      BufferedDailyRollingLogger rolling = rollingLogger;
      if (rolling != null) {
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        tr.printStackTrace(pw);
        String desc = sw.toString();
        rolling.log(msg + "\nexception:\n" + desc);
      } else
        Log.i(TAG, msg, tr);
      return;
    }
    StringWriter sw = new StringWriter();
    PrintWriter pw = new PrintWriter(sw);
    tr.printStackTrace(pw);
    String desc = sw.toString();
    boolean result = messages.offer(new String[]{msg, desc});
    if (!result) {
      Log.i(TAG, "[!] " + msg + "\nexception:\n" + desc);
    }
  }


  public static void setMessageSender(UnixRpcInstance sender) {
    try {
      instance = sender;
      Albatross.hookClass(PluginSendImpl.class, AlbatrossPlugin.class);
      Albatross.resetLogger(PluginMessage.class.getDeclaredMethod("send", String.class), PluginMessage.class.getDeclaredMethod("send", String.class, Throwable.class));
      MessageSender messageSender = new MessageSender();
      messageSender.start();
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }


  public static final int LOG_MAX_FILE_SIZE = 1024 * 1024 * 2;

  public static void setLogger(String logDir, String baseName, boolean clean) {
    synchronized (LOGGER_CONFIG_LOCK) {
      if (instance == null) {
        return;
      }
      BufferedDailyRollingLogger oldLogger = rollingLogger;
      if (oldLogger != null) {
        oldLogger.close();
        // Never clean/reopen the same path while the old writer still owns
        // an open descriptor after the five-second close deadline.
        if (!oldLogger.isClosed()) {
          return;
        }
        rollingLogger = null;
      }
      if (logDir != null && logDir.length() > 1) {
        File logFile = new File(logDir);
        if (!logFile.exists()) {
          if (!logFile.mkdirs()) {
            Albatross.log("create log dir:" + logDir + " fail");
            return;
          }
        } else if (clean) {
          BufferedDailyRollingLogger.cleanupLogFiles(logFile, baseName);
        }
        try {
          rollingLogger = new BufferedDailyRollingLogger(logFile, baseName, LOG_MAX_FILE_SIZE);
        } catch (IOException e) {
          Albatross.log("create log fail", e);
        }
      } else {
        try {
          File logDirPath;
          Application context = Albatross.currentApplication();
          if (context == null) {
            if (AppMetaInfo.packageName == null) {
              Albatross.log("can not create logger without application");
              return;
            }
            logDirPath = new File("/data/data/" + AppMetaInfo.packageName + "/files/log");
          } else {
            File fieldDir = context.getFilesDir();
            logDirPath = new File(fieldDir, "log");
          }
          if (logDirPath.exists()) {
            if (clean)
              BufferedDailyRollingLogger.cleanupLogFiles(logDirPath, baseName);
          } else if (!logDirPath.mkdirs() && !logDirPath.isDirectory()) {
            Albatross.log("create log dir:" + logDirPath + " fail");
            return;
          }
          rollingLogger = new BufferedDailyRollingLogger(logDirPath, baseName, LOG_MAX_FILE_SIZE);
        } catch (IOException e) {
          Albatross.log("create log fail", e);
        }
      }
    }
  }

  public static void flushLog() {
    BufferedDailyRollingLogger rolling = rollingLogger;
    if (rolling != null)
      rolling.flush();
    BufferedDailyRollingLogger app = appLogger;
    if (app != null)
      app.flush();
  }

  static class MessageSender extends Thread {

    @Override
    public void run() {
      ThreadConfig.notTraceMe();
      Albatross.log("message sender run");
      int errCount = 0;
      while (errCount < 1024) {
        try {
          Object out = messages.take();
          if (out instanceof String) {
            instance.send((String) out, null);
          } else {
            String[] ss = (String[]) out;
            instance.send(ss[0], ss[1]);
          }
        } catch (Exception e) {
          errCount += 1;
          Log.e("Albatross", "send error:" + errCount, e);
        }
      }
    }
  }

  public static boolean redirectLog(String fileName) {
    synchronized (LOGGER_CONFIG_LOCK) {
      if (appLogger != null)
        return false;
      Application application = Albatross.currentApplication();
      File logDIr;
      if (application == null) {
        String packageName = AppMetaInfo.packageName;
        if (packageName == null) {
          return false;
        }
        logDIr = new File("/data/data/" + packageName + "/files/log");
      } else {
        logDIr = new File(application.getFilesDir(), "log");
      }
      BufferedDailyRollingLogger newLogger = null;
      boolean transactionStarted = false;
      try {
        if (!logDIr.exists() && !logDIr.mkdirs() && !logDIr.isDirectory()) {
          throw new IOException("create log dir fail: " + logDIr);
        }
        newLogger = new BufferedDailyRollingLogger(logDIr,
            fileName + "_" + Albatross.currentProcessName(), 1024 * 1024 * 2);
        Albatross.transactionBegin();
        transactionStarted = true;
        Albatross.hookObject(PrintStreamH.class, System.out);
        Albatross.hookClass(LogH.class);
        Albatross.transactionEnd(true);
        appLogger = newLogger;
        return true;
      } catch (Exception e) {
        if (transactionStarted) {
          Albatross.transactionEnd(false);
        }
        if (newLogger != null) {
          newLogger.close();
        }
        Albatross.log("create app logger fail", e);
        return false;
      }
    }
  }

  public static boolean cancelRedirectLog() {
    synchronized (LOGGER_CONFIG_LOCK) {
      BufferedDailyRollingLogger logger = appLogger;
      if (logger == null)
        return false;
      PrintStreamH.flush();
      logger.log("appLogger finish log mark");
      logger.close();
      if (!logger.isClosed()) {
        return false;
      }
      try {
        Albatross.unhookClass(PrintStreamH.class, System.out.getClass());
        Albatross.unhookClass(LogH.class);
      } catch (AlbatrossErr e) {
        throw new RuntimeException(e);
      }
      appLogger = null;
      return true;
    }
  }


}
