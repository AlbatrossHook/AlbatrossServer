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

import java.util.Locale;

/**
 * hook_method / dyn_hook_method 命中记录的进程内环形缓冲（结构化取数通道）。
 * <p>
 * 内置回调（AgentInstructionListener / AgentMethodHook）命中时在打 logcat 之外追加一条
 * JSON 行记录；客户端经 RPC（hookEventsStatus / hookEventsPull / hookEventsClear）
 * 按全局序号游标拉取，替代"每个观测点写一个插件"。
 * <p>
 * 纪律（对标 native 侧 AlbDefaultTraceSink）：
 *  - 默认关闭，{@link #ENABLED} 为 false 时命中路径只做一次 volatile 读（零分配）；
 *  - 开启后命中线程 synchronized 入环，定容覆盖最旧并计 dropped，无阻塞无等待；
 *  - 记录在命中线程一次拼成 JSON 行，拉取侧只做拼接，不做对象反转义。
 *  - 本类零外部依赖（只用 java.*），tid 由调用方传入，便于独立单测。
 */
public final class HookEventBuffer {

  public static final int DEFAULT_CAPACITY = 4096;
  public static final int MAX_CAPACITY = 1 << 20;

  /** 命中路径的第一道闸：false 时调用方直接跳过（勿在命中线程外缓存该值） */
  public static volatile boolean ENABLED = false;

  private static final HookEventBuffer INSTANCE = new HookEventBuffer(DEFAULT_CAPACITY);

  private String[] ring;
  private long nextSeq = 1;     // 下一条记录的全局序号（从 1 起；cursor 语义见 pull）
  private long dropped = 0;     // 被覆盖丢弃的记录数
  private long appended = 0;    // 累计入环记录数（含被覆盖的）

  private HookEventBuffer(int capacity) {
    ring = new String[capacity];
  }

  public static HookEventBuffer get() {
    return INSTANCE;
  }

  /** 开启记录并（重）设容量；capacity<=0 用默认，超上限截断。已在跑时只换容量（清空）。 */
  public static void enable(int capacity) {
    synchronized (INSTANCE) {
    if (capacity <= 0)
      capacity = DEFAULT_CAPACITY;
    if (capacity > MAX_CAPACITY)
      capacity = MAX_CAPACITY;
      if (capacity != INSTANCE.ring.length) {
        INSTANCE.ring = new String[capacity];
        INSTANCE.nextSeq = 1;
        INSTANCE.dropped = 0;
        INSTANCE.appended = 0;
      }
      ENABLED = true;
    }
  }

  public static void disable() {
    synchronized (INSTANCE) {
      ENABLED = false;
    }
  }

  /** 清空已积累记录（seq 不重置，游标不回退；clear 造成的数据缺口由 pull 的 skipped 报告） */
  public static void clear() {
    synchronized (INSTANCE) {
      java.util.Arrays.fill(INSTANCE.ring, null);
      INSTANCE.appended = 0;
      INSTANCE.dropped = 0;
    }
  }

  /**
   * 追加一条记录（命中线程调用；enabled 由调用方先判，这里不再判）。
   * 各描述串应是调用方已拼好的（SafeToString 输出 / 方法名 / 线程名），这里只做转义入环。
   *
   * @param kind   "ins"（指令级 hook_method）或 "dyn"（动态 hook）
   * @param phase  "enter" / "leave" / "pc"（方法中途 dexPc 命中）
   * @param tid    调用方传入的线程 id（如 ThreadConfig.myId()），本类不依赖 core
   */
  public static void record(String kind, String phase, String method, Object self,
      String argsDesc, String retDesc) {
    record(kind, phase, method, self, argsDesc, retDesc,
        Thread.currentThread().getId(), Thread.currentThread().getName());
  }

  /** 同上，tid 显式传入（调用方用 ThreadConfig.myId()），线程名取当前线程。 */
  public static void record(String kind, String phase, String method, Object self,
      String argsDesc, String retDesc, long tid) {
    record(kind, phase, method, self, argsDesc, retDesc, tid,
        Thread.currentThread().getName());
  }

