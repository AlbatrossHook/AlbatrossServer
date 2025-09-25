package qing.albatross.plugin.app;

import android.app.Application;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;

public class DemoPlugin extends AlbatrossPlugin {

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
  public boolean load() {
    Albatross.log("DemoPlugin load");
    return super.load();
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
  }
}
