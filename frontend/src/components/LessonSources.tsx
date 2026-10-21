import { t } from '../lib/i18n'
import { CodeBlock } from './Code'

/** Recording inputs belong before the experiment, including flows with no separate practice activity. */
export function LessonSources({ files }: { files: Record<string, string> }) {
  const entries = Object.entries(files)
  if (!entries.length) return null
  return (
    <details className="more" data-testid="lesson-sources">
      <summary>{t('lesson.sourceFiles', { n: entries.length })}</summary>
      <p>{t('lesson.sourceFilesHelp')}</p>
      {entries.map(([name, body]) => (
        <details className="more" key={name} data-testid="lesson-source-file">
          <summary className="mono">{name}</summary>
          <CodeBlock code={body} caption={name} label={t('lesson.copySource', { name })} />
        </details>
      ))}
    </details>
  )
}
