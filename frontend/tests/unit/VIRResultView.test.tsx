import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'
import type { VIRResolutionView } from '../../src/api/types'
import { VIRResultView } from '../../src/components/VIRResultView'

function view(overrides: Partial<VIRResolutionView> = {}): VIRResolutionView {
  const confirmable = (field_path: string, extra: Record<string, unknown> = {}) => ({
    field_path, value: null, status: null, status_label: null, proposals: [], confirmation: null,
    choices: null, input_type: 'text', ...extra,
  })
  return {
    case_id: 'case-1',
    vir_execution_id: 'exec-1',
    resolution_status: 'provisionally_resolved',
    confidence: { score: 0.74, level: 'medium' },
    simulated: true,
    registration_country: 'FR',
    exact_factory_configuration_known: false,
    exact_factory_configuration_reasons: ['missing:version'],
    fields: [
      { field_path: 'manufacturer', value: 'MARQUE-FICTIVE', status: 'provider_not_established',
        status_label: 'fourni par une source, non établi', consulted_without_value: [], divergent: [],
        sources: [{ source_id: 'provider-vincario-vin', method: 'provider', role: 'concordant', reliability: 'medium', simulated: true, partial: false, user_declared: false }] },
      { field_path: 'model_year', value: 2019, status: 'provider_not_established', status_label: 'fourni par une source, non établi',
        consulted_without_value: [], divergent: [{ source_id: 'driver_confirmation', value: 2020, method: 'user_confirmation' }],
        sources: [{ source_id: 'provider-vincario-vin', method: 'provider', role: 'concordant', reliability: 'medium', simulated: true, partial: false, user_declared: false }] },
    ],
    unknown_fields: ['generation', 'engine.engine_code'],
    user_declared_fields: [],
    user_confirmed_fields: [],
    contradictions: [{ field_path: 'model_year', severity: 'high', values: [{ source_id: 'driver_confirmation', value: 2020 }, { source_id: 'provider-vincario-vin', value: 2019 }] }],
    alternative_candidates: [],
    excluded_candidates: [{ field_path: 'engine.power_kw', reason: 'declared_value_mismatch', reason_label: 'Puissance différente',
      declared_value: 81, candidate_value: 66, source_ids: ['provider-vincario-vin'], declaration_verified: false }],
    descriptive_info: [{ source_id: 'provider-fr-regcheck', provider_field: 'libVersion', label: 'Description de version fournie', value: 'VERSION-FICTIVE', unit: null, simulated: true }],
    limitations: ['Résultat fictif.'],
    clarification_questions: [],
    confirmations: [
      confirmable('fuel.primary_type', { choices: ['petrol', 'diesel'] }),
      confirmable('transmission.type'), confirmable('generation'), confirmable('engine.engine_code'),
      confirmable('transmission.gears', { input_type: 'number' }),
      confirmable('drivetrain', { choices: ['front_wheel_drive', 'rear_wheel_drive'] }),
      confirmable('model_year', { value: 2019, status: 'provider_not_established', status_label: 'fourni par une source, non établi',
        proposals: [{ value: 2019, sources: ['provider-vincario-vin'] }], confirmation: { value: 2020, applied: false }, input_type: 'number' }),
    ],
    confirmations_locked: false,
    ...overrides,
  }
}

