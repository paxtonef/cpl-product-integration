// The legacy PGDR dialogue (complaint text, diagnostic questions, garage preparation report) is unplugged from the
// product since the PGDR V1 closure: no link and no route to it, unless a test or trial build asks for it
// (VITE_PI_DIALOGUE_HISTORIQUE=1, with the API's PI_DIALOGUE_HISTORIQUE=1). A production build never sets it, and
// the production API never serves those routes. The code is kept, not deleted.
export const LEGACY_DIALOGUE = import.meta.env.VITE_PI_DIALOGUE_HISTORIQUE === '1'
