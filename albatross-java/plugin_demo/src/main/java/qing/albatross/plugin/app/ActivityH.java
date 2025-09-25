package qing.albatross.plugin.app;

import android.app.Activity;
import android.widget.Toast;

import qing.albatross.annotation.MethodHookBackup;
import qing.albatross.annotation.TargetClass;

@TargetClass(Activity.class)
public class ActivityH {

  @MethodHookBackup
  static void onResume(Activity thiz) {
    onResume(thiz);
    if (DemoPlugin.plugin.isEnable())
      Toast.makeText(thiz, DemoPlugin.prefix + ":" + thiz.getClass().getName(), Toast.LENGTH_LONG).show();
  }


}
