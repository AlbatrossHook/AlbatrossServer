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

import android.content.Context;
import android.os.Process;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.LinkedList;
import java.util.List;
import java.util.Locale;

import qing.albatross.common.ThreadConfig;

/**
 * 带缓冲队列的 Android 按天滚动日志工具
 * - 按天分文件（app_2025-11-07.log）
 * - 单文件超限则 .1, .2...
 * - 使用后台线程批量写入，减少 I/O 频率
 */
public class BufferedDailyRollingLogger {

  private final String baseName;
  private final long maxFileSize;
  private final File logDir;

  // 缓冲与线程控制
  private final LinkedList<String> logQueue = new LinkedList<>();
  private final Object queueLock = new Object();
  private volatile boolean running = true;
  private Thread writerThread;
  private FileOutputStream fos;
  private File currentFile;
  private String currentDateStr;

  // 配置参数（可调整）
  private static final long FLUSH_INTERVAL_MS = 500; // 每 100ms 强制 flush 一次
  private static final int MAX_BUFFER_SIZE = 50;     // 最多缓存 50 条再 flush

  private static final String DATE_PATTERN = "yyyy-MM-dd";
  private static final SimpleDateFormat DATE_FORMAT = new SimpleDateFormat(DATE_PATTERN, Locale.getDefault());
  private static final SimpleDateFormat TIMESTAMP_FORMAT = new SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault());

  public BufferedDailyRollingLogger(Context context, String baseName, long maxFileSize) throws IOException {
    this(context.getFilesDir(), baseName, maxFileSize);
  }

  public BufferedDailyRollingLogger(File logDir, String baseName, long maxFileSize) throws IOException {
    if (logDir == null || !logDir.exists() || !logDir.isDirectory()) {
      throw new IllegalArgumentException("Invalid log directory: " + logDir);
    }
    this.baseName = baseName;
    this.maxFileSize = maxFileSize;
    this.logDir = logDir;

    // 启动写入线程
    writerThread = new Thread(this::writerLoop, "LogWriterThread-" + baseName);
    writerThread.setDaemon(true); // 应用退出时自动终止
    writerThread.start();
  }

  /**
   * 快速入队日志（非阻塞）
   */
  public void log(String message) {
    if (!running) return;
    String timestamp = TIMESTAMP_FORMAT.format(new Date());
    String logLine = "[" + timestamp + "] " + message;
    synchronized (queueLock) {
      logQueue.add(logLine);
      if (logQueue.size() >= MAX_BUFFER_SIZE)
        queueLock.notify(); // 唤醒写入线程
    }
  }

  /**
   * 立即 flush 所有缓冲日志（可用于关键日志或退出前）
   */
  public void flush() {
    synchronized (queueLock) {
      queueLock.notify();
    }
  }

  /**
   * 安全关闭：停止接收新日志，并等待缓冲写完
   */
  public void close() {
    running = false;
    flush();
    if (writerThread != null && writerThread.isAlive()) {
      try {
        writerThread.join(5000); // 最多等 5 秒
      } catch (InterruptedException ignore) {
      }
    }
    // 关闭流
    synchronized (queueLock) {
      safeCloseFos();
    }
  }

  // ===== 后台写入循环 =====
  private void writerLoop() {
    ThreadConfig.notTraceMe();
    List<String> batch = new LinkedList<>();
    StringBuilder logBuilder = new StringBuilder();
    long lastFlushTime = System.currentTimeMillis();
    SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault());
    String currentTime = sdf.format(new Date());
    logBuilder.append("=== 日志启动时间: ").append(currentTime)
        .append(" 进程PID: ").append(Process.myPid()).append(" ===");
    batch.add(logBuilder.toString());
    while (running) {
      try {
        synchronized (queueLock) {
          // 等待有日志 or 超时
          while (logQueue.isEmpty() && running) {
            long now = System.currentTimeMillis();
            long elapsed = now - lastFlushTime;
            if (elapsed >= FLUSH_INTERVAL_MS) {
              break; // 定期 flush 空队列也触发检查（如跨天）
            }
            queueLock.wait(FLUSH_INTERVAL_MS - elapsed);
          }
          // 取出一批日志
          int drainCount = Math.min(logQueue.size(), MAX_BUFFER_SIZE);
          for (int i = 0; i < drainCount; i++) {
            batch.add(logQueue.poll());
          }
        }
        // 写入磁盘
        if (!batch.isEmpty() || System.currentTimeMillis() - lastFlushTime >= FLUSH_INTERVAL_MS) {
          writeBatchToDisk(batch);
          batch.clear();
          lastFlushTime = System.currentTimeMillis();
        }
      } catch (Exception e) {
        // 可选：记录到系统日志或忽略
        android.util.Log.e("BufferedLogger", "Write error", e);
      }
    }
    // 退出前再 flush 一次
    if (!logQueue.isEmpty()) {
      String s;
      while ((s = logQueue.poll()) != null) {
        batch.add(s);
      }
    }
    if (!batch.isEmpty()) {
      writeBatchToDisk(batch);
    }
    ThreadConfig.notifyLeave();
  }

  private void writeBatchToDisk(List<String> batch) {
    try {
      rollIfNeeded(); // 检查是否跨天
      for (String line : batch) {
        byte[] bytes = (line + "\n").getBytes();
        // 检查是否需要同天滚动
        if (currentFile.length() + bytes.length > maxFileSize) {
          rollOverSameDay();
        }
        fos.write(bytes);
      }
      fos.flush();
    } catch (IOException e) {
      android.util.Log.e("BufferedLogger", "Failed to write log batch", e);
    }
  }

  // ===== 文件滚动逻辑（同前）=====
  private void rollIfNeeded() throws IOException {
    String today = DATE_FORMAT.format(new Date());
    if (currentFile == null || !today.equals(currentDateStr)) {
      safeCloseFos();
      currentDateStr = today;
      currentFile = new File(logDir, baseName + "_" + today + ".log");
      fos = new FileOutputStream(currentFile, true);
    }
  }

  private void rollOverSameDay() throws IOException {
    safeCloseFos();
    String baseFileName = baseName + "_" + currentDateStr + "_";
    int index = 1;
    File candidate;
    do {
      candidate = new File(logDir, baseFileName + index + ".log");
      index++;
    } while (candidate.exists());
    currentFile = candidate;
    fos = new FileOutputStream(currentFile, false);
  }

  private void safeCloseFos() {
    if (fos != null) {
      try {
        fos.close();
      } catch (IOException ignored) {
      }
      fos = null;
    }
  }

  public static int cleanupLogFiles(File dir, String baseName) {
    File[] files = dir.listFiles((d, name) -> name.startsWith(baseName + "_"));
    if (files != null) {
      for (File f : files) f.delete();
      return files.length;
    }
    return 0;
  }
}