describe('VIRResultView', () => {
  beforeEach(() => {
    vi.spyOn(apiClient, 'getCaseVIR').mockResolvedValue(view())
    vi.spyOn(apiClient, 'confirmVIRField').mockResolvedValue({ outcome: 'SUCCESS' })
    vi.spyOn(apiClient, 'correctVIRField').mockResolvedValue({ outcome: 'SUCCESS' })
    vi.spyOn(apiClient, 'withdrawVIRField').mockResolvedValue({ outcome: 'SUCCESS' })
  })
  afterEach(() => vi.restoreAllMocks())

  it('shows provenance, unknowns, contradictions, divergent values and set-aside candidates', async () => {
    render(<VIRResultView caseId="case-1" />)
    const fields = await screen.findByRole('table', { name: 'Identified characteristics' })
    const row = within(fields).getByRole('row', { name: /manufacturer/i })
    expect(row).toHaveTextContent('MARQUE-FICTIVE')
    expect(row).toHaveTextContent('fourni par une source, non établi')
    expect(row).toHaveTextContent('provider-vincario-vin')
    expect(within(fields).getByRole('row', { name: /model year/i })).toHaveTextContent('Other value: 2020 (driver_confirmation')
    expect(screen.getByRole('region', { name: 'Unknown' })).toHaveTextContent('Generation')
    expect(screen.getByRole('region', { name: 'Contradictions' })).toHaveTextContent('2020')
    expect(screen.getByRole('region', { name: 'Candidates set aside' })).toHaveTextContent('Puissance différente')
    expect(screen.getByText(/simulated or test data/i)).toBeInTheDocument()
  })

  it('keeps the providers’ descriptive information apart from the identity', async () => {
    render(<VIRResultView caseId="case-1" />)
    const descriptive = await screen.findByRole('region', { name: 'Information supplied by the providers' })
    expect(descriptive).toHaveTextContent('Description de version fournie: VERSION-FICTIVE')
    expect(within(screen.getByRole('table', { name: 'Identified characteristics' })).queryByText('VERSION-FICTIVE')).toBeNull()
  })

  it('refreshes by reading the stored result again, never by a new lookup', async () => {
    render(<VIRResultView caseId="case-1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(apiClient.getCaseVIR).toHaveBeenCalledTimes(2))
    expect(apiClient.confirmVIRField).not.toHaveBeenCalled()
  })

  it('offers the seven fields, nothing preselected, and confirms an explicit value', async () => {
    render(<VIRResultView caseId="case-1" />)
    const panel = await screen.findByRole('region', { name: 'Confirm what you know' })
    expect(within(panel).getAllByRole('group')).toHaveLength(7)
    const drivetrain = within(panel).getByRole('group', { name: 'Driven wheels' })
    const select = within(drivetrain).getByLabelText('Your value for Driven wheels') as HTMLSelectElement
    expect(select.value).toBe('')
    fireEvent.change(select, { target: { value: 'front_wheel_drive' } })
    fireEvent.click(within(drivetrain).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(apiClient.confirmVIRField).toHaveBeenCalledWith('case-1', 'drivetrain', 'front_wheel_drive'))
    await waitFor(() => expect(apiClient.getCaseVIR).toHaveBeenCalledTimes(2))
  })

  it('corrects or withdraws an existing confirmation and says when it was not applied', async () => {
    render(<VIRResultView caseId="case-1" />)
    const modelYear = await screen.findByRole('group', { name: 'Model year' })
    expect(modelYear).toHaveTextContent('Your confirmation: 2020 (kept apart, not applied')
    fireEvent.change(within(modelYear).getByLabelText('Your value for Model year'), { target: { value: '2019' } })
    fireEvent.click(within(modelYear).getByRole('button', { name: 'Correct' }))
    await waitFor(() => expect(apiClient.correctVIRField).toHaveBeenCalledWith('case-1', 'model_year', 2019))
    fireEvent.click(within(await screen.findByRole('group', { name: 'Model year' })).getByRole('button', { name: 'Withdraw' }))
    await waitFor(() => expect(apiClient.withdrawVIRField).toHaveBeenCalledWith('case-1', 'model_year'))
  })

  it('shows a refused value and offers no change once a diagnostic has started', async () => {
    vi.mocked(apiClient.confirmVIRField).mockRejectedValueOnce(new ApiError('VIR_INPUT_REFUSED', 'VIR did not accept this value', 422))
    render(<VIRResultView caseId="case-1" />)
    const gears = await screen.findByRole('group', { name: 'Number of gears' })
    fireEvent.change(within(gears).getByLabelText('Your value for Number of gears'), { target: { value: '40' } })
    fireEvent.click(within(gears).getByRole('button', { name: 'Confirm' }))
    expect(await within(gears).findByRole('alert')).toHaveTextContent(/not accepted/i)

    vi.mocked(apiClient.getCaseVIR).mockResolvedValue(view({ confirmations_locked: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(screen.queryAllByRole('button', { name: 'Confirm' })).toHaveLength(0))
    expect(screen.getByText(/diagnostic has started/i)).toBeInTheDocument()
  })
})
