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
import android.system.Os;
import android.system.StructStat;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;

import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;

/**
 * 带缓冲队列的 Android 按天滚动日志工具
 * - 按天分文件（app_2025-11-07.log）
 * - 单文件超限则 .1, .2...
 * - 使用后台线程批量写入，减少 I/O 频率
 */
public class BufferedDailyRollingLogger {

  private static final String DATE_PATTERN = "yyyy-MM-dd";
  private static final String TIMESTAMP_PATTERN = "HH:mm:ss.SSS";

  private static final long FLUSH_INTERVAL_MS = 500;
  private static final int MAX_BUFFER_SIZE = 50;
  private static final int MAX_QUEUE_ENTRIES = 4096;
  private static final long MAX_QUEUE_BYTES = 4L * 1024L * 1024L;
  private static final int OUTPUT_BUFFER_SIZE = 64 * 1024;
  private static final long DROP_WARNING_INTERVAL_NANOS = 60_000_000_000L;
  private static final long WRITE_ERROR_INTERVAL_NANOS = 60_000_000_000L;
  private static final long WRITE_RETRY_INITIAL_MS = 100L;
  private static final long WRITE_RETRY_MAX_MS = 5_000L;
  private static final long CLOSE_TIMEOUT_MS = 5_000L;

  private static final ConcurrentHashMap<String, Object> FILE_LOCKS = new ConcurrentHashMap<>();

  private final String baseName;
  private final long maxFileSize;
  private final File logDir;
  private final Object fileLock;

  private final ArrayDeque<LogRecord> logQueue = new ArrayDeque<>();
  private final Object queueLock = new Object();
  private volatile boolean running = true;
  private volatile boolean closed;
  private volatile long closeDeadlineMillis;
  private Thread writerThread;
  private FileOutputStream fos;
  private BufferedOutputStream output;
  private File currentFile;
  private String currentDateStr;
  private long currentFileBytes;
  private int nextRollIndex = 1;

  // bufferedBytes includes records in logQueue and the writer's in-flight batch.
  private long bufferedBytes;
  private int bufferedEntryCount;
  private long droppedCount;
  private long reportedDroppedCount;
  private long ioDroppedCount;
  private long lastDropWarningNanos;
  private long lastWriteErrorNanos;

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
    this.fileLock = fileLockFor(logDir, baseName);

