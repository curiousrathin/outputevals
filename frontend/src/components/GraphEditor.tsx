import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  ConnectionMode,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ArrowRight, Trash2 } from 'lucide-react'
import type { Column, ConfigEdge, ConfigNode } from '../api'

type FieldData = { label: string; dtype: string; described: boolean }
type FieldNode = Node<FieldData, 'field'>

function FieldNodeView({ data, selected }: NodeProps<FieldNode>) {
  return (
    <div className={`field-node${selected ? ' selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="field-node-name">{data.label}</div>
      <div className="field-node-meta">
        {data.dtype}
        {data.described && <span className="described-dot" title="Has a description" />}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { field: FieldNodeView }

type Selection = { kind: 'node' | 'edge'; id: string } | null

interface Props {
  columns: Column[]
  nodes: ConfigNode[]
  edges: ConfigEdge[]
  onChange: (nodes: ConfigNode[], edges: ConfigEdge[]) => void
}

const newId = () => crypto.randomUUID().replace(/-/g, '').slice(0, 12)
const truncate = (s: string, n = 36) => (s.length > n ? `${s.slice(0, n)}…` : s)

export function GraphEditor({ columns, nodes, edges, onChange }: Props) {
  const colInfo = useMemo(() => Object.fromEntries(columns.map((c) => [c.name, c])), [columns])
  const [selection, setSelection] = useState<Selection>(null)
  const [draft, setDraft] = useState({ source: '', target: '', description: '' })

  // React Flow owns node state (it needs measured sizes); we sync positions back on drag stop.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<FieldNode>(
    nodes.map((n) => ({
      id: n.id,
      type: 'field',
      position: { x: n.x, y: n.y },
      data: { label: n.id, dtype: colInfo[n.id]?.dtype ?? '', described: !!n.description.trim() },
    })),
  )
  useEffect(() => {
    const described = Object.fromEntries(nodes.map((n) => [n.id, !!n.description.trim()]))
    setRfNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, described: described[n.id] ?? false } })))
  }, [nodes, setRfNodes])

  const rfEdges: Edge[] = edges.map((e) => ({
    id: e.id!,
    source: e.source,
    target: e.target,
    label: truncate(e.description),
    selected: selection?.kind === 'edge' && selection.id === e.id,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
  }))

  const updateNode = (id: string, description: string) =>
    onChange(nodes.map((n) => (n.id === id ? { ...n, description } : n)), edges)
  const updateEdge = (id: string, description: string) =>
    onChange(nodes, edges.map((e) => (e.id === id ? { ...e, description } : e)))
  const removeEdge = (id: string) => {
    onChange(nodes, edges.filter((e) => e.id !== id))
    setSelection(null)
  }
  const addEdge = () => {
    const edge = { id: newId(), ...draft, description: draft.description.trim() }
    onChange(nodes, [...edges, edge])
    setDraft({ source: '', target: '', description: '' })
    setSelection({ kind: 'edge', id: edge.id })
  }
  const canAdd = draft.source && draft.target && draft.source !== draft.target && draft.description.trim()

  const selNode = selection?.kind === 'node' ? nodes.find((n) => n.id === selection.id) : undefined
  const selEdge = selection?.kind === 'edge' ? edges.find((e) => e.id === selection.id) : undefined

  return (
    <div className="graph-shell">
      <div className="graph-canvas">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={(_e, _n, moved) => {
            const pos = Object.fromEntries(moved.map((m) => [m.id, m.position]))
            onChange(nodes.map((n) => (pos[n.id] ? { ...n, x: pos[n.id].x, y: pos[n.id].y } : n)), edges)
          }}
          onNodeClick={(_e, n) => setSelection({ kind: 'node', id: n.id })}
          onEdgeClick={(_e, ed) => setSelection({ kind: 'edge', id: ed.id })}
          onPaneClick={() => setSelection(null)}
          onConnect={(c) => {
            if (c.source && c.target && c.source !== c.target) {
              setSelection(null)
              setDraft({ source: c.source, target: c.target, description: '' })
            }
          }}
          connectionMode={ConnectionMode.Loose}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="#e6e6e6" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <aside className="graph-panel">
        {selNode ? (
          <>
            <div className="panel-label">Field</div>
            <div className="panel-title">{selNode.id}</div>
            <div className="muted small">
              {colInfo[selNode.id]?.dtype} · {colInfo[selNode.id]?.unique.toLocaleString()} unique
              {colInfo[selNode.id]?.samples.length ? ` · e.g. ${colInfo[selNode.id].samples.join(', ')}` : ''}
            </div>
            <label className="label">What does this field mean?</label>
            <textarea
              className="textarea"
              rows={4}
              placeholder="e.g. Invoice total in USD, before tax"
              value={selNode.description}
              onChange={(e) => updateNode(selNode.id, e.target.value)}
            />
            <div className="panel-label" style={{ marginTop: 18 }}>Connections</div>
            {edges.filter((e) => e.source === selNode.id || e.target === selNode.id).map((e) => (
              <button key={e.id} className="conn-row" onClick={() => setSelection({ kind: 'edge', id: e.id! })}>
                <span className="mono">{e.source} → {e.target}</span>
                <span className="muted">{truncate(e.description, 48)}</span>
              </button>
            ))}
            {!edges.some((e) => e.source === selNode.id || e.target === selNode.id) && (
              <div className="muted small">None yet. Drag from this field's right dot to another field.</div>
            )}
          </>
        ) : selEdge ? (
          <>
            <div className="panel-label">Connection</div>
            <div className="panel-title conn-title">
              {selEdge.source} <ArrowRight size={14} /> {selEdge.target}
            </div>
            <label className="label">How are they related? (plain English)</label>
            <textarea
              className="textarea"
              rows={4}
              value={selEdge.description}
              onChange={(e) => updateEdge(selEdge.id!, e.target.value)}
            />
            <button className="btn btn-danger" style={{ marginTop: 12 }} onClick={() => removeEdge(selEdge.id!)}>
              <Trash2 size={14} /> Remove connection
            </button>
          </>
        ) : (
          <>
            <div className="panel-label">New connection</div>
            <p className="muted small" style={{ marginTop: 4 }}>
              Drag between two fields on the canvas, or pick them here. Click a field to describe what it means.
            </p>
            <div className="conn-selects">
              <select className="select" value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
                <option value="">From field…</option>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.id}</option>)}
              </select>
              <ArrowRight size={14} className="muted" />
              <select className="select" value={draft.target} onChange={(e) => setDraft({ ...draft, target: e.target.value })}>
                <option value="">To field…</option>
                {nodes.filter((n) => n.id !== draft.source).map((n) => <option key={n.id} value={n.id}>{n.id}</option>)}
              </select>
            </div>
            <textarea
              className="textarea"
              rows={3}
              placeholder="e.g. approved_by is the employee ID of whoever signed off on the invoice"
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
            <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={!canAdd} onClick={addEdge}>
              Add connection
            </button>
            <div className="graph-stats muted small">
              {nodes.filter((n) => n.description.trim()).length} of {nodes.length} fields described · {edges.length} connections
            </div>
          </>
        )}
      </aside>
    </div>
  )
}
