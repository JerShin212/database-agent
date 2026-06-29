import { ClipboardList, ArrowRight } from 'lucide-react'
import type { FormSuggestion, ToolCall } from '../../types'

/** Re-derive form suggestions from persisted tool_calls on history reload. */
export function formSuggestionsFromToolCalls(toolCalls?: ToolCall[]): FormSuggestion[] {
  if (!toolCalls) return []
  return toolCalls
    .filter(
      (tc) =>
        tc.tool === 'suggest_form' &&
        typeof tc.result === 'string' &&
        tc.result.startsWith('Form suggestion sent to the user')
    )
    .map((tc) => ({
      form_id: String(tc.args?.form_id || ''),
      // The persisted args lack the catalog-resolved name/url; fall back to the id
      form_name: String(tc.args?.form_id || 'Form'),
      redirect_url: `/forms/${tc.args?.form_id || ''}`,
      prefill: (tc.args?.prefill as Record<string, string>) || {},
    }))
    .filter((s) => s.form_id)
}

export default function FormSuggestionCard({ suggestion }: { suggestion: FormSuggestion }) {
  const params = new URLSearchParams(
    Object.entries(suggestion.prefill).map(([k, v]) => [k, String(v)])
  )
  const href = params.size
    ? `${suggestion.redirect_url}?${params.toString()}`
    : suggestion.redirect_url

  return (
    <a
      href={href}
      className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 hover:bg-blue-100 transition-colors group"
    >
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center">
          <ClipboardList size={18} className="text-blue-600" />
        </div>
        <div>
          <div className="text-sm font-medium text-blue-800">{suggestion.form_name}</div>
          {Object.keys(suggestion.prefill).length > 0 && (
            <div className="text-xs text-blue-600">
              {Object.keys(suggestion.prefill).length} field(s) prefilled for you
            </div>
          )}
        </div>
      </div>
      <ArrowRight size={16} className="text-blue-500 group-hover:translate-x-0.5 transition-transform" />
    </a>
  )
}
