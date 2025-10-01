package qing.albatross.agent;


import android.util.Log;

import java.io.PrintWriter;
import java.io.StringWriter;

import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.server.UnixRpcInstance;

@TargetClass(AlbatrossPlugin.class)
public class PluginMessage {

  static final String TAG = "PluginMessage";

  public static void silenceMessage() {
    try {
      Albatross.disableMethod(AlbatrossPlugin.class.getDeclaredMethod("send", String.class, Throwable.class));
      Albatross.disableMethod(AlbatrossPlugin.class.getDeclaredMethod("send", String.class));
    } catch (NoSuchMethodException e) {
      throw new RuntimeException(e);
    }
  }

  static class PluginHook {
    @MethodHook
    private static void send(AlbatrossPlugin plugin, String msg) {
      Albatross.log(msg);
    }

    @MethodHook
    private static void send(AlbatrossPlugin plugin, String msg, Throwable tr) {
      Albatross.log(msg, tr);
    }
  }

  public static void enableMessage() {
    try {
      Albatross.hookClass(PluginHook.class, AlbatrossPlugin.class);
    } catch (AlbatrossErr e) {
      throw new RuntimeException(e);
    }
  }

  static UnixRpcInstance instance;


  @TargetClass(AlbatrossPlugin.class)
  static class PluginHookSend {

    @MethodHook
    private static void send(Object plugin, String msg) {
      if (instance.getSubscriberSize() > 0)
        instance.send(msg, null);
      else
        Log.i(TAG, msg);
    }

    @MethodHook
    private static void send(Object plugin, String msg, Throwable tr) {
      if (instance.getSubscriberSize() > 0) {
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        tr.printStackTrace(pw);
        String s = sw.toString();
        instance.send(msg, s);
      } else {
        Log.i(TAG, msg, tr);
      }
    }
  }

  public static void log(String msg) {
    if (instance != null && instance.getSubscriberSize() > 0)
      instance.send(msg, null);
    else
      Log.i(TAG, msg);
  }

  public static void log(String msg, Throwable tr) {
    if (instance == null) {
      Log.i(TAG, msg, tr);
      return;
    }
    int subscriberSize = instance.getSubscriberSize();
    if (subscriberSize > 0) {
      StringWriter sw = new StringWriter();
      PrintWriter pw = new PrintWriter(sw);
      tr.printStackTrace(pw);
      String s = sw.toString();
      instance.send(msg, s);
    } else {
      Log.i(TAG, msg, tr);
    }
  }


  public static void setMessageSender(UnixRpcInstance sender) {
    try {
      instance = sender;
      Albatross.hookClass(PluginHookSend.class, AlbatrossPlugin.class);
      Albatross.resetLogger(PluginMessage.class.getDeclaredMethod("log", String.class), PluginMessage.class.getDeclaredMethod("log", String.class, Throwable.class));
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

}
