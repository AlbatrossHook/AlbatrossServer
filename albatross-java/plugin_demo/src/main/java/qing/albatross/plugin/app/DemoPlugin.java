package qing.albatross.plugin.app;

import android.app.Application;
import android.widget.Toast;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.server.UnixRpcInstance;

public class DemoPlugin extends AlbatrossPlugin implements DemoApi{

  public static String prefix = "activity";

  public DemoPlugin(String libName, String argString, int flags) {
    super(libName, argString, flags);
    plugin = this;
  }

  static DemoPlugin plugin;

  @Override
  public void beforeMakeApplication() {
    Albatross.log("DemoPlugin beforeMakeApplication");
  }

  @Override
  public boolean load(UnixRpcInstance agent) {
    Albatross.log("DemoPlugin load");
    agent.registerApi(this, DemoApi.class);
    return super.load(agent);
  }

  @Override
  public boolean parseParams(String params, int flags) {
    if (params != null && !params.isEmpty())
      prefix = params;
    return true;
  }

  @Override
  public void beforeApplicationCreate(Application application) {
    try {
      Albatross.log("DemoPlugin beforeApplicationCreate");
      Albatross.hookClass(ActivityH.class);
    } catch (AlbatrossErr e) {
      throw new RuntimeException(e);
    }
  }

  @Override
  public void afterApplicationCreate(Application application) {
    Albatross.log("DemoPlugin afterApplicationCreate");
    Albatross.getMainHandler().postDelayed(() -> {
      Toast.makeText(application, "test app:" + application.getPackageManager(), Toast.LENGTH_LONG).show();
    }, 4000);
  }
  @Override
  public void toastMsg(String msg) {
    Albatross.getMainHandler().post(() -> {
      Toast.makeText(Albatross.currentApplication(), msg, Toast.LENGTH_SHORT).show();
    });
  }
}
