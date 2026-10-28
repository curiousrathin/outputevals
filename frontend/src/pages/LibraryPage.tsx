import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FilePlus, FolderPlus, Save, Trash2 } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { LibraryTree } from '../components/LibraryTree'
import { api, type LibraryNode } from '../api'

type NewKind = 'file' | 'folder'

const parentOf = (path: string) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')

export function LibraryPage() {
  const queryClient = useQueryClient()
  const tree = useQuery({ queryKey: ['library'], queryFn: api.libraryTree })
  const [selected, setSelected] = useState<LibraryNode>()
  const [creating, setCreating] = useState<NewKind>()
  const isFile = selected?.type === 'file'
  const baseFolder = !selected ? '' : isFile ? parentOf(selected.path) : selected.path

  const file = useQuery({
    queryKey: ['library-file', selected?.path],
    queryFn: () => api.libraryFile(selected!.path),
    enabled: isFile,
  })
  // Unsaved edits by path; a file with no entry shows its saved content.
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState(false)
  const path = selected?.path ?? ''
  const draft = edits[path] ?? file.data?.content ?? ''
  const dirty = isFile && file.data !== undefined && path in edits && edits[path] !== file.data.content
  const setDraft = (text: string) => setEdits((cur) => ({ ...cur, [path]: text }))
  const dropEdit = (p: string) =>
    setEdits((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => k !== p)))

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['library'] })
  const save = useMutation({
    mutationFn: () => api.saveLibraryFile(path, draft),
    onSuccess: (saved) => {
      queryClient.setQueryData(['library-file', saved.path], saved)
      dropEdit(saved.path)
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteLibraryItem(selected!.path),
    onSuccess: () => {
      setSelected(undefined)
      refresh()
    },
  })

  const select = (node: LibraryNode) => {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    if (selected) dropEdit(selected.path)
    save.reset()
    remove.reset()
    setPreview(false)
    setSelected(node)
  }

  return (
    <>
      <Topbar title="Library" />
      <div className="scroll">
        <div className="page page-wide">
          <div className="eyebrow">Library</div>
          <h1>Knowledge your configurations can use.</h1>
          <p className="lead">
            Markdown files, one folder per skill: definitions, rules, procedures, style guides. Each configuration
            attaches only the folders or files it needs, and every answer records exactly which ones it saw.
          </p>

          <div className="two-col">
            <section className="panel lib-panel">
              <div className="lib-actions">
                <button className="btn btn-sm" onClick={() => setCreating('file')}><FilePlus size={14} /> New file</button>
                <button className="btn btn-sm" onClick={() => setCreating('folder')}><FolderPlus size={14} /> New folder</button>
              </div>
              {creating && (
                <NewItemForm
                  kind={creating}
                  folder={baseFolder}
                  taken={allPaths(tree.data ?? [])}
                  onDone={(node) => {
                    setCreating(undefined)
                    refresh()
                    if (node) select(node)
                  }}
                />
              )}
              {tree.data && tree.data.length > 0 ? (
                <LibraryTree nodes={tree.data} selected={selected?.path} onSelect={select} />
              ) : (
                <p className="muted small lib-empty">
                  Empty so far. Start with a folder per skill, for example <span className="mono">sales-semantics/</span>,
                  holding a <span className="mono">SKILL.md</span> that says what the skill is for, plus files like{' '}
                  <span className="mono">definitions.md</span>.
                </p>
              )}
            </section>

            <section className="panel lib-editor">
              {!selected && <p className="muted">Select a file to edit it, or create one.</p>}
              {selected && !isFile && (
                <>
                  <div className="panel-head">
                    <div className="panel-title mono">{selected.path}/</div>
                    <button className="btn btn-sm btn-danger" onClick={() => remove.mutate()}><Trash2 size={14} /> Delete folder</button>
                  </div>
                  <p className="muted small">
                    {selected.children?.length ? `${selected.children.length} item(s). Only empty folders can be deleted.` : 'Empty folder.'}
                  </p>
                </>
              )}
              {isFile && (
                <>
                  <div className="panel-head">
                    <div className="panel-title mono">{selected.path}{dirty && <span className="pill">unsaved</span>}</div>
                    <div className="lib-actions">
                      <div className="segmented">
                        <button className={!preview ? 'active' : ''} onClick={() => setPreview(false)}>Edit</button>
                        <button className={preview ? 'active' : ''} onClick={() => setPreview(true)}>Preview</button>
                      </div>
                      <button className="btn btn-sm btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
                        <Save size={14} /> {save.isPending ? 'Saving…' : 'Save'}
                      </button>
                      <button className="btn btn-sm btn-danger" onClick={() => remove.mutate()} aria-label="Delete file"><Trash2 size={14} /></button>
                    </div>
                  </div>
                  {file.isLoading && <p className="muted">Loading…</p>}
                  {file.data && (preview ? (
                    <div className="markdown lib-preview"><Markdown remarkPlugins={[remarkGfm]}>{draft}</Markdown></div>
                  ) : (
                    <textarea
                      id="library-editor"
                      className="textarea mono md-editor"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                          e.preventDefault()
                          if (dirty) save.mutate()
                        }
                      }}
                    />
                  ))}
                </>
              )}
              {save.isError && <div className="notice notice-err">{save.error.message}</div>}
              {remove.isError && <div className="notice notice-err">{remove.error.message}</div>}
            </section>
          </div>
        </div>
      </div>
    </>
  )
}

function allPaths(nodes: LibraryNode[]): Set<string> {
  return new Set(nodes.flatMap((n) => [n.path, ...allPaths(n.children ?? [])]))
}

function NewItemForm({ kind, folder, taken, onDone }: {
  kind: NewKind
  folder: string
  taken: Set<string>
  onDone: (node?: LibraryNode) => void
}) {
  const [name, setName] = useState(kind === 'file' ? 'SKILL.md' : '')
  const create = useMutation({
    mutationFn: async () => {
      const clean = name.trim()
      const withExt = kind === 'file' && !/\.(md|txt)$/i.test(clean) ? `${clean}.md` : clean
      const path = folder ? `${folder}/${withExt}` : withExt
      if (taken.has(path)) throw new Error(`${path} already exists. Pick another name.`)
      if (kind === 'folder') {
        await api.createLibraryFolder(path)
        return { path, name: withExt, type: 'folder', children: [] } as LibraryNode
      }
      const title = withExt.replace(/\.(md|txt)$/i, '')
      await api.saveLibraryFile(path, `# ${title}\n\n`)
      return { path, name: withExt, type: 'file' } as LibraryNode
    },
    onSuccess: (node) => onDone(node),
  })
  return (
    <form
      className="lib-new"
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) create.mutate()
      }}
    >
      <label className="label" htmlFor="library-new-name">
        New {kind} in <span className="mono">{folder ? `${folder}/` : 'library root'}</span>
      </label>
      <div className="key-form">
        <input
          id="library-new-name"
          className="input-box"
          autoFocus
          placeholder={kind === 'file' ? 'definitions.md' : 'sales-semantics'}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn btn-primary btn-sm" type="submit" disabled={create.isPending}>Create</button>
        <button className="btn btn-sm" type="button" onClick={() => onDone()}>Cancel</button>
      </div>
      {create.isError && <div className="notice notice-err">{create.error.message}</div>}
    </form>
  )
}
