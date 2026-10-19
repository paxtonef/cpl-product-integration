// No photo can be analysed in this installation (block 5: no qualified,
// authorised vision provider), so no media-analysis consent is asked;
// mediaAnalysisAllowed stays false.
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
