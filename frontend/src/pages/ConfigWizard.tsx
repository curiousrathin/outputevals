import { useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, FileText } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { DatasetList, PreviewTable, UploadZone } from '../components/DatasetPicker'
import { GraphEditor } from '../components/GraphEditor'
import { api, type ConfigEdge, type ConfigNode, type Configuration, type Dataset } from '../api'

const steps = ['Dataset', 'Fields & connections', 'Context', 'Save']

function gridNodes(d: Dataset): ConfigNode[] {
  return d.columns.map((c, i) => ({ id: c.name, description: '', x: (i % 4) * 240, y: Math.floor(i / 4) * 130 }))
}

export function ConfigWizard() {
  const { id } = useParams()
  const existing = useQuery({ queryKey: ['configuration', id], queryFn: () => api.configuration(id!), enabled: !!id })
  if (id && !existing.data) {
    return <Topbar title={existing.isError ? existing.error.message : 'Loading…'} />
  }
  return <Wizard key={id ?? 'new'} initial={existing.data} />
}

function Wizard({ initial }: { initial?: Configuration }) {
  const id = initial?.id
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isNew = !initial

  const [step, setStep] = useState(isNew && !params.get('dataset') ? 0 : 1)
  const [datasetId, setDatasetId] = useState(initial?.dataset_id ?? params.get('dataset') ?? '')
  const [name, setName] = useState(initial?.name ?? '')
  const [nodeState, setNodes] = useState<ConfigNode[]>(initial?.nodes ?? [])
  const [edges, setEdges] = useState<ConfigEdge[]>(initial?.edges ?? [])
  const [context, setContext] = useState(initial?.context_markdown ?? '')
  const [createExperiment, setCreateExperiment] = useState(isNew)
  const [experimentName, setExperimentName] = useState('')
  const mdInput = useRef<HTMLInputElement>(null)

  const dataset = useQuery({ queryKey: ['dataset', datasetId], queryFn: () => api.dataset(datasetId), enabled: !!datasetId })
  // Until the user edits the graph, a new configuration has one node per column.
  const nodes = nodeState.length || !dataset.data ? nodeState : gridNodes(dataset.data)
  const defaultName = dataset.data ? `${dataset.data.name} config` : 'Untitled configuration'
  const defaultExperimentName = dataset.data ? `${dataset.data.name} experiment` : 'Untitled experiment'

  const chooseDataset = (d: Dataset) => {
    setDatasetId(d.id)
    setNodes(gridNodes(d))
    setEdges([])
  }

  const save = useMutation({
    mutationFn: async () => {
      const body = { name: name.trim() || defaultName, dataset_id: datasetId, nodes, edges, context_markdown: context }
      const config = isNew ? await api.createConfiguration(body) : await api.updateConfiguration(id!, body)
      if (createExperiment) {
        return { config, experiment: await api.createExperiment({ name: experimentName.trim() || defaultExperimentName, configuration_id: config.id }) }
      }
      return { config, experiment: null }
    },
    onSuccess: ({ experiment }) => {
      queryClient.invalidateQueries()
      navigate(experiment ? `/experiments/${experiment.id}` : '/configurations')
    },
  })

  const canNext = step === 0 ? !!datasetId : true

  return (
    <>
      <Topbar title={isNew ? 'New configuration' : `Edit · ${initial.name}`} />
      <div className="stepper">
        {steps.map((s, i) => (
          <button
            key={s}
            className={`step-pill${i === step ? ' active' : ''}${i < step ? ' done' : ''}`}
            onClick={() => (i === 0 ? isNew : datasetId) && setStep(i)}
            disabled={(i > 0 && !datasetId) || (i === 0 && !isNew)}
          >
            <span className="step-index">{i < step ? <Check size={12} /> : i + 1}</span> {s}
          </button>
        ))}
      </div>

      <div className="scroll">
        <div className={`page ${step === 1 ? 'page-full' : 'page-wide'}`}>
          {step === 0 && (
            <>
              <h2 className="h2">Which dataset?</h2>
              <p className="lead">Upload a CSV or pick one you've already added.</p>
              <div className="two-col">
                <div>
                  <UploadZone onUploaded={chooseDataset} />
                  <DatasetList selected={datasetId} onSelect={chooseDataset} />
                </div>
                {datasetId && <section className="panel"><PreviewTable datasetId={datasetId} /></section>}
              </div>
            </>
          )}

          {step === 1 && dataset.data && nodes.length > 0 && (
            <>
              <h2 className="h2">Fields & connections</h2>
              <p className="lead">
                Every column is a node. Describe what fields mean and connect related fields in plain English.
                Only the configured arm sees this. The baseline gets the raw CSV.
              </p>
              <GraphEditor
                key={datasetId}
                columns={dataset.data.columns}
                nodes={nodes}
                edges={edges}
                onChange={(n, e) => {
                  setNodes(n)
                  setEdges(e)
                }}
              />
            </>
          )}

          {step === 2 && (
            <>
              <h2 className="h2">Any more context?</h2>
              <p className="lead">
                Add domain knowledge, business rules or instructions as Markdown, like a Claude skill file. Optional.
              </p>
              <div className="md-toolbar">
                <button className="btn" onClick={() => mdInput.current?.click()}>
                  <FileText size={15} /> Load .md file
                </button>
                <input
                  ref={mdInput}
                  type="file"
                  accept=".md,.markdown,.txt"
                  hidden
                  onChange={async (e) => {
                    const f = e.target.files?.[0]
                    if (f) setContext(await f.text())
                  }}
                />
                <span className="muted small">{context.length.toLocaleString()} characters</span>
              </div>
              <textarea
                className="textarea mono md-editor"
                placeholder={'# Invoice rules\n\n- Amounts are in USD, before tax\n- Invoices over $4,000 require two approvals'}
                value={context}
                onChange={(e) => setContext(e.target.value)}
              />
            </>
          )}

          {step === 3 && (
            <>
              <h2 className="h2">Save configuration</h2>
              <p className="lead">Configurations are reusable. Use this one across as many experiments as you like.</p>
              <section className="panel form-panel">
                <label className="label">Configuration name</label>
                <input className="input-box" placeholder={defaultName} value={name} onChange={(e) => setName(e.target.value)} />

                <dl className="kv" style={{ marginTop: 18 }}>
                  <dt>Dataset</dt><dd>{dataset.data?.filename}</dd>
                  <dt>Fields</dt><dd>{nodes.filter((n) => n.description.trim()).length} of {nodes.length} described</dd>
                  <dt>Connections</dt><dd>{edges.length}</dd>
                  <dt>Context</dt><dd>{context.trim() ? `${context.length.toLocaleString()} characters` : 'None'}</dd>
                </dl>

                <label className="check">
                  <input type="checkbox" checked={createExperiment} onChange={(e) => setCreateExperiment(e.target.checked)} />
                  Create an experiment with this configuration
                </label>
                {createExperiment && (
                  <>
                    <label className="label">Experiment name</label>
                    <input className="input-box" placeholder={defaultExperimentName} value={experimentName} onChange={(e) => setExperimentName(e.target.value)} />
                  </>
                )}
                {save.isError && <div className="notice notice-err">{save.error.message}</div>}
              </section>
            </>
          )}

          <div className="wizard-footer">
            {step > (isNew ? 0 : 1) ? (
              <button className="btn" onClick={() => setStep(step - 1)}><ArrowLeft size={15} /> Back</button>
            ) : <span />}
            {step < 3 ? (
              <button className="btn btn-primary" disabled={!canNext} onClick={() => setStep(step + 1)}>
                {step === 2 && !context.trim() ? 'Skip' : 'Next'} <ArrowRight size={15} />
              </button>
            ) : (
              <button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? 'Saving…' : createExperiment ? 'Save & open arena' : 'Save configuration'}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
