package qing.albatross.app.agent.client;

public class ShellExecResult {
  public int exitCode;
  public String stdout;
  public String stderr;

  public ShellExecResult(int exitCode, String stdout, String stderr) {
    this.exitCode = exitCode;
    this.stdout = stdout;
    this.stderr = stderr;
  }
}
