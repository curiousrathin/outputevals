import { useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Folder } from 'lucide-react'
import type { LibraryNode } from '../api'

interface Props {
  nodes: LibraryNode[]
  /** Library page: the open file or folder. */
  selected?: string
  onSelect?: (node: LibraryNode) => void
  /** Configuration wizard: attached paths. Attaching a folder covers everything inside it. */
  attached?: string[]
  onToggle?: (path: string) => void
}

const covers = (attached: string[], path: string) =>
  attached.some((a) => path !== a && path.startsWith(`${a}/`))

export function LibraryTree(props: Props) {
  return (
    <ul className="lib-tree" role="tree">
      {props.nodes.map((n) => <Row key={n.path} node={n} depth={0} {...props} />)}
    </ul>
  )
}

function Row({ node, depth, ...props }: Props & { node: LibraryNode; depth: number }) {
  const [open, setOpen] = useState(true)
  const { selected, onSelect, attached, onToggle } = props
  const isFolder = node.type === 'folder'
  const coveredByParent = attached ? covers(attached, node.path) : false
  const checked = attached ? attached.includes(node.path) || coveredByParent : false

  return (
    <li role="treeitem" aria-expanded={isFolder ? open : undefined} aria-selected={selected === node.path}>
      <div className={`lib-row${selected === node.path ? ' selected' : ''}`} style={{ paddingLeft: 8 + depth * 16 }}>
        {isFolder ? (
          <button className="lib-caret" onClick={() => setOpen(!open)} aria-label={open ? 'Collapse' : 'Expand'}>
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="lib-caret" />
        )}
        {attached && onToggle && (
          <input
            type="checkbox"
            id={`attach-${node.path}`}
            checked={checked}
            disabled={coveredByParent}
            title={coveredByParent ? 'Included because its folder is attached' : undefined}
            onChange={() => onToggle(node.path)}
          />
        )}
        <label
          className="lib-name"
          htmlFor={attached ? `attach-${node.path}` : undefined}
          onClick={() => onSelect?.(node)}
        >
          {isFolder ? <Folder size={15} /> : <FileText size={15} />}
          <span>{node.name}</span>
          {isFolder && node.children && <span className="lib-count">{countFiles(node)}</span>}
        </label>
      </div>
      {isFolder && open && node.children && node.children.length > 0 && (
        <ul role="group">
          {node.children.map((c) => <Row key={c.path} node={c} depth={depth + 1} {...props} />)}
        </ul>
      )}
    </li>
  )
}

function countFiles(node: LibraryNode): number {
  return (node.children ?? []).reduce((n, c) => n + (c.type === 'file' ? 1 : countFiles(c)), 0)
}
