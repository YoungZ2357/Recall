import type { IngestConfig } from '../../../types/ingest';
import styles from './configure-step.module.css';

interface ConfigureStepProps {
  config: IngestConfig;
  onConfigChange: (partial: Partial<IngestConfig>) => void;
  onBack: () => void;
  onNext: () => void;
}

const PDF_PARSERS: { value: IngestConfig['pdfParser']; label: string; desc: string }[] = [
  { value: 'pymupdf', label: 'PyMuPDF', desc: '轻量 CPU，默认' },
  { value: 'marker', label: 'Marker CLI', desc: '高质量 Markdown' },
  { value: 'mineru', label: 'MinerU API', desc: '结构化 PDF' },
];

interface ToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
}

function Toggle({ on, onChange }: ToggleProps) {
  return (
    <div
      className={`${styles.toggleSwitch} ${on ? styles.toggleOn : ''}`}
      onClick={() => onChange(!on)}
      role="switch"
      aria-checked={on}
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' || e.key === ' ' ? onChange(!on) : undefined}
    >
      <div className={styles.toggleThumb} />
    </div>
  );
}

export function ConfigureStep({ config, onConfigChange, onBack, onNext }: ConfigureStepProps) {
  return (
    <>
      {/* Card 1: Parse + Filter */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}><span>📄</span> 解析 + 过滤</div>
        </div>
        <div className={styles.cardBody}>
          <div className={styles.section}>
            <div className={styles.sectionTitle}>PDF 解析器</div>
            <div className={styles.pillGroup}>
              {PDF_PARSERS.map(p => (
                <div
                  key={p.value}
                  className={`${styles.pill} ${config.pdfParser === p.value ? styles.pillActive : ''}`}
                  onClick={() => onConfigChange({ pdfParser: p.value })}
                >
                  {p.label}
                  <span className={styles.pillDesc}>{p.desc}</span>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.section}>
            <div className={styles.sectionTitle}>内容过滤</div>
            <div className={styles.toggleRow}>
              <div className={styles.toggleInfo}>
                <div className={styles.toggleLabel}>Strip tail references</div>
                <div className={styles.toggleDesc}>段落级引用密度启发式扫描，截断尾部参考文献</div>
              </div>
              <Toggle on={config.stripTail} onChange={v => onConfigChange({ stripTail: v })} />
            </div>
            <div className={styles.toggleRow}>
              <div className={styles.toggleInfo}>
                <div className={styles.toggleLabel}>Strip markdown sections</div>
                <div className={styles.toggleDesc}>扫描 Markdown 标题，精确切除 References / Appendix 段落</div>
              </div>
              <Toggle on={config.stripMarkdown} onChange={v => onConfigChange({ stripMarkdown: v })} />
            </div>
          </div>
        </div>
      </div>

      {/* Card 2: Chunking */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}><span>✂️</span> 分块策略</div>
        </div>
        <div className={styles.cardBody}>
          <div className={styles.section}>
            <div className={styles.pillGroup}>
              <div
                className={`${styles.pill} ${config.chunkStrategy === 'recursive' ? styles.pillActive : ''}`}
                onClick={() => onConfigChange({ chunkStrategy: 'recursive' })}
              >
                Recursive split
                <span className={styles.pillDesc}>从粗粒度向细粒度回退</span>
              </div>
              <div
                className={`${styles.pill} ${config.chunkStrategy === 'fixed_count' ? styles.pillActive : ''}`}
                onClick={() => onConfigChange({ chunkStrategy: 'fixed_count' })}
              >
                Fixed count
                <span className={styles.pillDesc}>均匀切分为 N 块</span>
              </div>
            </div>
          </div>

          {config.chunkStrategy === 'recursive' && (
            <div className={styles.conditionalParams}>
              <div className={styles.paramGrid}>
                <div className={styles.paramItem}>
                  <label>Chunk size</label>
                  <input
                    type="number"
                    value={config.chunkSize}
                    min={64}
                    max={4096}
                    onChange={e => onConfigChange({ chunkSize: Number(e.target.value) })}
                  />
                  <div className={styles.paramHint}>每块最大字符数</div>
                </div>
                <div className={styles.paramItem}>
                  <label>Overlap</label>
                  <input
                    type="number"
                    value={config.chunkOverlap}
                    min={0}
                    max={512}
                    onChange={e => onConfigChange({ chunkOverlap: Number(e.target.value) })}
                  />
                  <div className={styles.paramHint}>相邻块重叠字符数</div>
                </div>
              </div>
            </div>
          )}

          {config.chunkStrategy === 'fixed_count' && (
            <div className={styles.conditionalParams}>
              <div className={styles.paramGrid}>
                <div className={styles.paramItem}>
                  <label>Target chunks</label>
                  <input
                    type="number"
                    value={config.targetChunks}
                    min={2}
                    max={200}
                    onChange={e => onConfigChange({ targetChunks: Number(e.target.value) })}
                  />
                  <div className={styles.paramHint}>目标分块数量</div>
                </div>
                <div className={styles.paramItem}>
                  <label>Overlap ratio</label>
                  <input
                    type="number"
                    value={config.overlapRatio}
                    min={0}
                    max={0.5}
                    step={0.05}
                    onChange={e => onConfigChange({ overlapRatio: Number(e.target.value) })}
                  />
                  <div className={styles.paramHint}>重叠比例 (0–0.5)</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Card 3: Enrichment */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitle}><span>🧠</span> 增强选项</div>
        </div>
        <div className={styles.cardBody}>
          <div className={styles.toggleRow}>
            <div className={styles.toggleInfo}>
              <div className={styles.toggleLabel}>上下文化 (Contextualization)</div>
              <div className={styles.toggleDesc}>为每个 chunk 生成 LLM 文档级上下文前缀，拼接后嵌入。显著提升召回，增加耗时和 API 费用。</div>
            </div>
            <Toggle on={config.contextualize} onChange={v => onConfigChange({ contextualize: v })} />
          </div>

          {config.contextualize && (
            <div className={`${styles.conditionalParams} ${styles.conditionalParamsInline}`}>
              <div className={styles.paramGrid}>
                <div className={styles.paramItem}>
                  <label>并发数</label>
                  <input
                    type="number"
                    value={config.contextConcurrency}
                    min={1}
                    max={32}
                    onChange={e => onConfigChange({ contextConcurrency: Number(e.target.value) })}
                  />
                  <div className={styles.paramHint}>chunk 级并行 LLM 调用数</div>
                </div>
                <div className={styles.paramItem}>
                  <label>LLM Provider</label>
                  <input type="text" value="DeepSeek V3" disabled />
                  <div className={styles.paramHint}>当前固定，未来可配置</div>
                </div>
              </div>
            </div>
          )}

          <div className={`${styles.toggleRow} ${styles.toggleRowLast}`}>
            <div className={styles.toggleInfo}>
              <div className={styles.toggleLabel}>自动打标 (Auto-Tagging)</div>
              <div className={styles.toggleDesc}>LLM 为文档生成主题标签（≤ 10 个），所有 chunk 继承。参考已有全局标签池以复用标签。</div>
            </div>
            <Toggle on={config.autoTag} onChange={v => onConfigChange({ autoTag: v })} />
          </div>
        </div>
      </div>

      <div className={styles.actions}>
        <button className={styles.btn} onClick={onBack}>← 返回上传</button>
        <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onNext}>
          下一步：确认摄入 →
        </button>
      </div>
    </>
  );
}
