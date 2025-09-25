package qing.albatross.plugin.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

public class PluginActivity extends Activity {
  @Override
  protected void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    TextView textView = new TextView(this);
    textView.setText("demo plugin1");
    setContentView(textView);
    Intent resultIntent = new Intent();
    resultIntent.putExtra("plugin_params", "demo_param");
    resultIntent.putExtra("plugin_flags", 12345);
    resultIntent.putExtra("plugin_class", this.getClass().getName().replace("PluginActivity", "DemoPlugin"));
    setResult(RESULT_OK, resultIntent);
  }
}
