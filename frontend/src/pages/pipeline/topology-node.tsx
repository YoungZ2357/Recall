import { Handle, Position } from '@xyflow/react';
import type { NodeProps, Node } from '@xyflow/react';
import type { PipelineNodeData } from '../../stores/pipeline-store';
import styles from './topology-node.module.css';

// In RF v12, NodeProps<T> requires T extends Node.
// Alias makes the call-sites readable.
type PN = Node<PipelineNodeData>;

// ---------------------------------------------------------------------------
// Shared base (all three node variants render the same HTML; only class differs)
// ---------------------------------------------------------------------------

interface BaseNodeProps extends NodeProps<PN> {
  roleClass: string;
  /** SOURCE nodes have no inputs; MERGE/TRANSFORM do */
  hasTarget: boolean;
}

function PipelineNodeBase({
  data,
  selected,
  roleClass,
  hasTarget,
}: BaseNodeProps) {
  return (
    <div
      className={[
        styles.node,
        roleClass,
        selected ? styles.selected : '',
        !data.available ? styles.unavailable : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {hasTarget && (
        <Handle type="target" position={Position.Left} className={styles.handle} />
      )}
      <span className={styles.label}>{data.label}</span>
      <Handle type="source" position={Position.Right} className={styles.handle} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported node components registered in topology-canvas
// ---------------------------------------------------------------------------

export function SourceNode(props: NodeProps<PN>) {
  return (
    <PipelineNodeBase {...props} roleClass={styles.source} hasTarget={false} />
  );
}

export function MergeNode(props: NodeProps<PN>) {
  return (
    <PipelineNodeBase {...props} roleClass={styles.merge} hasTarget={true} />
  );
}

export function TransformNode(props: NodeProps<PN>) {
  return (
    <PipelineNodeBase {...props} roleClass={styles.transform} hasTarget={true} />
  );
}
