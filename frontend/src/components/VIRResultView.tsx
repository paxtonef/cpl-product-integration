import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { VIRConfirmable, VIRResolutionView } from '../api/types'
import { ErrorBanner } from './ErrorBanner'

// The case's VIR result as PI-05 serves it (GET /cases/{id}/vir): VIR's own
// statuses, sources and values, shown as given. Nothing is computed here:
// no status, no confidence, no value. The providers' descriptive
// information stays apart from the identity. Refreshing reads the stored
// result again; it never starts a new lookup.

const FIELD_LABELS: Record<string, string> = {
  manufacturer: 'Manufacturer',
  brand: 'Brand',
  model: 'Model',
  generation: 'Generation',
  version: 'Version',
  variant: 'Variant',
  trim: 'Trim',
  model_year: 'Model year',
  first_registration_date: 'First registration date',
  cluster_type: 'Instrument cluster',
  drivetrain: 'Driven wheels',
  'production.year': 'Production year',
  'body.type': 'Body',
  'fuel.primary_type': 'Fuel',
  'engine.engine_code': 'Engine code',
  'engine.power_kw': 'Power (kW)',
  'engine.displacement_cc': 'Displacement (cc)',
  'engine.cylinders': 'Cylinders',
  'transmission.type': 'Gearbox type',
  'transmission.gears': 'Number of gears',
}

const VALUE_LABELS: Record<string, string> = {
  petrol: 'petrol', diesel: 'diesel', electric: 'electric', hybrid: 'hybrid', plug_in_hybrid: 'plug-in hybrid',
  lpg: 'LPG', cng: 'CNG', hydrogen: 'hydrogen', other: 'other', manual: 'manual', automatic: 'automatic',
  automated_manual: 'automated manual', cvt: 'continuously variable (CVT)', direct_drive: 'direct drive',
  front_wheel_drive: 'front-wheel drive', rear_wheel_drive: 'rear-wheel drive',
  all_wheel_drive: 'all-wheel drive (AWD)', four_wheel_drive: 'four-wheel drive (4WD)',
}

function fieldLabel(path: string): string {
  return FIELD_LABELS[path] ?? path
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return VALUE_LABELS[value] ?? value
  return String(value)
}

