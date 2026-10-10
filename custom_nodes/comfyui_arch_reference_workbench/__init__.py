"""Local reference composition, preparation, review and provenance."""
from .cast import ReferenceCast
from .imaging import ArchReferenceContactSheet, ArchReferencePrepare
from .review import ArchResultReview, ArchRunRecord
from .routes import register_routes

NODE_CLASS_MAPPINGS = {
    "ArchReferenceCast": ReferenceCast,
    "ArchReferenceContactSheet": ArchReferenceContactSheet,
    "ArchReferencePrepare": ArchReferencePrepare,
    "ArchResultReview": ArchResultReview,
    "ArchRunRecord": ArchRunRecord,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ArchReferenceCast": "arch-Reference Cast",
    "ArchReferenceContactSheet": "arch-Reference Contact Sheet",
    "ArchReferencePrepare": "arch-Reference Prepare",
    "ArchResultReview": "arch-Result Review",
    "ArchRunRecord": "arch-Run Record",
}
WEB_DIRECTORY = "./web"
register_routes()
