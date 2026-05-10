import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { IngestConfig, IngestTask, UploadFile } from '../../../types/ingest';
import { startIngestion, pollTaskStatus } from '../../../api/ingest';
import { StageProgress } from './stage-progress';
import styles from './result-step.module.css';

function formatDuration(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.round((end - start) / 1000);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`;
}

interface ResultStepProps {
  files: UploadFile[];
  config: IngestConfig;
  onNewIngest: () => void;
}

export function ResultStep({ files, config, onNewIngest }: ResultStepProps) {
  const navigate = useNavigate();
  const [task, setTask] = useState<IngestTask | null>(null);
  const taskIdRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      const taskId = await startIngestion(files, config);
      if (cancelled) return;
      taskIdRef.current = taskId;

      // Poll immediately then every 1000ms
      async function poll() {
        if (!taskIdRef.current || cancelled) return;
        const t = await pollTaskStatus(taskIdRef.current, files);
        if (cancelled) return;
        setTask(t);
        if (t.status === 'done') {
          if (timerRef.current) clearInterval(timerRef.current);
        }
      }

      await poll();
      timerRef.current = setInterval(poll, 1000);
    }

    init();

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!task) {
    return <div className={styles.loading}>初始化中…</div>;
  }

  const totalChunks = task.files.reduce((sum, f) => sum + (f.chunkCount ?? 0), 0);
  const writtenFiles = task.files.filter(f => f.status === 'done').length;
  const failedFiles = task.files.filter(f => f.status === 'error');
  const isDone = task.status === 'done';
  const doneFiles = task.files.filter(f => f.status === 'done').length;

  return (
    <>
      {/* Metric cards */}
      <div className={styles.metricRow}>
        <div className={styles.metricBox}>
          <div className={styles.metricLabel}>文件进度</div>
          <div className={`${styles.metricValue} ${isDone ? styles.metricSuccess : styles.metricRunning}`}>
            {doneFiles + failedFiles.length} / {task.files.length}
          </div>
        </div>
        <div className={styles.metricBox}>
          <div className={styles.metricLabel}>已生成 Chunks</div>
          <div className={styles.metricValue}>{totalChunks}</div>
        </div>
        <div className={styles.metricBox}>
          <div className={styles.metricLabel}>已写入</div>
          <div className={`${styles.metricValue} ${styles.metricSuccess}`}>{writtenFiles}</div>
        </div>
        <div className={styles.metricBox}>
          <div className={styles.metricLabel}>状态</div>
          <div className={`${styles.metricValue} ${isDone ? (failedFiles.length > 0 ? styles.metricError : styles.metricSuccess) : styles.metricRunning}`}>
            {isDone ? (failedFiles.length > 0 ? '部分失败' : '完成') : '运行中'}
          </div>
        </div>
      </div>

      {/* Per-file progress */}
      <div className={styles.card}>
        <div className={styles.cardBody}>
          {task.files.map(f => (
            <StageProgress key={f.fileId} fileStatus={f} />
          ))}
        </div>
      </div>

      {/* Result summaries (shown when done) */}
      {isDone && (
        <>
          <div className={styles.resultSummary}>
            <h3>✅ 摄入完成（{writtenFiles}/{task.files.length} 成功）</h3>
            <div className={styles.resultGrid}>
              <div className={styles.resultItem}>
                <div className={styles.rdl}>成功文件</div>
                <div className={styles.rdv}>{writtenFiles}</div>
              </div>
              <div className={styles.resultItem}>
                <div className={styles.rdl}>总 Chunks</div>
                <div className={styles.rdv}>{totalChunks}</div>
              </div>
              <div className={styles.resultItem}>
                <div className={styles.rdl}>耗时</div>
                <div className={styles.rdv}>{formatDuration(task.startedAt, task.completedAt)}</div>
              </div>
            </div>
          </div>

          {failedFiles.length > 0 && (
            <div className={styles.errorSummary}>
              <h3>⚠ {failedFiles.length} 个文件失败</h3>
              {failedFiles.map(f => (
                <div key={f.fileId} className={styles.errorFile}>
                  <span>{f.fileName}</span>
                  <span className={styles.errorMsg}>{f.error}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Bottom actions */}
      {isDone && (
        <div className={styles.actions}>
          {failedFiles.length > 0 && (
            <button className={styles.btn} onClick={onNewIngest}>
              ← 重新摄入失败文件
            </button>
          )}
          <div className={styles.actionRight}>
            <button className={styles.btn} onClick={() => navigate('/library')}>
              查看文档列表
            </button>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onNewIngest}>
              开始新摄入
            </button>
          </div>
        </div>
      )}
    </>
  );
}