function ConfirmationField({
  caseId,
  entry,
  locked,
  onChanged,
}: {
  caseId: string
  entry: VIRConfirmable
  locked: boolean
  onChanged: () => void
}) {
  const [value, setValue] = useState('')
  const [status, setStatus] = useState<'ready' | 'submitting'>('ready')
  const [error, setError] = useState<ApiError | null>(null)
  const label = fieldLabel(entry.field_path)
  const inputId = `confirm-${entry.field_path.replace(/\W/g, '-')}`

  function typed(): unknown {
    return entry.input_type === 'number' ? Number(value) : value
  }

  async function run(action: () => Promise<unknown>) {
    setError(null)
    setStatus('submitting')
    try {
      await action()
      setValue('')
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
    } finally {
      setStatus('ready')
    }
  }

  const submitting = status === 'submitting'
  return (
    <fieldset>
      <legend>{label}</legend>
      {error && <ErrorBanner error={error} />}
      <p>
        Retained value: {show(entry.value)}
        {entry.status_label ? ` — ${entry.status_label}` : ''}
      </p>
      {entry.proposals.length > 0 && (
        <p>
          Proposed by the sources:{' '}
          {entry.proposals.map((p) => `${show(p.value)} (${p.sources.join(', ')})`).join('; ')}
        </p>
      )}
      {entry.confirmation && (
        <p>
          Your confirmation: {show(entry.confirmation.value)}{' '}
          {entry.confirmation.applied
            ? '(applied, not independently verified)'
            : '(kept apart, not applied: the sources give another value)'}
        </p>
      )}
      {!locked && (
        <div>
          <label htmlFor={inputId}>Your value for {label}</label>
          {entry.choices ? (
            <select id={inputId} value={value} onChange={(event) => setValue(event.target.value)} disabled={submitting}>
              <option value="" disabled>
                Choose…
              </option>
              {entry.choices.map((choice) => (
                <option key={choice} value={choice}>
                  {show(choice)}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={inputId}
              type={entry.input_type === 'number' ? 'number' : 'text'}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              disabled={submitting}
            />
          )}
          {entry.confirmation ? (
            <>
              <button
                type="button"
                disabled={submitting || !value}
                onClick={() => run(() => apiClient.correctVIRField(caseId, entry.field_path, typed()))}
              >
                Correct
              </button>
              <button
                type="button"
                disabled={submitting}
                onClick={() => run(() => apiClient.withdrawVIRField(caseId, entry.field_path))}
              >
                Withdraw
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={submitting || !value}
              onClick={() => run(() => apiClient.confirmVIRField(caseId, entry.field_path, typed()))}
            >
              Confirm
            </button>
          )}
        </div>
      )}
    </fieldset>
  )
}

export function VIRResultView({ caseId, onChanged }: { caseId: string; onChanged?: () => void }) {
  const [view, setView] = useState<VIRResolutionView | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(() => {
    setError(null)
    apiClient
      .getCaseVIR(caseId)
      .then(setView)
      .catch((err) => setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500)))
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <ErrorBanner error={error} />
  if (!view) {
    return (
      <div role="status" aria-busy="true">
        Loading the vehicle identity…
      </div>
    )
  }

  function changed() {
    load()
    onChanged?.()
  }

  return (
    <section aria-label="Vehicle identity details">
      <h2>Vehicle identity</h2>
      <p>
        Status: <strong>{view.resolution_status}</strong> — confidence {view.confidence.level} ({view.confidence.score})
      </p>
      {view.registration_country && <p>Registration country: {view.registration_country}</p>}
      {view.simulated && (
        <p role="note">These are simulated or test data: they do not come from a confirmed provider lookup.</p>
      )}
      <p>
        Exact factory configuration: {view.exact_factory_configuration_known ? 'established' : 'not established'}
      </p>
      <button type="button" onClick={load}>
        Refresh
      </button>
      <p>Refreshing reads the stored result again; it does not consult any provider.</p>

      <table aria-label="Identified characteristics">
        <thead>
          <tr>
            <th>Characteristic</th>
            <th>Value</th>
            <th>Status</th>
            <th>Sources</th>
          </tr>
        </thead>
        <tbody>
          {view.fields.map((field) => (
            <tr key={field.field_path}>
              <td>{fieldLabel(field.field_path)}</td>
              <td>{show(field.value)}</td>
              <td>{field.status_label ?? '—'}</td>
              <td>
                {field.sources
                  .map((s) => `${s.source_id}${s.method ? ` (${s.method}${s.simulated ? ', simulated' : ''})` : ''}`)
                  .join(', ') || '—'}
                {field.divergent.map((d) => (
                  <span key={`${d.source_id}-${String(d.value)}`}>
                    {' '}
                    Other value: {show(d.value)} ({d.source_id}
                    {d.method ? `, ${d.method}` : ''})
                  </span>
                ))}
                {field.consulted_without_value.length > 0 &&
                  ` Consulted without a value: ${field.consulted_without_value.join(', ')}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <section aria-label="Unknown">
        <h3>Unknown</h3>
        {view.unknown_fields.length === 0 ? (
          <p>None.</p>
        ) : (
          <ul>
            {view.unknown_fields.map((f) => (
              <li key={f}>{fieldLabel(f)}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Contradictions">
        <h3>Contradictions</h3>
        {view.contradictions.length === 0 ? (
          <p>None.</p>
        ) : (
          <ul>
            {view.contradictions.map((c) => (
              <li key={c.field_path}>
                {fieldLabel(c.field_path)} ({c.severity}):{' '}
                {c.values.map((v) => `${show(v.value)} (${v.source_id})`).join(' / ')}
              </li>
            ))}
          </ul>
        )}
      </section>

      {view.alternative_candidates.length > 0 && (
        <section aria-label="Other candidates">
          <h3>Other candidates</h3>
          <ul>
            {view.alternative_candidates.map((c) => (
              <li key={c.candidate_id}>
                {c.source_ids.join(', ')} — differs on: {c.conflicting_fields.map(fieldLabel).join(', ') || '—'}
              </li>
            ))}
          </ul>
        </section>
      )}

      {view.excluded_candidates.length > 0 && (
        <section aria-label="Candidates set aside">
          <h3>Candidates set aside</h3>
          <ul>
            {view.excluded_candidates.map((x, index) => (
              <li key={`${x.field_path}-${index}`}>
                {x.reason_label || x.reason}: {fieldLabel(x.field_path)} — your value {show(x.declared_value)}
                {x.declaration_verified ? '' : ' (not verified)'}, candidate {show(x.candidate_value)} (
                {x.source_ids.join(', ')})
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Information supplied by the providers">
        <h3>Information supplied by the providers (not part of the identity)</h3>
        {view.descriptive_info.length === 0 ? (
          <p>None.</p>
        ) : (
          <ul>
            {view.descriptive_info.map((d) => (
              <li key={`${d.source_id}-${d.provider_field}`}>
                {d.label}: {d.value}
                {d.unit ? ` ${d.unit}` : ''} ({d.source_id}
                {d.simulated ? ', simulated' : ''})
              </li>
            ))}
          </ul>
        )}
      </section>

      {view.limitations.length > 0 && (
        <section aria-label="Limitations">
          <h3>Limitations</h3>
          <ul>
            {view.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Confirm what you know">
        <h3>Confirm what you know</h3>
        {view.confirmations_locked ? (
          <p>A diagnostic has started for this case: the vehicle identity can no longer be changed here.</p>
        ) : (
          <p>
            A value you confirm is recorded as yours, without independent verification. It never replaces a value
            given by a source and never raises the confidence.
          </p>
        )}
        {view.confirmations.map((entry) => (
          <ConfirmationField
            key={entry.field_path}
            caseId={caseId}
            entry={entry}
            locked={view.confirmations_locked}
            onChanged={changed}
          />
        ))}
      </section>
    </section>
  )
}
