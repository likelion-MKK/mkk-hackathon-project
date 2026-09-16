"""Read positioning from EyeTrax 0.4.0's existing detector, once per frame.

The adapter is intentionally pinned to EyeTrax's _face_landmarker seam. The
observer is enabled only for positioning; no image or landmark is retained.
"""

from eyetrax import GazeEstimator

from .face_positioning import placement_from_landmarks


class _PositioningLandmarker:
    def __init__(self, detector):
        self.detector = detector
        self.image_size = None
        self.placement = None

    def detect_for_video(self, image, timestamp):
        self.placement = None
        result = self.detector.detect_for_video(image, timestamp)
        if self.image_size is not None and result.face_landmarks:
            self.placement = placement_from_landmarks(result.face_landmarks[0], *self.image_size)
        return result

    def close(self):
        self.placement = self.image_size = None
        self.detector.close()


class GuidedGazeEstimator(GazeEstimator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._face_landmarker = _PositioningLandmarker(self._face_landmarker)

    def extract_positioning(self, image):
        observer = self._face_landmarker
        observer.image_size = (image.shape[1], image.shape[0])
        try:
            features, blink = self.extract_features(image)
            return features, blink, observer.placement
        finally:
            observer.placement = observer.image_size = None
