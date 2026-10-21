import { useEffect, useId, useRef, useState } from 'react'
import type { ScreenshotImage } from '../lib/data'
import { t } from '../lib/i18n'
import { useOverlay } from '../lib/overlay'
import { Icon } from './ui'

/** A real screenshot in a lesson: shown at the column's width with its space reserved (nothing jumps while it loads),
 * what it is and where it was captured, and an enlarged view at full size for reading small text. The enlarged view
 * is a native modal dialog (focus stays in it, Escape closes it); while it is open the page behind does not scroll,
 * and closing gives the focus back to the button that opened it without moving the page. Its image is only created
 * the first time it is opened, so a lesson does not download every screenshot twice. An image that cannot be shown
 * (missing or unreadable) says so, with its description, instead of a broken picture. */
export function Screenshot({ img, caption }: { img: ScreenshotImage; caption: string }) {
  const dlg = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLButtonElement>(null)
  const [opened, setOpened] = useState(false) // the full-size image exists once the dialog was opened
  const [failed, setFailed] = useState(!img.width || !img.height) // the server found no usable file
  const name = caption || img.alt
  const [shown, setShown] = useState(false)
  // the phone's Back closes the enlarged view (and one overlay at a time): lib/overlay.ts
  useOverlay(shown, () => dlg.current?.close(), { id: `shot${useId()}`, root: dlg, opener, modal: true, outside: false, closeOnPick: false, focusTrap: true }) // Tab stays in it (Chrome lets it leave a modal dialog)
  const open = () => {
    setOpened(true)
    setShown(true)
    document.documentElement.classList.add('shot-open') // the page behind keeps its place (CSS: overflow hidden)
    dlg.current?.showModal()
  }
  const close = () => dlg.current?.close()
  useEffect(() => () => document.documentElement.classList.remove('shot-open'), []) // leaving the page unlocks it
  return (
    <figure className="demo shot" data-testid="screenshot">
      {failed ? (
        <p className="shot-missing" role="img" aria-label={img.alt} data-testid="screenshot-missing">
          <Icon name="info" size={16} /> {t('shot.missing')} <span className="muted">{img.alt}</span>
        </p>
      ) : (
        // the image is also clickable; keyboard and screen-reader users have the button below
        <img className="shot-img" src={img.url} alt={img.alt} width={img.width} height={img.height} loading="lazy" decoding="async" onClick={open} onError={() => setFailed(true)} />
      )}
      <figcaption className="demo-meta shot-meta">
        <span className="shot-text">
          {caption && <span className="shot-caption">{caption}</span>}
          <span className="shot-captured" data-testid="screenshot-captured">{img.captured}</span>
        </span>
        {!failed && (
          <button ref={opener} type="button" className="linkish small shot-enlarge" onClick={open} aria-label={t('shot.enlargeNamed', { name })} data-testid="screenshot-enlarge">
            <Icon name="expand" size={14} /> {t('shot.enlarge')}
          </button>
        )}
      </figcaption>
      {!failed && (
        <dialog
          ref={dlg}
          className="shot-dialog"
          aria-label={name}
          onClose={() => {
            setShown(false)
            document.documentElement.classList.remove('shot-open')
            opener.current?.focus({ preventScroll: true })
          }}
          onClick={(e) => e.target === dlg.current && close()} // a click on the backdrop
          data-testid="screenshot-dialog"
        >
          <div className="shot-dialog-bar">
            <span className="shot-dialog-title">{name}</span>
            <button type="button" className="icon-btn" onClick={close} aria-label={t('ui.close')} autoFocus>
              <Icon name="x" size={18} />
            </button>
          </div>
          <div className="shot-dialog-body" tabIndex={0} aria-label={t('shot.fullSize')}>
            {opened && <img src={img.url} alt={img.alt} width={img.width} height={img.height} />}
          </div>
        </dialog>
      )}
    </figure>
  )
}
