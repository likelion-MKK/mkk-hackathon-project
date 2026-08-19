"""Language-level interface matching the repository Face Adapter contract."""

from typing import Generic, Protocol, TypeVar, runtime_checkable

from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext


FrameT = TypeVar("FrameT")


@runtime_checkable
class FaceAdapter(Protocol, Generic[FrameT]):
    """Replaceable boundary for fake, replay, and selected Face adapters."""

    def metadata(self) -> AdapterMetadata:
        """Return pinned identity and taxonomy information for this adapter."""

    def initialize(self) -> None:
        """Prepare deterministic runtime resources."""

    def warmup(self) -> None:
        """Run startup work before the first inference."""

    def infer(self, frame: FrameT, context: FaceFrameContext) -> ExpressionSample:
        """Produce one derived sample without retaining or serializing the frame."""

    def dispose(self) -> None:
        """Release resources owned by the adapter."""
