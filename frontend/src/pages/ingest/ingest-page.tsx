import { useEffect } from 'react';
import { AppNav } from '../../components/app-nav';
import { IngestStepper } from './components/ingest-stepper';
import { UploadStep } from './components/upload-step';
import { ConfigureStep } from './components/configure-step';
import { ReviewStep } from './components/review-step';
import { ResultStep } from './components/result-step';
import { useIngestStore } from '../../stores/ingest-store';
import styles from './ingest-page.module.css';

export function IngestPage() {
  const currentStep      = useIngestStore((s) => s.currentStep);
  const files            = useIngestStore((s) => s.files);
  const config           = useIngestStore((s) => s.config);

  const addFiles         = useIngestStore((s) => s.addFiles);
  const removeFile       = useIngestStore((s) => s.removeFile);
  const setConfig        = useIngestStore((s) => s.setConfig);
  const setStep          = useIngestStore((s) => s.setStep);
  const resetWizard      = useIngestStore((s) => s.resetWizard);
  const resumeIfPending  = useIngestStore((s) => s.resumeIfPending);

  useEffect(() => {
    void resumeIfPending();
  }, [resumeIfPending]);

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
              onNext={() => setStep(1)}
            />
          )}

          {currentStep === 1 && (
            <ConfigureStep
              config={config}
              onConfigChange={setConfig}
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
            />
          )}

          {currentStep === 2 && (
            <ReviewStep
              files={files}
              config={config}
              onBack={() => setStep(1)}
              onStart={() => setStep(3)}
            />
          )}

          {currentStep === 3 && (
            <ResultStep onNewIngest={resetWizard} />
          )}
        </div>
      </div>
    </div>
  );
}