    writerThread = new Thread(this::writerLoop, "LogWriterThread-" + baseName);
    writerThread.setDaemon(true);
    writerThread.start();
  }

  /**
   * 快速入队日志（非阻塞）。队列达到任一上限时丢弃新日志。
   */
  public void log(String message) {
    if (!running) {
      return;
    }

    long timestampMillis = System.currentTimeMillis();
    String rawMessage = message == null ? "null" : message;
    long estimatedBytes = estimateQueuedBytes(rawMessage);
    boolean warn = false;
    long droppedSnapshot = 0;
    synchronized (queueLock) {
      // close() may have raced with the fast path check.
      if (!running) {
        return;
      }
      if (bufferedEntryCount >= MAX_QUEUE_ENTRIES
          || estimatedBytes > MAX_QUEUE_BYTES
          || bufferedBytes > MAX_QUEUE_BYTES - estimatedBytes) {
        long pendingDrops = droppedCount - reportedDroppedCount;
        droppedCount++;
        droppedSnapshot = droppedCount;
        if (pendingDrops == 0) {
          queueLock.notify();
        }
        long now = System.nanoTime();
        if (lastDropWarningNanos == 0
            || now - lastDropWarningNanos >= DROP_WARNING_INTERVAL_NANOS) {
          lastDropWarningNanos = now;
          warn = true;
        }
      } else {
        logQueue.addLast(new LogRecord(timestampMillis, rawMessage, estimatedBytes));
        bufferedBytes += estimatedBytes;
        bufferedEntryCount++;
        if (logQueue.size() >= MAX_BUFFER_SIZE) {
          queueLock.notify();
        }
      }
    }
    if (warn) {
      reportDropWarning(droppedSnapshot);
    }
  }

  /**
   * 唤醒写线程。保持异步语义，不等待写线程完成。
   */
  public void flush() {
    synchronized (queueLock) {
      queueLock.notify();
    }
  }

  /**
   * 安全关闭：停止接收新日志，并等待缓冲写完，最多等待 5 秒。
   */
  public void close() {
    synchronized (queueLock) {
      running = false;
      closeDeadlineMillis = System.currentTimeMillis() + CLOSE_TIMEOUT_MS;
      queueLock.notifyAll();
    }
    Thread thread = writerThread;
    if (thread != null && thread != Thread.currentThread() && thread.isAlive()) {
      try {
        thread.join(CLOSE_TIMEOUT_MS);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
      if (thread.isAlive()) {
        reportLogcatWarning("Timed out waiting for logger writer thread to stop");
      }
    }
  }

  /**
   * 供重配置调用方判断 close() 是否已经真正完成。
   */
  public boolean isClosed() {
    return closed;
  }

  private void writerLoop() {
    SimpleDateFormat dateFormat = new SimpleDateFormat(DATE_PATTERN, Locale.getDefault());
    SimpleDateFormat timestampFormat = new SimpleDateFormat(TIMESTAMP_PATTERN, Locale.getDefault());
    ArrayList<LogRecord> pending = new ArrayList<>(MAX_BUFFER_SIZE);
    String pendingSummary = null;
    long pendingSummaryCount = 0;
    long retryDelay = 0;
    boolean traceMarked = false;
    try {
      ThreadConfig.notTraceMe();
      traceMarked = true;
      writeStartupMarker(dateFormat, timestampFormat);
      while (true) {
        if (pending.isEmpty() && pendingSummary == null) {
          synchronized (queueLock) {
            while (logQueue.isEmpty() && running) {
              try {
                queueLock.wait(FLUSH_INTERVAL_MS);
              } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                running = false;
                if (closeDeadlineMillis == 0) {
                  closeDeadlineMillis = System.currentTimeMillis() + CLOSE_TIMEOUT_MS;
                }
                break;
              }
            }

            long pendingDrops = droppedCount - reportedDroppedCount;
            if (pendingDrops > 0) {
              pendingSummaryCount = pendingDrops;
              pendingSummary = "BufferedDailyRollingLogger dropped " + pendingDrops
                  + " log message(s) because the queue limit was reached";
            }
            int drainCount = Math.min(logQueue.size(), MAX_BUFFER_SIZE);
            for (int i = 0; i < drainCount; i++) {
              pending.add(logQueue.removeFirst());
            }
          }
        }

        if (!pending.isEmpty() || pendingSummary != null) {
          WriteResult result = writeBatchToDisk(
              pendingSummary, pending, dateFormat, timestampFormat);
          if (result.summaryWritten) {
            synchronized (queueLock) {
              reportedDroppedCount += pendingSummaryCount;
              if (reportedDroppedCount > droppedCount) {
                reportedDroppedCount = droppedCount;
              }
            }
            pendingSummary = null;
            pendingSummaryCount = 0;
          }
          if (result.success && !pending.isEmpty()) {
            releaseWrittenRecords(pending, pending.size());
          }
          if (result.success) {
            retryDelay = 0;
            continue;
          }
          if (closeDeadlineExceeded()) {
            discardRetained(pending);
            break;
          }
          retryDelay = retryDelay == 0
              ? WRITE_RETRY_INITIAL_MS
              : Math.min(WRITE_RETRY_MAX_MS, retryDelay * 2);
          sleepBeforeRetry(retryDelay);
          continue;
        }

        synchronized (queueLock) {
          if (!running && logQueue.isEmpty()) {
            break;
          }
        }
      }
    } catch (Exception e) {
      reportLogcatError("Unexpected writer error", e);
      synchronized (queueLock) {
        running = false;
        if (closeDeadlineMillis == 0) {
          closeDeadlineMillis = System.currentTimeMillis() + CLOSE_TIMEOUT_MS;
        }
      }
    } finally {
      synchronized (queueLock) {
        running = false;
      }
      discardRetained(pending);
      synchronized (fileLock) {
        closeOutputLocked();
        currentFile = null;
        currentDateStr = null;
        currentFileBytes = 0;
      }
      closed = true;
      if (traceMarked) {
        try {
          ThreadConfig.notifyLeave();
        } catch (Exception e) {
          reportLogcatError("Failed to leave logger trace exclusion", e);
        }
      }
    }
  }

  private WriteResult writeBatchToDisk(String summary,
                                       ArrayList<LogRecord> batch, SimpleDateFormat dateFormat, SimpleDateFormat timestampFormat) {
    boolean summaryWritten = summary == null;
    Exception failure = null;
    synchronized (fileLock) {
      try {
        if (summary != null) {
          writeLine(System.currentTimeMillis(), summary, true, dateFormat, timestampFormat);
          summaryWritten = true;
        }
        String checkedDate = null;
        for (LogRecord record : batch) {
          String date = dateFormat.format(new Date(record.timestampMillis));
          if (!date.equals(checkedDate)) {
            ensureOutputForDate(date);
            checkedDate = date;
          }
          writeLineOnCurrentFile(record.timestampMillis, record.message, true,
              date, timestampFormat);
        }
        if (output == null) {
          throw new IOException("logger output is not open");
        }
        output.flush();
      } catch (Exception e) {
        failure = e;
        invalidateOutputLocked();
      }
    }
    if (failure != null) {
      reportWriteError(failure);
      // BufferedOutputStream may have accepted bytes without flushing them to
      // the file. Retain the whole batch and retry from the beginning. This
      // can duplicate a prefix if the underlying write failed after a partial
      // flush, but avoids falsely releasing records that were never durable.
      return new WriteResult(false, false);
    }
    return new WriteResult(true, summaryWritten);
  }

  private void writeStartupMarker(SimpleDateFormat dateFormat, SimpleDateFormat timestampFormat) {
    long now = System.currentTimeMillis();
    String marker = "=== 日志启动时间: " + dateFormat.format(new Date(now)) + " "
        + timestampFormat.format(new Date(now))
        + " 进程PID: " + Process.myPid() + " ===";
    Exception failure = null;
    synchronized (fileLock) {
      try {
        String date = dateFormat.format(new Date(now));
        ensureOutputForDate(date);
        writeLineOnCurrentFile(now, marker, false, date, timestampFormat);
        output.flush();
      } catch (Exception e) {
        failure = e;
        invalidateOutputLocked();
      }
    }
    if (failure != null) {
      reportWriteError(failure);
    }
  }

  private void writeLine(long timestampMillis, String message, boolean addTimestamp,
                         SimpleDateFormat dateFormat, SimpleDateFormat timestampFormat) throws IOException {
    String date = dateFormat.format(new Date(timestampMillis));
    ensureOutputForDate(date);
    writeLineOnCurrentFile(timestampMillis, message, addTimestamp, date, timestampFormat);
  }

  private void writeLineOnCurrentFile(long timestampMillis, String message, boolean addTimestamp,
                                      String date, SimpleDateFormat timestampFormat) throws IOException {
    if (currentFile == null || output == null || !date.equals(currentDateStr)) {
      throw new IOException("logger output is not open for date " + date);
    }
    String line = addTimestamp
        ? "[" + timestampFormat.format(new Date(timestampMillis)) + "] " + message
        : message;
    byte[] bytes = (line + "\n").getBytes(StandardCharsets.UTF_8);
    if (needsRollover(bytes.length)) {
      rollOverSameDay();
    }
    output.write(bytes);
    currentFileBytes += bytes.length;
  }

  private boolean needsRollover(int bytesLength) {
    return maxFileSize < 0
        || currentFileBytes > maxFileSize
        || bytesLength > maxFileSize - currentFileBytes;
  }

  private void ensureOutputForDate(String date) throws IOException {
    boolean dateChanged = currentFile == null || !date.equals(currentDateStr);
    boolean reopen = dateChanged || fos == null || output == null;
    if (!reopen) {
      if (!currentFile.exists()) {
        reopen = true;
      } else {
        long actualLength = currentFile.length();
        if (actualLength < currentFileBytes || activeFileIdentityChanged()) {
          reopen = true;
        } else {
          currentFileBytes = actualLength;
        }
      }
    }
    if (!reopen) {
      return;
    }

    File target = dateChanged
        ? new File(logDir, baseName + "_" + date + ".log")
        : currentFile;
    if (dateChanged) {
      nextRollIndex = 1;
    }
    openOutput(target, date, true);
  }

  private void openOutput(File target, String date, boolean append) throws IOException {
    ensureLogDirectory();
    FileOutputStream newFos = null;
    BufferedOutputStream newOutput = null;
    try {
      newFos = new FileOutputStream(target, append);
      newOutput = new BufferedOutputStream(newFos, OUTPUT_BUFFER_SIZE);
      long existingLength = target.length();
      closeOutputLocked();
      currentFile = target;
      currentDateStr = date;
      currentFileBytes = existingLength;
      fos = newFos;
      output = newOutput;
    } catch (Exception e) {
      if (newFos != null) {
        try {
          newFos.close();
        } catch (IOException ignored) {
        }
      }
      throw e instanceof IOException ? (IOException) e : new IOException(e);
    }
  }

  private void rollOverSameDay() throws IOException {
    if (currentDateStr == null) {
      throw new IOException("logger date is not initialized");
    }
    ensureLogDirectory();
    File candidate;
    int candidateIndex;
    while (true) {
      candidateIndex = nextRollIndex++;
      candidate = new File(logDir,
          baseName + "_" + currentDateStr + "_" + candidateIndex + ".log");
      if (candidate.createNewFile()) {
        break;
      }
    }

    FileOutputStream newFos = null;
    BufferedOutputStream newOutput = null;
    try {
      newFos = new FileOutputStream(candidate, false);
      newOutput = new BufferedOutputStream(newFos, OUTPUT_BUFFER_SIZE);
      closeOutputLocked();
      currentFile = candidate;
      currentFileBytes = 0;
      fos = newFos;
      output = newOutput;
    } catch (Exception e) {
      if (newFos != null) {
        try {
          newFos.close();
        } catch (IOException ignored) {
        }
      }
      candidate.delete();
      throw e instanceof IOException ? (IOException) e : new IOException(e);
    }
  }

  private void ensureLogDirectory() throws IOException {
    if (!logDir.exists() && !logDir.mkdirs() && !logDir.isDirectory()) {
      throw new IOException("Unable to create log directory: " + logDir);
    }
    if (!logDir.isDirectory()) {
      throw new IOException("Log path is not a directory: " + logDir);
    }
  }

  private void invalidateOutputLocked() {
    FileOutputStream oldFos = fos;
    output = null;
    fos = null;
    // Do not close the BufferedOutputStream here: close() would flush a failed
    // buffer and could duplicate records when the pending batch is retried.
    if (oldFos != null) {
      try {
        oldFos.close();
      } catch (IOException ignored) {
      }
    }
  }

  private void closeOutputLocked() {
    BufferedOutputStream oldOutput = output;
    FileOutputStream oldFos = fos;
    output = null;
    fos = null;
    if (oldOutput != null) {
      try {
        oldOutput.close();
      } catch (IOException ignored) {
        // The wrapper normally closes the fd; still try the raw stream below.
      }
    }
    if (oldFos != null) {
      try {
        oldFos.close();
      } catch (IOException ignored) {
      }
    }
  }

  private boolean activeFileIdentityChanged() {
    if (fos == null || currentFile == null) {
      return false;
    }
    try {
      StructStat fdStat = Os.fstat(fos.getFD());
      StructStat pathStat = Os.stat(currentFile.getPath());
      return fdStat.st_dev != pathStat.st_dev || fdStat.st_ino != pathStat.st_ino;
    } catch (Exception e) {
      return !currentFile.exists();
    }
  }

  private void releaseWrittenRecords(ArrayList<LogRecord> pending, int count) {
    if (count <= 0) {
      return;
    }
    synchronized (queueLock) {
      for (int i = 0; i < count; i++) {
        releaseRecordLocked(pending.get(i));
      }
    }
    pending.subList(0, count).clear();
  }

  private void discardRetained(ArrayList<LogRecord> pending) {
    int discarded = pending.size();
    synchronized (queueLock) {
      for (LogRecord record : pending) {
        releaseRecordLocked(record);
      }
      pending.clear();
      while (!logQueue.isEmpty()) {
        releaseRecordLocked(logQueue.removeFirst());
        discarded++;
      }
    }
    if (discarded > 0) {
      synchronized (queueLock) {
        ioDroppedCount += discarded;
      }
      reportWriteError(new IOException("Discarded " + discarded
          + " retained log record(s) after write failure"));
    }
  }

  private void releaseRecordLocked(LogRecord record) {
    bufferedBytes -= record.estimatedBytes;
    bufferedEntryCount--;
    if (bufferedBytes < 0) {
      bufferedBytes = 0;
    }
    if (bufferedEntryCount < 0) {
      bufferedEntryCount = 0;
    }
  }

  private boolean closeDeadlineExceeded() {
    long deadline = closeDeadlineMillis;
    return !running && deadline > 0 && System.currentTimeMillis() >= deadline;
  }

  private void sleepBeforeRetry(long delayMillis) {
    try {
      Thread.sleep(delayMillis);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      synchronized (queueLock) {
        running = false;
        if (closeDeadlineMillis == 0) {
          closeDeadlineMillis = System.currentTimeMillis() + CLOSE_TIMEOUT_MS;
        }
      }
    }
  }

  private void reportWriteError(Exception error) {
    long now = System.nanoTime();
    if (lastWriteErrorNanos == 0
        || now - lastWriteErrorNanos >= WRITE_ERROR_INTERVAL_NANOS) {
      lastWriteErrorNanos = now;
      reportLogcatError("Failed to write log batch; retrying or dropping after close timeout", error);
    }
  }

  private void reportDropWarning(long droppedSnapshot) {
    reportLogcatWarning("Log queue full; dropping messages (droppedCount="
        + droppedSnapshot + ")");
  }

  /**
   * LogH redirects Logcat into appLogger. Never feed this logger's own
   * diagnostics back into that queue, especially while it is full.
   */
  private static void reportLogcatWarning(String message) {
    Albatross.log(message);
  }

  private static void reportLogcatError(String message, Throwable error) {
    Albatross.log(message,error);
  }

  private static long estimateQueuedBytes(String message) {
    // Character count is an intentionally cheap O(1) estimate. The entry
    // limit is the hard bound; this value only provides a coarse guard.
    return message.length();
  }

  private static Object fileLockFor(File dir, String baseName) {
    String path;
    try {
      path = dir.getCanonicalPath();
    } catch (IOException e) {
      path = dir.getAbsolutePath();
    }
    String key = path + "\n" + String.valueOf(baseName);
    return FILE_LOCKS.computeIfAbsent(key, ignored -> new Object());
  }

  private static final class WriteResult {
    private final boolean success;
    private final boolean summaryWritten;

    private WriteResult(boolean success, boolean summaryWritten) {
      this.success = success;
      this.summaryWritten = summaryWritten;
    }
  }

  private static final class LogRecord {
    private final long timestampMillis;
    private final String message;
    private final long estimatedBytes;

    private LogRecord(long timestampMillis, String message, long estimatedBytes) {
      this.timestampMillis = timestampMillis;
      this.message = message;
      this.estimatedBytes = estimatedBytes;
    }
  }

  public static int cleanupLogFiles(File dir, String baseName) {
    if (dir == null) {
      return 0;
    }
    Object fileLock = fileLockFor(dir, baseName);
    synchronized (fileLock) {
      File[] files = dir.listFiles((d, name) -> name.startsWith(String.valueOf(baseName) + "_"));
      if (files == null) {
        return 0;
      }
      int deletedCount = 0;
      for (File file : files) {
        if (file.delete()) {
          deletedCount++;
        }
      }
      return deletedCount;
    }
  }
}
