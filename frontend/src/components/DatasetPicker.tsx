import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSpreadsheet, Upload } from 'lucide-react'
import { api, timeAgo, type Dataset } from '../api'

export function UploadZone({ onUploaded }: { onUploaded: (d: Dataset) => void }) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const upload = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: (d) => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      onUploaded(d)
    },
  })
  const pick = (files: FileList | null) => files?.[0] && upload.mutate(files[0])

  return (
    <div
      className={`dropzone${dragging ? ' dragging' : ''}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        pick(e.dataTransfer.files)
      }}
    >
      <input ref={input} type="file" accept=".csv" hidden onChange={(e) => pick(e.target.files)} />
      <Upload size={20} />
      <div className="dropzone-title">{upload.isPending ? 'Uploading…' : 'Drop a CSV here, or click to browse'}</div>
      <div className="dropzone-sub">Stored untouched. The original file is always the baseline.</div>
      {upload.isError && <div className="error-text">{upload.error.message}</div>}
    </div>
  )
}

export function DatasetList({
  selected,
  onSelect,
}: {
  selected?: string
  onSelect: (d: Dataset) => void
}) {
  const { data = [] } = useQuery({ queryKey: ['datasets'], queryFn: api.datasets })
  if (!data.length) return null
  return (
    <div className="pick-list">
      {data.map((d) => (
        <button
          key={d.id}
          className={`pick-item${selected === d.id ? ' selected' : ''}`}
          onClick={() => onSelect(d)}
        >
          <FileSpreadsheet size={16} />
          <span className="pick-name">{d.name}</span>
          <span className="pick-meta">
            {d.row_count.toLocaleString()} rows · {d.columns.length} fields · {timeAgo(d.created_at)}
          </span>
        </button>
      ))}
    </div>
  )
}

export function PreviewTable({ datasetId }: { datasetId: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['preview', datasetId], queryFn: () => api.preview(datasetId) })
  if (isLoading || !data) return <div className="muted">Loading preview…</div>
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i}>
              {row.map((v, j) => (
                <td key={j} className={v === null ? 'null' : ''}>{v === null ? '—' : String(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
