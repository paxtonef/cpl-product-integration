"""Block B1.5 — concrete MediaResolverPort implementation, owned by PI
(the layer with the actual storage), implementing PGDR's own port
contract (pgdr.ports.media_resolver.MediaResolverPort). PGDR domain code
never imports this module -- only the abstract Port from PGDR's own
package.
"""
from __future__ import annotations

from pgdr.domain.media import MediaType
from pgdr.ports.media_resolver import MediaResolutionError, ResolvedMedia

from product_integration.media.storage import LocalMediaStorage, MediaNotFoundError

_CONTENT_TYPE_TO_MEDIA_TYPE = {
    "image/jpeg": MediaType.IMAGE,
    "image/png": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "image/heic": MediaType.IMAGE,
}


class LocalMediaResolverAdapter:
    """Implements pgdr.ports.media_resolver.MediaResolverPort (structurally,
    via typing.Protocol -- no inheritance required, confirmed by the PGDR-
    side test suite's own isinstance() check against the Port)."""

    def __init__(self, storage: LocalMediaStorage):
        self._storage = storage

    def resolve(self, reference: str) -> ResolvedMedia:
        try:
            content, content_type = self._storage.read(reference)
        except MediaNotFoundError as exc:
            raise MediaResolutionError(str(exc)) from exc
        media_type = _CONTENT_TYPE_TO_MEDIA_TYPE.get(content_type, MediaType.IMAGE)
        return ResolvedMedia(content=content, media_type=media_type, reference=reference)
