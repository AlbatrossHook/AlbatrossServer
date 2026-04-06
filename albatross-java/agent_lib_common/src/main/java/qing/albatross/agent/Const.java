package qing.albatross.agent;

public class Const {
  public static final int FLAG_LOG = 0x10000;
  public static final int REDIRECT_LOG = 0x20000;
  public static final int CLEANUP_LOG  = 0x40000;

  public static final int DEX_LOAD_FAIL = 4;
  public static final int DEX_CLASS_NO_FIND = 5;
  public static final int DEX_INIT_FAIL = 6;
  public static final int METHOD_NO_FIND = 7;
  public static final int DEX_SYSTEM_SERVER_ERR = 9;
  public static final int DEX_PROCESS_SLEEPING = 10;
  public static final int DEX_LOAD_SUCCESS = 20;
  public static final int DEX_ALREADY_LOAD = 21;
}
