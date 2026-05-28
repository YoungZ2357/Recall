import '@xyflow/react/dist/style.css';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  Panel,
  type NodeTypes,
  type Connection,
} from '@xyflow/react';
import {
  usePipelineStore,
  type PipelineRFNode,
} from '../../stores/pipeline-store';
import { SourceNode, MergeNode, TransformNode } from './topology-node';
import type { NodeChange, EdgeChange } from '@xyflow/react';
import styles from './topology-canvas.module.css';

// Defined outside component to avoid re-registration on every render
const NODE_TYPES: NodeTypes = {
  sourceNode: SourceNode as NodeTypes[string],
  mergeNode: MergeNode as NodeTypes[string],
  transformNode: TransformNode as NodeTypes[string],
};

export function TopologyCanvas({ readOnly = false }: { readOnly?: boolean }) {
  const rfNodes = usePipelineStore(s => s.rfNodes);
  const rfEdges = usePipelineStore(s => s.rfEdges);
  const onNodesChange = usePipelineStore(s => s.onNodesChange);
  const onEdgesChange = usePipelineStore(s => s.onEdgesChange);
  const onConnect = usePipelineStore(s => s.onConnect);
  const validationResult = usePipelineStore(s => s.validationResult);
  const activeId = usePipelineStore(s => s.activeId);
  const activeName = usePipelineStore(s => s.activeName);

  const isEmpty = rfNodes.length === 0 && (activeId !== null || activeName === '');

  const statusLabel = (() => {
    if (validationResult === null) return '';
    return validationResult.valid ? '· valid' : `· ${validationResult.errors[0] ?? 'invalid'}`;
  })();

  return (
    <div className={styles.canvas}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={(changes: NodeChange<PipelineRFNode>[]) => onNodesChange(changes)}
        onEdgesChange={(changes: EdgeChange[]) => onEdgesChange(changes)}
        onConnect={(conn: Connection) => onConnect(conn)}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={2}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        deleteKeyCode={null}   // disable built-in delete to avoid accidental loss
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={18}
          size={0.7}
          color="var(--border)"
        />
        <Controls
          position="bottom-right"
          showInteractive={false}
          className={styles.controls}
        />

        {/* Empty canvas placeholder */}
        {isEmpty && rfNodes.length === 0 && (
          <Panel position="top-center">
            <span className={styles.emptyHint}>
              Click <strong>+ Add node</strong> to start building a topology
            </span>
          </Panel>
        )}

        {/* Status line: node/edge count + validation */}
        <Panel position="bottom-left">
          <span className={styles.statusLine}>
            {rfNodes.length} nodes · {rfEdges.length} edges{' '}
            <span
              className={
                validationResult?.valid === true
                  ? styles.statusValid
                  : validationResult?.valid === false
                    ? styles.statusInvalid
                    : ''
              }
            >
              {statusLabel}
            </span>
          </span>
        </Panel>
      </ReactFlow>
    </div>
  );
}
