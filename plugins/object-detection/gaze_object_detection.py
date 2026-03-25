import logging
import os

import cv2
import numpy as np
from pyglui import ui
from pyglui.pyfontstash import fontstash
import OpenGL.GL as gl
from ultralytics import YOLO
from plugin import Plugin
from pyglui.cygl.utils import draw_polyline_norm, RGBA, draw_rounded_rect
from PIL import Image


class GazeObjectDetector(Plugin):
    CUSTOM_TOPIC = "objects"
    TRIGGER_TOPIC = "fixations"
    LEGEND_TEXT = "Object Detection"

    FRAME_TOPIC = "frame.world"

    icon_chr = chr(0xEC07)
    icon_font = "pupil_icons"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # Parameters with default values
        self.max_duration = 0.3      # Maximum fixation duration
        self.min_prob = 0.2          # Minimum confidence for object detection
        self.vis_object_bbox = True

        self.model_path = "yolo11s.pt"
        if os.path.exists("/home/tobias/Desktop/Uni/IMP/Pupil-Capture-Plugins/.local/models/yolov11s_IoT.pt"):
            self.model_path = "/home/tobias/Desktop/Uni/IMP/Pupil-Capture-Plugins/.local/models/yolov11s_IoT.pt"


        # Initialize YOLO model
        self.model = YOLO(self.model_path)

        # Visualization variables
        self.glfont = None
        self.bbox_color = RGBA(1.0, 0.8, 0.8, 1.0)
        self.bbox_text_color = (1.0, 0.8, 0.8, 1.0)
        self.info_text_color = (0.0, 0.0, 0.0, 1.0)
        self.info_text_bg = RGBA(1.0, 0.8, 0.8, 1.0)

        # State variables
        self.current_fixation = None
        self.current_fixation_id = None
        self.fixation_buffer = []
        self.mean_fixation = None
        self.current_object = None
        self.current_bbox = None
        self.current_conf = None

        self.logger.info("GazeObjectDetector initialized.")

    @classmethod
    def parse_pretty_class_name(cls) -> str:
        return "Gaze Object Detector"

    def reinit_model(self):
        """Reinitialize the YOLO model with the specified model path."""
        if os.path.exists(self.model_path):
            self.model = YOLO(self.model_path)
            self.logger.info(f"Model reinitialized with path: {self.model_path}")
        else:
            self.logger.error(f"Model path {self.model_path} does not exist.")
            self.model_path = "yolo11s.pt"

    def init_ui(self):
        self.add_menu()
        self.menu.label = "Gaze Object Detection Parameters"
        self.menu.append(
            ui.Info_Text("This plugin detects objects at the user's fixation point.")
        )
        self.menu.append(
            ui.Switch("vis_object_bbox", self, label="Visualize Bounding Box on Gaze")
        )
        self.menu.append(
            ui.Text_Input("model_path", self, label="Model Path")
        )
        self.menu.append(
            ui.Button("Reinitialize YOLO Model", self.reinit_model)
        )
        self.menu.append(
            ui.Slider("min_prob", self, min=0.0, step=0.05, max=1.0, label="Min Confidence")
        )
        self.menu.append(
            ui.Slider("max_duration", self, min=0.01, step=0.01, max=2.0, label="Max Fixation Duration")
        )
        # Initialize font context for text rendering
        self.glfont = fontstash.Context()
        self.glfont.add_font("opensans", ui.get_opensans_font_path())
        self.glfont.set_size(20)
        self.glfont.set_color_float((0.0, 0.0, 0.0, 1.0))  # Black text

    def gl_display(self):
        """Display the detected object and bounding box if enabled."""
        # Position where the text will be drawn
        x_legend, y_legend = 20, 610

        # Draw the rounded rectangle
        draw_rounded_rect(
            (x_legend - 10, y_legend - 17),
            (x_legend + (8 * len(self.LEGEND_TEXT)), 23),
            corner_radius=5.0,
            color=self.info_text_bg
        )
        self.glfont.set_color_float((0.0, 0.0, 0.0, 1.0))
        self.glfont.draw_text(x_legend, y_legend, self.LEGEND_TEXT)

        if self.current_object and self.current_fixation:
            text = f"{self.current_fixation['id']} - {self.current_object.upper()}"

            # Position where the text will be drawn
            x, y = 20, 80

            # Draw the rounded rectangle
            draw_rounded_rect(
                (x - 10, y - 17),
                (x + (8 * len(text)), 23),
                corner_radius=5.0,
                color=self.info_text_bg
            )
            self.glfont.set_size(20)
            self.glfont.set_color_float(self.info_text_color)
            self.glfont.draw_text(x, y, text)

            if self.vis_object_bbox and self.current_bbox is not None:
                x_min, y_min, x_max, y_max = self.current_bbox
                x_min_screen = x_min * 1280
                y_max_screen = y_min * 720

                box_text = f"{self.current_object.upper()} - {self.current_conf:.2f}"
                self.glfont.set_color_float(self.bbox_text_color)
                self.glfont.draw_text(x_min_screen + 5, y_max_screen - 5, box_text)

                # Adjust Y coordinates for OpenGL coordinate system
                y_min = 1 - y_min
                y_max = 1 - y_max

                bbox_points = np.array([
                    [x_min, y_min],  # Bottom-left
                    [x_max, y_min],  # Bottom-right
                    [x_max, y_min],  # Bottom-right
                    [x_max, y_max],  # Top-right
                    [x_max, y_max],  # Top-right
                    [x_min, y_max],  # Top-left
                    [x_min, y_max],  # Top-left
                    [x_min, y_min]   # Bottom-left
                ])
                draw_polyline_norm(
                    bbox_points,
                    thickness=3.0, color=self.bbox_color, line_type=gl.GL_LINE_LOOP
                )

    def deinit_ui(self):
        self.remove_menu()
        self.glfont = None

    def _predict_frame(self, raw):
        """Run object detection on the current frame."""
        raw_image_bytes = bytes(raw)
        frame = cv2.imdecode(np.frombuffer(raw_image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        results = self.model(frame, verbose=False)
        return results

    def _get_object_in_gaze(self, gaze_point, results):
        """Find the object under the gaze point with the highest confidence."""
        highest_confidence = 0
        detected_object = None
        bbox = None
        for result in results:
            boxes = result.boxes
            for i, box in enumerate(boxes.xyxyn):
                x_min, y_min, x_max, y_max = box.tolist()
                cls_conf = boxes.conf[i].item()
                cls_idx = int(boxes.cls[i].item())

                if cls_conf < self.min_prob:
                    continue

                # Adjust gaze point Y coordinate
                adjusted_gaze_y = 1 - gaze_point[1]

                if x_min <= gaze_point[0] <= x_max and y_min <= adjusted_gaze_y <= y_max:
                    if cls_conf > highest_confidence:
                        highest_confidence = cls_conf
                        detected_object = result.names[cls_idx]
                        bbox = (x_min, y_min, x_max, y_max)
        return detected_object, bbox, highest_confidence

    def _publish_event(self, events):
        """Publish a custom event when an object is detected under the gaze."""
        custom_datum = {
            "topic": self.CUSTOM_TOPIC,
            "timestamp": self.g_pool.get_timestamp(),
            "id": self.current_fixation['id'],
            "object": self.current_object,
            "bbox": [float(x) for x in self.current_bbox],
            "norm_pos": self.mean_fixation
        }
        events.setdefault(self.CUSTOM_TOPIC, []).append(custom_datum)

    def recent_events(self, events):
        """Handle incoming events to detect objects at fixation points."""
        fixations = events.get(self.TRIGGER_TOPIC, [])
        if fixations:
            for fixation in fixations:
                if self.current_fixation is None or fixation['id'] != self.current_fixation['id']:
                    # New fixation started
                    self._start_fixation(fixation)
                else:
                    # Continuing current fixation
                    self._update_fixation(fixation)
        elif self.current_fixation is not None:
            # Fixation ended
            self._end_fixation(events)

    def _start_fixation(self, fixation):
        """Initialize a new fixation."""
        self.current_fixation = fixation
        self.current_fixation_id = fixation['id']
        self.fixation_buffer = [fixation]
        self.logger.debug(f"Started new fixation id: {fixation['id']}")

    def _update_fixation(self, fixation):
        """Update the current fixation with new data."""
        self.fixation_buffer.append(fixation)
        duration = fixation['timestamp'] - self.fixation_buffer[0]['timestamp']
        if duration > self.max_duration:
            self.logger.debug(f"Fixation id {fixation['id']} duration exceeded max_duration.")
            self._reset_fixation()
        else:
            self.logger.debug(f"Updating fixation id: {fixation['id']}")

    def _end_fixation(self, events):
        """Process the fixation when it ends."""
        # Compute the mean fixation position
        self.mean_fixation = list(np.mean([f["norm_pos"] for f in self.fixation_buffer], axis=0))
        frame_data = events.get(self.FRAME_TOPIC, [])
        if frame_data:
            raw_data = frame_data[-1].get("__raw_data__", [None])
            if raw_data[0]:
                results = self._predict_frame(raw_data[0])
                obj, bbox, conf = self._get_object_in_gaze(self.mean_fixation, results)
                if obj:
                    self.current_object = obj
                    self.current_bbox = bbox
                    self.current_conf = conf
                    self.logger.debug(f"Fixation {self.current_fixation['id']} on {self.current_object}")
                    self._publish_event(events)
                else:
                    self.logger.debug(f"No object detected in gaze for fixation {self.current_fixation['id']}")
                    self.current_bbox = None
                    self.current_object = None
            else:
                self.logger.debug("No raw frame data available.")
        else:
            self.logger.debug("No frame data received.")
        self._reset_fixation()

    def _reset_fixation(self):
        """Reset variables after fixation processing is complete."""
        self.current_fixation = None
        self.fixation_buffer = []
        self.mean_fixation = None

