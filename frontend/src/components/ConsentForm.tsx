export interface ConsentValue {
  mediaAnalysisAllowed: boolean
  reportStorageAllowed: boolean
}

export function ConsentForm({
  value,
  onChange,
  disabled,
}: {
  value: ConsentValue
  onChange: (value: ConsentValue) => void
  disabled?: boolean
}) {
  return (
    <fieldset>
      <legend>Consent</legend>
      <div>
        <input
          id="consentMediaAnalysis"
          type="checkbox"
          checked={value.mediaAnalysisAllowed}
          onChange={(event) => onChange({ ...value, mediaAnalysisAllowed: event.target.checked })}
          disabled={disabled}
        />
        <label htmlFor="consentMediaAnalysis">I consent to media analysis, if provided.</label>
      </div>
      <div>
        <input
          id="consentReportStorage"
          type="checkbox"
          checked={value.reportStorageAllowed}
          onChange={(event) => onChange({ ...value, reportStorageAllowed: event.target.checked })}
          disabled={disabled}
        />
        <label htmlFor="consentReportStorage">I consent to my diagnostic report being stored.</label>
      </div>
    </fieldset>
  )
}