  /** 同上，tid/线程名显式传入（单测与调用方可注入）。 */
  public static void record(String kind, String phase, String method, Object self,
      String argsDesc, String retDesc, long tid, String threadName) {
    final HookEventBuffer buffer = INSTANCE;
    // 转义与拼串都在锁外做，锁内只分配序号与写槽位
    String threadEsc = escape(threadName);
    String methodEsc = escape(method);
    // receiver 的 toString 可能抛异常/有副作用：必须兜底，否则异常会从 record
    // 一路逃出 onEnter、注入被插桩方法的调用点（插桩工具不能改变被测程序行为）。
    // 不用 SafeToString（core 模块）——本类按设计零外部依赖，便于纯 JVM 单测。
    String selfDesc = null;
    if (self != null) {
      try {
        selfDesc = self.toString();
      } catch (Throwable t) {
        selfDesc = "<toString threw " + t.getClass().getSimpleName() + ">";
      }
    }
    String selfEsc = selfDesc != null ? escape(selfDesc) : null;
    String argsEsc = argsDesc != null ? escape(argsDesc) : null;
    String retEsc = retDesc != null ? escape(retDesc) : null;
    long ts = System.currentTimeMillis();
    synchronized (buffer) {
      final String[] ring = buffer.ring;
      long seq = buffer.nextSeq++;
      int slot = (int) ((seq - 1) % ring.length);
      if (ring[slot] != null) {
        buffer.dropped++;
      }
      StringBuilder builder = new StringBuilder(192);
      builder.append("{\"seq\":").append(seq)
          .append(",\"ts\":").append(ts)
          .append(",\"tid\":").append(tid)
          .append(",\"thread\":\"").append(threadEsc)
          .append("\",\"kind\":\"").append(kind)
          .append("\",\"phase\":\"").append(phase)
          .append("\",\"method\":\"").append(methodEsc).append('"');
      if (selfEsc != null) {
        builder.append(",\"this\":\"").append(selfEsc).append('"');
      }
      if (argsEsc != null) {
        builder.append(",\"args\":\"").append(argsEsc).append('"');
      }
      if (retEsc != null) {
        builder.append(",\"ret\":\"").append(retEsc).append('"');
      }
      builder.append('}');
      ring[slot] = builder.toString();
      buffer.appended++;
    }
  }

  /**
   * 拉取 cursor 之后的记录（JSON 行批量，{@link #STATUS_PREFIX} 开头的首行为元信息）。
   * maxBytes<=0 用 1MiB；超出在行边界截断（下次继续拉）。
   * 首行字段：first_seq（环内最旧）、next_seq（下一条）、dropped、capacity、
   * skipped（cursor 与环内最旧之间被覆盖丢掉的条数）。
   */
  public static String pull(long cursor, int maxBytes) {
    synchronized (INSTANCE) {
        final HookEventBuffer buffer = INSTANCE;
        final String[] ring = buffer.ring;
        int capacity = ring.length;
        int count = (int) Math.min(buffer.appended, capacity);
        long firstSeq = buffer.nextSeq - count;
        long from = Math.max(cursor + 1, firstSeq);
        long skipped = Math.max(0, firstSeq - 1 - cursor);
        if (maxBytes <= 0)
          maxBytes = 1 << 20;
        StringBuilder builder = new StringBuilder(256);
        builder.append(STATUS_PREFIX).append("{\"first_seq\":").append(firstSeq)
            .append(",\"next_seq\":").append(buffer.nextSeq)
            .append(",\"dropped\":").append(buffer.dropped)
            .append(",\"capacity\":").append(capacity)
            .append(",\"skipped\":").append(skipped)
            .append("}\n");
        int budget = maxBytes;
        for (long seq = from; seq < buffer.nextSeq; seq++) {
          String line = ring[(int) ((seq - 1) % capacity)];
          if (line == null)
            continue;
          if (budget < line.length() + 1)
            break;
          builder.append(line).append('\n');
          budget -= line.length() + 1;
        }
        return builder.toString();
      }
  }

  /** 状态 JSON：enabled/capacity/appended/dropped/next_seq/readable */
  public static String status() {
    synchronized (INSTANCE) {
      final HookEventBuffer buffer = INSTANCE;
      int capacity = buffer.ring.length;
      int count = (int) Math.min(buffer.appended, capacity);
      return "{\"enabled\":" + ENABLED
          + ",\"capacity\":" + capacity
          + ",\"appended\":" + buffer.appended
          + ",\"dropped\":" + buffer.dropped
          + ",\"next_seq\":" + buffer.nextSeq
          + ",\"readable\":" + count
          + "}";
    }
  }

  /** 拉取结果首行前缀（区别于记录行，客户端据此解析游标元信息） */
  public static final String STATUS_PREFIX = "#";

  /** 测试专用：全量重置（seq 归 1）。生产勿用——会破坏游标单调性。 */
  static void resetForTest() {
    synchronized (INSTANCE) {
      INSTANCE.ring = new String[INSTANCE.ring.length];
      INSTANCE.nextSeq = 1;
      INSTANCE.appended = 0;
      INSTANCE.dropped = 0;
      ENABLED = true;
    }
  }

  /** JSON 字符串转义（引号、反斜杠与常见控制字符；无效控制字节统一转 \\uXXXX） */
  static String escape(String s) {
    if (s == null)
      return "";
    int len = s.length();
    StringBuilder builder = new StringBuilder(len + 8);
    for (int i = 0; i < len; i++) {
      char c = s.charAt(i);
      switch (c) {
        case '"':
          builder.append("\\\"");
          break;
        case '\\':
          builder.append("\\\\");
          break;
        case '\n':
          builder.append("\\n");
          break;
        case '\r':
          builder.append("\\r");
          break;
        case '\t':
          builder.append("\\t");
          break;
        default:
          if (c < 0x20) {
            builder.append(String.format(Locale.US, "\\u%04x", (int) c));
          } else {
            builder.append(c);
          }
      }
    }
    return builder.toString();
  }
}
