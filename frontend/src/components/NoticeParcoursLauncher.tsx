import { useEffect, useState } from 'react'
import { apiClient, apiPageUrl } from '../api/client'
import { ApiError } from '../api/errors'
import type { NoticeParcoursResponse, NoticeResult, NoticeTextSegment } from '../api/types'
import { ErrorBanner } from './ErrorBanner'

function plain(segments: NoticeTextSegment[]): string {
  return segments.map((s) => s.text ?? '').join('')
}

// PGDR's refusal as PGDR worded it (French): its reason, the identity keys compared with their provenance
// (« confirmé par le conducteur » is never shown as established), what remains to be checked and the next
// useful action. Nothing is assumed beyond it.
function Refusal({ refusal, go }: { refusal: NoticeParcoursResponse; go: (url: string) => void }) {
  const identity = refusal.identity ?? []
  const reasons = refusal.reasons ?? []
  const toVerify = refusal.to_verify ?? []
  return (
    <div role="status" lang="fr" data-testid="notice-refusal">
      <p>{refusal.message ?? 'No manufacturer notice can be shown for this vehicle.'}</p>
      {identity.length > 0 && (
        <ul aria-label="Identité comparée" data-testid="notice-refusal-identity">
          {identity.map((k) => (
            <li key={k.key}>
              {k.label} : {k.value ?? '—'} ({k.provenance_label})
            </li>
          ))}
        </ul>
      )}
      {reasons.length > 0 && (
        <ul aria-label="Motifs" data-testid="notice-refusal-reasons">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {toVerify.length > 0 && (
        <>
          <p>Reste à vérifier :</p>
          <ul aria-label="Reste à vérifier" data-testid="notice-refusal-to-verify">
            {toVerify.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}
      {refusal.next_action && <p data-testid="notice-refusal-next">Prochaine étape : {refusal.next_action}</p>}
      {refusal.safety_page && (
        // PGDR's parcours without notice: a fixed screen, then the safety instructions by the colour of the light.
        <button type="button" data-testid="notice-refusal-safety" onClick={() => go(apiPageUrl(refusal.safety_page!))}>
          Voir les consignes de sécurité
        </button>
      )}
    </div>
  )
}

// One confirmed result, as kept: the notice edition, the driver's own selection and the exact texts.
function KeptResult({ result }: { result: NoticeResult }) {
  const lang = result.notice.language ?? undefined
  const stops = result.premier_constat.presentation?.stops_confirmed ?? []
  return (
    <article data-testid={`notice-result-${result.record_id}`}>
      <h4>Confirmed on {new Date(result.confirmation.confirmed_at).toLocaleString()}</h4>
      <p>
        Notice: <span lang={lang}>{result.notice.title} — {result.notice.edition}</span> (fingerprint{' '}
        {result.notice.content_sha256.slice(0, 12)})
      </p>
      <p>
        Your selection, not a recognition:{' '}
        <span lang={lang}>{result.sections.map((s) => s.designation).join(', ')}</span>
      </p>
      {stops.map((stop, i) => (
        <blockquote key={i} lang={lang}>
          {stop.citation?.text}
        </blockquote>
      ))}
      {result.sections.map((section) => (
        <section key={section.entry_id} aria-label={section.designation}>
          <h5 lang={lang}>{section.designation}</h5>
          <p lang={lang}>{plain(section.meaning)}</p>
          {section.instruction && <p lang={lang}>{section.instruction}</p>}
          {section.page_reference && <p>Page {section.page_reference}</p>}
        </section>
      ))}
      <ul lang="fr">
        {result.limits.map((limit) => (
          <li key={limit}>{limit}</li>
        ))}
      </ul>
    </article>
  )
}

// Opens PGDR's notice parcours (photo, up to 3 proposed images, the complete
// catalogue, the driver's own selection and confirmation, the notice text and
// the Premier Constat) for this case. The parcours page is PGDR's own, served
// through PI for the case owner only; when PGDR opens no parcours (identity
// not established, no notice, applicability not confirmed), its own reason is
// shown and nothing else is assumed. Confirmed results are kept with the case
// and shown here as they were confirmed (bloc 3A); an unfinished parcours is
// never resumed: opening the notice starts a new one.
export function NoticeParcoursLauncher({
  caseId,
  go = (url: string) => window.location.assign(url),
}: {
  caseId: string
  go?: (url: string) => void
}) {
  const [status, setStatus] = useState<'ready' | 'opening'>('ready')
  const [refusal, setRefusal] = useState<NoticeParcoursResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [kept, setKept] = useState<NoticeResult[] | null>(null)
  const [keptUnavailable, setKeptUnavailable] = useState(false)

  useEffect(() => {
    let live = true
    apiClient
      .getNoticeResults(caseId)
      .then((r) => live && setKept(r.results))
      .catch(() => live && setKeptUnavailable(true))
    return () => {
      live = false
    }
  }, [caseId])

  async function open() {
    setError(null)
    setRefusal(null)
    setStatus('opening')
    try {
      const result = await apiClient.openNoticeParcours(caseId)
      if (result.status === 'opened' && result.page) {
        go(apiPageUrl(result.page))
        return
      }
      setRefusal(result)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('UNEXPECTED', 'Something went wrong.', 500))
    }
    setStatus('ready')
  }

  return (
    <section aria-label="Warning lights">
      <h2>Warning lights</h2>
      <p>
        Compare a warning light with the images of your vehicle's manufacturer notice, then read what the notice
        says. Images proposed from your photo are only an aid: you choose and confirm.
      </p>
      {error && <ErrorBanner error={error} />}
      {refusal && <Refusal refusal={refusal} go={go} />}
      <p>Opening the notice always starts a new parcours from the beginning.</p>
      <button type="button" onClick={open} disabled={status === 'opening'}>
        Open the manufacturer notice
      </button>
      {kept && kept.length > 0 && (
        <section aria-label="Confirmed results">
          <h3>Confirmed results</h3>
          {kept.map((result) => (
            <KeptResult key={result.record_id} result={result} />
          ))}
        </section>
      )}
      {keptUnavailable && <p role="status">Confirmed results cannot be read right now.</p>}
    </section>
  )
}
