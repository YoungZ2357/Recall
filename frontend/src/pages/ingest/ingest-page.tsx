import { useState } from 'react';
import { AppNav } from '../../components/app-nav';
import { IngestStepper } from './components/ingest-stepper';
import { UploadStep } from './components/upload-step';
import { ConfigureStep } from './components/configure-step';
import { ReviewStep } from './components/review-step';
import { ResultStep } from './components/result-step';
import type { IngestConfig, UploadFile } from '../../types/ingest';
import styles from './ingest-page.module.css';

export const DEFAULT_INGEST_CONFIG: IngestConfig = {
  pdfParser: 'pymupdf',
  stripTail: true,
  stripMarkdown: false,
  chunkStrategy: 'recursive',
  chunkSize: 512,
  chunkOverlap: 64,
  targetChunks: 20,
  overlapRatio: 0.1,
  contextualize: true,
  contextConcurrency: 8,
  autoTag: true,
};

export function IngestPage() {
  const [currentStep, setCurrentStep] = useState(0);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [config, setConfig] = useState<IngestConfig>(DEFAULT_INGEST_CONFIG);

  function addFiles(newFiles: File[]) {
    const mapped: UploadFile[] = newFiles.map(f => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
      const type = (ext === 'pdf' ? 'pdf' : ext === 'md' ? 'md' : 'txt') as UploadFile['type'];
      return {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file: f,
        name: f.name,
        size: f.size,
        type,
      };
    });
    setFiles(prev => [...prev, ...mapped]);
  }

  function removeFile(id: string) {
    setFiles(prev => prev.filter(f => f.id !== id));
  }

  function updateConfig(partial: Partial<IngestConfig>) {
    setConfig(prev => ({ ...prev, ...partial }));
  }

  function resetWizard() {
    setCurrentStep(0);
    setFiles([]);
    setConfig(DEFAULT_INGEST_CONFIG);
  }

  return (
    <div className={styles.shell}>
      <AppNav />
      <div className={styles.contentArea}>
        <div className={styles.container}>
          <div className={styles.header}>
            <div className={styles.breadcrumb}>Library / Ingest</div>
            <h1 className={styles.title}>文档摄入</h1>
          </div>

          <IngestStepper currentStep={currentStep} />

          {currentStep === 0 && (
            <UploadStep
              files={files}
              onAddFiles={addFiles}
              onRemoveFile={removeFile}
              onNext={() => setCurrentStep(1)}
            />
          )}

          {currentStep === 1 && (
            <ConfigureStep
              config={config}
              onConfigChange={updateConfig}
              onBack={() => setCurrentStep(0)}
              onNext={() => setCurrentStep(2)}
            />
          )}

          {currentStep === 2 && (
            <ReviewStep
              files={files}
              config={config}
              onBack={() => setCurrentStep(1)}
              onStart={() => setCurrentStep(3)}
            />
          )}

          {currentStep === 3 && (
            <ResultStep
              files={files}
              config={config}
              onNewIngest={resetWizard}
            />
          )}
        </div>
      </div>
    </div>
  );
}
