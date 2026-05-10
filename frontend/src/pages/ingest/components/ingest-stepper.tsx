import styles from './ingest-stepper.module.css';

const STEPS = ['上传文件', '配置管道', '确认摄入', '执行结果'] as const;

interface IngestStepperProps {
  currentStep: number;
}

export function IngestStepper({ currentStep }: IngestStepperProps) {
  return (
    <div className={styles.stepper}>
      {STEPS.map((label, idx) => {
        const state = idx < currentStep ? 'done' : idx === currentStep ? 'active' : 'pending';
        return (
          <div key={idx} className={`${styles.item} ${styles[state]}`}>
            <div className={styles.dot}>
              {state === 'done' ? '✓' : idx + 1}
            </div>
            <div className={styles.label}>{label}</div>
          </div>
        );
      })}
    </div>
  );
}
