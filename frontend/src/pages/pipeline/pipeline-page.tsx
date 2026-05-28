import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Dropdown, message, Modal, Input, type MenuProps } from 'antd';
import { AppNav } from '../../components/app-nav';
import { usePipelineStore } from '../../stores/pipeline-store';
import { useSearchStore } from '../../stores/search-store';
import { TopologyCanvas } from './topology-canvas';
import { NodeInspector } from './node-inspector';
import styles from './pipeline-page.module.css';

// ---------------------------------------------------------------------------
// Preset sidebar item
// ---------------------------------------------------------------------------

interface PresetItemProps {
  name: string;
  nodeCount: number;
  isBuiltin: boolean;
  isDraft?: boolean;
  active: boolean;
  onClick: () => void;
}

function PresetItem({
  name,
  nodeCount,
  isBuiltin,
  isDraft,
  active,
  onClick,
}: PresetItemProps) {
  return (
    <div
      className={`${styles.presetItem} ${active ? styles.presetItemActive : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick()}
    >
      <div className={styles.presetName}>{name}</div>
      <div className={styles.presetMeta}>
        {isDraft ? (
          <span className={styles.draftBadge}>draft</span>
        ) : null}
        {isBuiltin && !isDraft ? (
          <span className={styles.builtinDot} />
        ) : null}
        <span>{nodeCount} nodes</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function PipelinePage() {
  const navigate = useNavigate();

  // Store state
  const presets = usePipelineStore(s => s.presets);
  const presetsLoaded = usePipelineStore(s => s.presetsLoaded);
  const catalog = usePipelineStore(s => s.catalog);
  const catalogLoaded = usePipelineStore(s => s.catalogLoaded);
  const activeId = usePipelineStore(s => s.activeId);
  const activeName = usePipelineStore(s => s.activeName);
  const isDirty = usePipelineStore(s => s.isDirty);
  const selectedNodeId = usePipelineStore(s => s.selectedNodeId);
  const isValidating = usePipelineStore(s => s.isValidating);
  const isSaving = usePipelineStore(s => s.isSaving);
  const validationResult = usePipelineStore(s => s.validationResult);
  // rfNodes used only for length check and empty-state display
  const rfNodeCount = usePipelineStore(s => s.rfNodes.length);

  // Store actions
  const loadPresetsIfNeeded = usePipelineStore(s => s.loadPresetsIfNeeded);
  const loadCatalogIfNeeded = usePipelineStore(s => s.loadCatalogIfNeeded);
  const openPreset = usePipelineStore(s => s.openPreset);
  const newPreset = usePipelineStore(s => s.newPreset);
  const addNode = usePipelineStore(s => s.addNode);
  const validate = usePipelineStore(s => s.validate);
  const save = usePipelineStore(s => s.save);
  const deletePreset = usePipelineStore(s => s.deletePreset);
  const toSpec = usePipelineStore(s => s.toSpec);

  // Local UI state
  const [filter, setFilter] = useState('');
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [saveNameDraft, setSaveNameDraft] = useState('');

  // Load data on mount
  useEffect(() => {
    void loadPresetsIfNeeded();
    void loadCatalogIfNeeded();
  }, [loadPresetsIfNeeded, loadCatalogIfNeeded]);

  // Auto-open first preset on initial load only — useRef prevents re-firing when user clicks "+ New"
  const didAutoOpen = useRef(false);
  useEffect(() => {
    if (didAutoOpen.current) return;
    if (presetsLoaded && catalogLoaded && presets.length > 0) {
      didAutoOpen.current = true;
      openPreset(presets[0].id);
    }
  }, [presetsLoaded, catalogLoaded, presets, openPreset]);

  // ── derived ────────────────────────────────────────────────────────────────

  const activePreset = activeId != null ? presets.find(p => p.id === activeId) : null;
  const isBuiltin = activePreset?.is_builtin ?? false;

  const filteredPresets = presets.filter(p =>
    p.name.toLowerCase().includes(filter.toLowerCase()),
  );

  // ── Add node menu ──────────────────────────────────────────────────────────

  const ROLE_LABELS: Record<string, string> = {
    SOURCE: 'Retrieve',
    MERGE: 'Merge',
    TRANSFORM: 'Rerank',
  };

  const addNodeMenuItems: MenuProps['items'] = (['SOURCE', 'MERGE', 'TRANSFORM'] as const)
    .flatMap(role => {
      const items = catalog.filter(e => e.node_role === role);
      if (items.length === 0) return [];
      return [
        {
          type: 'group' as const,
          label: ROLE_LABELS[role],
          children: items.map(e => ({
            key: e.node_type,
            label: e.display_name,
            disabled: !e.available,
          })),
        },
      ];
    });

  // ── handlers ──────────────────────────────────────────────────────────────

  async function handleValidate() {
    try {
      const result = await validate();
      if (result.valid) {
        void message.success('Topology is valid');
      } else {
        void message.error(result.errors[0] ?? 'Invalid topology');
      }
    } catch {
      void message.error('Validation request failed');
    }
  }

  function handleTestRun() {
    const spec = toSpec();
    useSearchStore.getState().setConfig({
      topo: 'custom',
      customJson: JSON.stringify(spec, null, 2),
    });
    void navigate('/search');
  }

  function openSaveModal() {
    const defaultName = isBuiltin ? '' : (activeName || '');
    setSaveNameDraft(defaultName);
    setSaveModalOpen(true);
  }

  async function handleSaveConfirm() {
    const name = saveNameDraft.trim();
    if (!name) {
      void message.error('Please enter a name');
      return;
    }
    setSaveModalOpen(false);
    try {
      await save(name);
      void message.success('Saved');
    } catch {
      void message.error('Save failed');
    }
  }

  async function handleDeletePreset() {
    if (!activePreset) return;
    Modal.confirm({
      title: `Delete "${activePreset.name}"?`,
      content: 'This action cannot be undone.',
      okText: 'Delete',
      okType: 'danger',
      onOk: async () => {
        try {
          await deletePreset(activePreset.id);
          void message.success('Deleted');
        } catch {
          void message.error('Delete failed');
        }
      },
    });
  }

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className={styles.shell}>
      <AppNav />

      <div className={styles.body}>
        {/* ── Left sidebar: topology list ── */}
        <aside className={styles.sidebar}>
          <div className={styles.sidebarHeader}>
            <span className={styles.sidebarTitle}>Topologies</span>
            <button className={styles.newBtn} onClick={newPreset}>
              + New
            </button>
          </div>

          <input
            className={styles.filterInput}
            placeholder="Filter…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />

          {!presetsLoaded ? (
            <span className={styles.loadingMsg}>Loading…</span>
          ) : filteredPresets.length === 0 ? (
            <span className={styles.loadingMsg}>No topologies</span>
          ) : (
            filteredPresets.map(p => (
              <PresetItem
                key={p.id}
                name={p.name}
                nodeCount={p.spec.nodes.length}
                isBuiltin={p.is_builtin}
                active={p.id === activeId}
                onClick={() => openPreset(p.id)}
              />
            ))
          )}

          {/* New unsaved topology entry */}
          {activeId === null && activeName === '' && (
            <PresetItem
              name="New topology"
              nodeCount={rfNodeCount}
              isBuiltin={false}
              isDraft
              active
              onClick={() => { /* already active */ }}
            />
          )}
        </aside>

        {/* ── Right: editor area ── */}
        <div className={styles.main}>
          {activeId === null && activeName === '' && rfNodeCount === 0 && !presetsLoaded ? (
            <div className={styles.emptyState}>Select or create a topology</div>
          ) : (
            <>
              {/* Topology header */}
              <div className={styles.topoHeader}>
                <span className={styles.topoName}>
                  {activeName || 'Untitled'}
                  {isDirty && <span className={styles.dirtyDot} title="Unsaved changes" />}
                </span>
                {isBuiltin && (
                  <span className={styles.builtinBadge}>built-in</span>
                )}
                {activePreset?.created_at && (
                  <span className={styles.topoDate}>
                    updated {activePreset.created_at.slice(0, 10)}
                  </span>
                )}
                <div className={styles.topoActions}>
                  {!isBuiltin && activePreset && (
                    <button className={styles.headerBtn} onClick={handleDeletePreset}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Toolbar */}
              <div className={styles.toolbar}>
                <Dropdown
                  menu={{
                    items: addNodeMenuItems,
                    onClick: ({ key }) => addNode(key),
                  }}
                  trigger={['click']}
                  disabled={!catalogLoaded || isBuiltin}
                >
                  <button className={styles.toolBtnPrimary} disabled={!catalogLoaded || isBuiltin}>
                    + Add node ▾
                  </button>
                </Dropdown>

                <button
                  className={styles.toolBtn}
                  onClick={() => void handleValidate()}
                  disabled={isValidating}
                >
                  {isValidating ? 'Validating…' : '✓ Validate'}
                </button>

                <button
                  className={styles.toolBtn}
                  onClick={handleTestRun}
                  disabled={rfNodeCount === 0}
                >
                  ▶ Test run
                </button>

                <button
                  className={`${styles.toolBtn} ${styles.toolBtnSave}`}
                  onClick={openSaveModal}
                  disabled={isSaving}
                >
                  {isSaving ? 'Saving…' : isBuiltin ? '⑂ Fork' : '💾 Save'}
                </button>
              </div>

              {/* Canvas + Inspector */}
              <div className={styles.canvasWrap}>
                <TopologyCanvas readOnly={isBuiltin} />
                {selectedNodeId !== null && <NodeInspector readOnly={isBuiltin} />}
              </div>

              {/* Validation error banner */}
              {validationResult && !validationResult.valid && (
                <div className={styles.errorBanner}>
                  {validationResult.errors.join(' · ')}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Save modal */}
      <Modal
        title={isBuiltin ? 'Save as new topology' : 'Save topology'}
        open={saveModalOpen}
        onOk={() => void handleSaveConfirm()}
        onCancel={() => setSaveModalOpen(false)}
        okText="Save"
        okButtonProps={{ disabled: !saveNameDraft.trim() }}
      >
        <Input
          placeholder="Topology name"
          value={saveNameDraft}
          onChange={e => setSaveNameDraft(e.target.value)}
          onPressEnter={() => void handleSaveConfirm()}
          autoFocus
        />
        {isBuiltin && (
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, marginBottom: 0 }}>
            Built-in topologies cannot be overwritten — a new copy will be created.
          </p>
        )}
      </Modal>
    </div>
  );
}
