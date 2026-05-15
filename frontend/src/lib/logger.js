/**
 * Client-side logger.
 * - In dev: prints to console with level + source tag
 * - In prod: only warnings/errors are logged
 * - Optionally posts errors to /api/client-log (not implemented server-side yet)
 */
const isDev = import.meta.env.DEV
const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 }
const MIN_LEVEL = isDev ? LEVELS.debug : LEVELS.warn

function _log(level, source, msg, ...extra) {
  if (LEVELS[level] < MIN_LEVEL) return
  const prefix = `[${source}]`
  const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log
  fn(prefix, msg, ...extra)
}

export function createLogger(source) {
  return {
    debug: (msg, ...x) => _log('debug', source, msg, ...x),
    info: (msg, ...x) => _log('info', source, msg, ...x),
    warn: (msg, ...x) => _log('warn', source, msg, ...x),
    error: (msg, ...x) => _log('error', source, msg, ...x),
    // Use for caught exceptions — logs the error and returns undefined so it
    // can be used as a single-line replacement for `catch {}`:
    //   .catch(log.ignore)
    ignore: (e) => _log('debug', source, 'ignored', e?.message || e),
  }
}

export const logger = createLogger('app')
