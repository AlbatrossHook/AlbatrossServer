package qing.albatross.plugin.app;

import android.app.Application;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;

public class DemoPlugin extends AlbatrossPlugin {
  public DemoPlugin(String libName, String argString, int flags) {
    super(libName, argString, flags);
  }

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
