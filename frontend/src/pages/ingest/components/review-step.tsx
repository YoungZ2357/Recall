import type { IngestConfig, UploadFile } from '../../../types/ingest';
import styles from './review-step.module.css';

function formatTotalSize(files: UploadFile[]): string {
  const bytes = files.reduce((sum, f) => sum + f.size, 0);
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const PDF_PARSER_LABELS: Record<IngestConfig['pdfParser'], string> = {
  pymupdf: 'PyMuPDF',
  marker: 'Marker CLI',
  mineru: 'MinerU API',
};

interface BadgeProps {
  type: 'on' | 'off' | 'info';
  children: React.ReactNode;
}

function Badge({ type, children }: BadgeProps) {
  return <span className={`${styles.badge} ${styles[`badge${type.charAt(0).toUpperCase()}${type.slice(1)}`]}`}>{children}</span>;
}

interface ReviewStepProps {
  files: UploadFile[];
  config: IngestConfig;
  onBack: () => void;
  onStart: () => void;
}

export function ReviewStep({ files, config, onBack, onStart }: ReviewStepProps) {
  const chunkParamLabel =
    config.chunkStrategy === 'recursive'
      ? `chunk_size=${config.chunkSize} · overlap=${config.chunkOverlap}`
      : `target_chunks=${config.targetChunks} · overlap_ratio=${config.overlapRatio}`;

  const estimatedChunks = files.length * (config.chunkStrategy === 'recursive'
    ? Math.ceil(40000 / config.chunkSize) : config.targetChunks);

  return (
    <>
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}><span>📋</span> 摄入配置总览</div>
          <button className={styles.editBtn} onClick={onBack}>✏️ 修改配置</button>
        </div>
        <div className={styles.cardBody}>
          <table className={styles.table}>
            <tbody>
              <tr>
                <td className={styles.tdLabel}>文件</td>
                <td>
                  <strong>{files.length} 个文件</strong>（{formatTotalSize(files)}）<br />
                  <span className={styles.fileNames}>
                    {files.map(f => f.name).join(' · ')}
                  </span>
                </td>
              </tr>
              <tr>
                <td className={styles.tdLabel}>PDF 解析器</td>
                <td><Badge type="info">{PDF_PARSER_LABELS[config.pdfParser]}</Badge></td>
              </tr>
              <tr>
                <td className={styles.tdLabel}>内容过滤</td>
                <td>
                  <Badge type={config.stripTail ? 'on' : 'off'}>
                    strip_tail {config.stripTail ? 'ON' : 'OFF'}
                  </Badge>
                  {' '}
                  <Badge type={config.stripMarkdown ? 'on' : 'off'}>
                    strip_markdown {config.stripMarkdown ? 'ON' : 'OFF'}
                  </Badge>
                </td>
              </tr>
              <tr>
                <td className={styles.tdLabel}>分块策略</td>
                <td>
                  <Badge type="info">
                    {config.chunkStrategy === 'recursive' ? 'Recursive split' : 'Fixed count'}
                  </Badge>
                  {' '}
                  <span className={styles.mono}>{chunkParamLabel}</span>
                </td>
              </tr>
              <tr>
                <td className={styles.tdLabel}>上下文化</td>
                <td>
                  <Badge type={config.contextualize ? 'on' : 'off'}>
                    {config.contextualize ? 'ON' : 'OFF'}
                  </Badge>
                  {config.contextualize && (
                    <span className={styles.mono}>
                      {' '}concurrency={config.contextConcurrency} · DeepSeek V3
                    </span>
                  )}
                </td>
              </tr>
              <tr>
                <td className={styles.tdLabel}>自动打标</td>
                <td>
                  <Badge type={config.autoTag ? 'on' : 'off'}>
                    {config.autoTag ? 'ON' : 'OFF'}
                  </Badge>
                </td>
              </tr>
            </tbody>
          </table>

          {config.contextualize && (
            <div className={styles.warning}>
              <span>⚠️</span>
              <div>
                <strong>上下文化已开启</strong>：预计消耗约 3–5 分钟和 ~{Math.round(estimatedChunks * 600 / 1000)}K tokens 的 LLM API 调用（{files.length} 个文件，预估 ~{estimatedChunks} chunks）。
                确认后开始执行，执行中不可修改配置。
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={styles.actions}>
        <button className={styles.btn} onClick={onBack}>← 修改配置</button>
        <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onStart}>
          ▶ 开始摄入
        </button>
      </div>
    </>
  );
}
