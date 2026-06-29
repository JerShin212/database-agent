import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar, Line, Pie, Scatter } from 'react-chartjs-2'
import type { ChartSpec, ToolCall } from '../../types'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
)

const PALETTE = [
  'rgba(59, 130, 246, 0.7)', // blue-500
  'rgba(16, 185, 129, 0.7)', // emerald-500
  'rgba(245, 158, 11, 0.7)', // amber-500
  'rgba(239, 68, 68, 0.7)', // red-500
]

/** Re-derive chart specs from persisted tool_calls when reloading history. */
export function chartsFromToolCalls(toolCalls?: ToolCall[]): ChartSpec[] {
  if (!toolCalls) return []
  return toolCalls
    .filter(
      (tc) =>
        tc.tool === 'create_chart' &&
        typeof tc.result === 'string' &&
        tc.result.startsWith('Chart rendered for the user')
    )
    .map((tc) => tc.args as unknown as ChartSpec)
    .filter((spec) => spec && spec.chart_type && Array.isArray(spec.datasets))
}

export default function ChartBlock({ spec }: { spec: ChartSpec }) {
  const isPie = spec.chart_type === 'pie'
  const data = {
    labels: spec.labels || [],
    datasets: spec.datasets.map((ds, i) => ({
      label: ds.label,
      data: ds.data,
      backgroundColor: isPie
        ? (spec.labels || []).map((_, j) => PALETTE[j % PALETTE.length])
        : PALETTE[i % PALETTE.length],
      borderColor: isPie
        ? undefined
        : PALETTE[i % PALETTE.length].replace('0.7', '1'),
      borderWidth: 1,
    })),
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom' as const },
      title: { display: true, text: spec.title },
    },
  }

  return (
    <div className="my-3 bg-white rounded-lg border p-4" style={{ height: 320 }}>
      {spec.chart_type === 'bar' && <Bar data={data} options={options} />}
      {spec.chart_type === 'line' && <Line data={data} options={options} />}
      {spec.chart_type === 'pie' && <Pie data={data} options={options} />}
      {spec.chart_type === 'scatter' && <Scatter data={data} options={options} />}
    </div>
  )
}
