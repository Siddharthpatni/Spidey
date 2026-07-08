import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'

// Per-tool visual identity: icon + accent color.
const TOOL_STYLE = {
  task: { icon: '◎', color: '#818cf8', label: 'task' },
  think: { icon: '🧠', color: '#c084fc', label: 'think' },
  answer: { icon: '💬', color: '#60a5fa', label: 'answer' },
  plan: { icon: '📋', color: '#f59e0b', label: 'plan' },
  remember: { icon: '💾', color: '#a78bfa', label: 'remember' },
  read_file: { icon: '📖', color: '#38bdf8', label: 'read_file' },
  write_file: { icon: '✏️', color: '#34d399', label: 'write_file' },
  list_directory: { icon: '📂', color: '#2dd4bf', label: 'list_directory' },
  search_code: { icon: '🔍', color: '#22d3ee', label: 'search_code' },
  run_command: { icon: '💻', color: '#fbbf24', label: 'run_command' },
  finish: { icon: '🏁', color: '#4ade80', label: 'finish' },
  default: { icon: '🔧', color: '#a1a1aa', label: 'tool' },
}

export function styleFor(step) {
  if (step.type === 'task') return TOOL_STYLE.task
  if (step.type === 'think') return TOOL_STYLE.think
  if (step.type === 'answer') return TOOL_STYLE.answer
  if (step.type === 'finish') return TOOL_STYLE.finish
  return TOOL_STYLE[step.tool] || TOOL_STYLE.default
}

function subtitle(step) {
  if (step.type === 'task') return step.text
  if (step.type === 'think') return step.text
  if (step.type === 'answer') return step.text
  if (step.type === 'finish') return step.text
  const a = step.args || {}
  return a.path || a.pattern || a.command || a.steps || a.fact || ''
}

function StepNode({ data }) {
  const { step } = data
  const s = styleFor(step)
  const statusBadge =
    step.status === 'ok' ? <span className="text-emerald-400">✓</span>
    : step.status === 'err' ? <span className="text-rose-400">✗</span>
    : step.status === 'awaiting' ? <span className="text-amber-400">⚠ approval</span>
    : <span className="animate-pulse text-amber-300">⏳</span>

  return (
    <div
      className={`w-64 rounded-xl border bg-zinc-900/95 px-3 py-2 shadow-lg transition-colors ${
        step.status === 'running' || step.status === 'awaiting' ? 'spidey-node-running' : ''
      }`}
      style={{ borderColor: s.color }}
    >
      <Handle type="target" position={Position.Top} className="!bg-zinc-600" />
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">{s.icon}</span>
        <span className="font-mono text-xs font-semibold" style={{ color: s.color }}>
          {step.type === 'tool' ? step.tool : s.label}
        </span>
        <span className="ml-auto text-xs">{statusBadge}</span>
      </div>
      {subtitle(step) && (
        <div className="mt-1 truncate font-mono text-[11px] text-zinc-400">{subtitle(step)}</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-zinc-600" />
    </div>
  )
}

const nodeTypes = { step: StepNode }

function Graph({ steps, onSelect }) {
  const { fitView } = useReactFlow()

  const { nodes, edges } = useMemo(() => {
    const nodes = steps.map((step, i) => ({
      id: step.id,
      type: 'step',
      position: { x: (i % 2) * 40 - 20, y: i * 92 },
      data: { step },
    }))
    const edges = steps.slice(1).map((step, i) => ({
      id: `e-${steps[i].id}-${step.id}`,
      source: steps[i].id,
      target: step.id,
      animated: step.status === 'running' || step.status === 'awaiting',
      style: { stroke: styleFor(step).color, strokeWidth: 1.5 },
    }))
    return { nodes, edges }
  }, [steps])

  useEffect(() => {
    if (steps.length) {
      const t = setTimeout(() => fitView({ duration: 350, padding: 0.15, maxZoom: 1 }), 60)
      return () => clearTimeout(t)
    }
  }, [steps.length, fitView])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.data.step)}
      proOptions={{ hideAttribution: false }}
      nodesDraggable={false}
      nodesConnectable={false}
      minZoom={0.3}
      colorMode="dark"
    >
      <Background gap={24} size={1.2} color="#27272a" />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

export default function AgentGraph({ steps, onSelect }) {
  if (!steps.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        <div className="text-center">
          <div className="mb-2 text-4xl">🕸</div>
          The agent's reasoning appears here, live — node by node.
        </div>
      </div>
    )
  }
  return (
    <ReactFlowProvider>
      <Graph steps={steps} onSelect={onSelect} />
    </ReactFlowProvider>
  )
}
