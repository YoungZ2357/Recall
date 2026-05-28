import { useEffect } from 'react';
import { message } from 'antd';
import { AppNav } from '../../components/app-nav';
import { useEvalStore } from '../../stores/eval-store';
import { DatasetList } from './components/dataset-list';
import { GenerateSection } from './components/generate-section';
import { ResultsPanel } from './components/results-panel';
import { RunConfigPanel } from './components/run-config-panel';
import styles from './eval-page.module.css';

export function EvalPage() {
  const testSets = useEvalStore((s) => s.testSets);
  const selectedTestSetName = useEvalStore((s) => s.selectedTestSetName);
  const errorMessage = useEvalStore((s) => s.errorMessage);
  const generatePanelOpen = useEvalStore((s) => s.generatePanelOpen);

  const loadTestSets = useEvalStore((s) => s.loadTestSets);
  const loadReports = useEvalStore((s) => s.loadReports);
  const selectTestSet = useEvalStore((s) => s.selectTestSet);
  const setGeneratePanelOpen = useEvalStore((s) => s.setGeneratePanelOpen);
  const clearError = useEvalStore((s) => s.clearError);

  useEffect(() => {
    void loadTestSets();
    void loadReports();
  }, [loadTestSets, loadReports]);

  useEffect(() => {
    if (errorMessage) {
      void message.error(errorMessage);
      clearError();
    }
  }, [errorMessage, clearError]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <div className={styles.contentArea}>
        {/* Generate validation set — collapsible row */}
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span
              className={
                generatePanelOpen
                  ? `${styles.topBarArrow} ${styles.topBarArrowOpen}`
                  : styles.topBarArrow
              }
              onClick={() => setGeneratePanelOpen(!generatePanelOpen)}
              style={{ cursor: 'pointer' }}
            >
              ▸
            </span>
            <span className={styles.sectionLabel}>Generate validation set</span>
            <span className={styles.topBarHint}>— click to expand</span>
          </div>
        </div>

        <GenerateSection open={generatePanelOpen} />

        {/* Two-column workspace */}
        <div className={styles.grid}>
          <div className={styles.leftCol}>
            <DatasetList
              testSets={testSets}
              selectedName={selectedTestSetName}
              onSelect={selectTestSet}
              onToggleGenerate={() => setGeneratePanelOpen(!generatePanelOpen)}
            />

            <div className={styles.section}>
              <div className={styles.label} style={{ marginBottom: 12 }}>
                <span className={styles.sectionLabel}>Run config</span>
              </div>
              <RunConfigPanel />
            </div>
          </div>

          <div className={styles.rightCol}>
            <ResultsPanel selectedTestSetName={selectedTestSetName} />
          </div>
        </div>
      </div>
    </div>
  );
}
