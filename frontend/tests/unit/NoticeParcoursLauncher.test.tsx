import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../src/api/client'
import { ApiError } from '../../src/api/errors'
import { NoticeParcoursLauncher } from '../../src/components/NoticeParcoursLauncher'

afterEach(() => vi.restoreAllMocks())

describe('NoticeParcoursLauncher', () => {
  it('goes to the PGDR page served under the API when the parcours is opened', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({ status: 'opened', page: '/v1?p=V1-abc' })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    await waitFor(() => expect(go).toHaveBeenCalledWith('/api/v1?p=V1-abc'))
    expect(apiClient.openNoticeParcours).toHaveBeenCalledWith('case-1')
  })

  it("shows PGDR's own refusal and goes nowhere", async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({
      status: 'vehicle_identity_insufficient', page: null, message: "L'identité du véhicule n'est pas établie par VIR.",
    })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    expect(await screen.findByTestId('notice-refusal')).toHaveTextContent("L'identité du véhicule n'est pas établie par VIR.")
    expect(go).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Open the manufacturer notice' })).toBeEnabled()
  })

  it('shows the reasons, the provenance of each key, what remains to check and the next action', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({
      status: 'applicability_not_confirmed', page: null,
      message: "L'applicabilité de la notice à ce véhicule n'est pas confirmée.",
      reasons: ['La génération (« X1 ») repose sur la seule confirmation du conducteur : cela ne suffit pas à rendre la notice applicable.'],
      to_verify: ['Comparer la marque, le modèle et la génération du véhicule avec le texte imprimé de la notice.'],
      next_action: "Le propriétaire de la notice enregistre une attestation d'applicabilité. Les contenus déjà validés de la notice n'ont pas à être refaits.",
      identity: [
        { key: 'model', label: 'Le modèle', value: 'Testmobile', provenance: 'provider_not_established',
          provenance_label: 'fourni par une source, non établi' },
        { key: 'generation', label: 'La génération', value: 'X1', provenance: 'user_confirmed',
          provenance_label: 'confirmé par le conducteur, sans vérification indépendante' },
      ],
    })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    const refusal = await screen.findByTestId('notice-refusal')
    expect(refusal).toHaveTextContent("L'applicabilité de la notice à ce véhicule n'est pas confirmée.")
    expect(screen.getByTestId('notice-refusal-identity')).toHaveTextContent(
      'La génération : X1 (confirmé par le conducteur, sans vérification indépendante)')
    expect(screen.getByTestId('notice-refusal-identity')).not.toHaveTextContent('établi (décodage')
    expect(screen.getByTestId('notice-refusal-reasons')).toHaveTextContent('seule confirmation du conducteur')
    expect(screen.getByTestId('notice-refusal-to-verify')).toHaveTextContent('texte imprimé de la notice')
    expect(screen.getByTestId('notice-refusal-next')).toHaveTextContent("déjà validés de la notice n'ont pas à être refaits")
    expect(go).not.toHaveBeenCalled()
  })

  it('offers the safety instructions of PGDR\'s parcours without notice beside its refusal (never a dead end)', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockResolvedValue({
      status: 'notice_unavailable', page: null, safety_page: '/v1?p=V1-safe',
      message: 'Aucune notice constructeur n\'est disponible.',
    })
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    await screen.findByTestId('notice-refusal')
    expect(go).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Voir les consignes de sécurité' }))
    expect(go).toHaveBeenCalledWith('/api/v1?p=V1-safe')
  })

  it('shows a technical failure without any detail', async () => {
    vi.spyOn(apiClient, 'openNoticeParcours').mockRejectedValue(
      new ApiError('PGDR_TECHNICAL_FAILURE', 'PGDR notice service unavailable', 502),
    )
    const go = vi.fn()
    render(<NoticeParcoursLauncher caseId="case-1" go={go} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open the manufacturer notice' }))
    expect(await screen.findByText('The diagnostic service is temporarily unavailable. Please try again.')).toBeVisible()
    expect(go).not.toHaveBeenCalled()
  })
})

describe('NoticeParcoursLauncher — recorded results (bloc 3A)', () => {
  const record = {
    record_id: 'rec-1',
    recorded_at: '2026-10-19T10:00:01+00:00',
    case_id: 'case-1',
    owner_contact_id: 'contact-1',
    vir: { execution_id: 'e', artifact_id: 'a', resolution_id: 'r' },
    notice: { document_id: 'DOC-1', title: 'FICTIVE OWNER HANDBOOK', edition: 'Fictive edition 1', language: 'en',
      content_sha256: 'abcdef0123456789abcdef' },
    selection: { entry_ids: ['fn_green_lamps'], by: 'driver' },
    confirmation: { explicit: true, confirmed_at: '2026-10-19T10:00:00+00:00' },
    sections: [{ entry_id: 'fn_green_lamps', designation: 'FICTIVE LAMPS ON', page_reference: 'F-2',
      meaning: [{ text: 'The fictive green light ' }, { pictogram: 'x' }, { text: 'shows the lamps.' }],
      instruction: null }],
    premier_constat: { presentation: { stops_confirmed: [], sources: ['Source : FICTIVE OWNER HANDBOOK'], end: 'Fin.' } },
    provenance: { selection_origin: 'driver' },
    limits: ["Sélection faite par le conducteur dans les images de la notice : ce n'est pas une reconnaissance du voyant."],
  }

  it('shows each kept result as it was confirmed, read from the case only', async () => {
    vi.spyOn(apiClient, 'getNoticeResults').mockResolvedValue({ case_id: 'case-1', results: [record] })
    vi.spyOn(apiClient, 'openNoticeParcours')
    render(<NoticeParcoursLauncher caseId="case-1" go={vi.fn()} />)
    const kept = await screen.findByTestId('notice-result-rec-1')
    expect(kept).toHaveTextContent('FICTIVE OWNER HANDBOOK — Fictive edition 1')
    expect(kept).toHaveTextContent('Your selection, not a recognition: FICTIVE LAMPS ON')
    expect(kept).toHaveTextContent('The fictive green light shows the lamps.')
    expect(kept).toHaveTextContent("ce n'est pas une reconnaissance du voyant")
    expect(apiClient.getNoticeResults).toHaveBeenCalledWith('case-1')
    expect(apiClient.openNoticeParcours).not.toHaveBeenCalled()
  })

  it('says that opening the notice starts a new parcours, never a resumed one', async () => {
    vi.spyOn(apiClient, 'getNoticeResults').mockResolvedValue({ case_id: 'case-1', results: [] })
    render(<NoticeParcoursLauncher caseId="case-1" go={vi.fn()} />)
    expect(await screen.findByText(/starts a new parcours/)).toBeVisible()
    expect(screen.queryByText(/resum/i)).toBeNull()
  })
})
