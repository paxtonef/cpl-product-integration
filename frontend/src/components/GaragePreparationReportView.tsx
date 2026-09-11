import type { GaragePreparationReport } from '../api/types'

export function GaragePreparationReportView({ report }: { report: GaragePreparationReport }) {
  const hasSafetyContent =
    Object.keys(report.safety_information ?? {}).length > 0 || (report.warning_indicators ?? []).length > 0

  return (
    <article aria-label="Diagnostic result">
      <h1>Diagnostic result</h1>
      {hasSafetyContent && (
        <div role="alert" className="safety-banner" data-testid="safety-banner">
          <strong>Safety notice</strong>
          <p>This diagnostic identified information that may affect vehicle safety. Please review carefully.</p>
        </div>
      )}
      <p>Report ID: {report.report_id}</p>
      <section>
        <h2>Reported problem</h2>
        <p>{report.customer_reported_problem}</p>
      </section>
      {report.systems_to_examine.length > 0 && (
        <section>
          <h2>Systems to examine</h2>
          <ul>
            {report.systems_to_examine.map((system, index) => (
              <li key={index}>{JSON.stringify(system)}</li>
            ))}
          </ul>
        </section>
      )}
      {report.suggested_professional_checks.length > 0 && (
        <section>
          <h2>Suggested professional checks</h2>
          <ul>
            {report.suggested_professional_checks.map((check, index) => (
              <li key={index}>{check}</li>
            ))}
          </ul>
        </section>
      )}
      {report.limitations.length > 0 && (
        <section>
          <h2>Limitations</h2>
          <ul>
            {report.limitations.map((limitation, index) => (
              <li key={index}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}
      <p>Generated at: {report.generated_at}</p>
    </article>
  )
}
