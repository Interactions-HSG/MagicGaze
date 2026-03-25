import logging
from plugin import Plugin
import numpy as np
from pyglui import ui
from pyglui.cygl.utils import RGBA, draw_rounded_rect
from pyglui.pyfontstash import fontstash


def cross_product(v1, v2):
    return v1[0] * v2[1] - v1[1] * v2[0]


def is_point_in_triangle(p1, p2, p3, p):
    def sign(a, b, c):
        return (a[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (a[1] - c[1])

    b1 = sign(p, p1, p2) < 0.0
    b2 = sign(p, p2, p3) < 0.0
    b3 = sign(p, p3, p1) < 0.0

    return (b1 == b2) and (b2 == b3)


class HeadGestureDetector(Plugin):
    CUSTOM_TOPIC = "head_gestures"
    TRIGGER_TOPIC = "objects"
    LEGEND_TEXT = "Head Gestures"

    icon_chr = chr(0xEC12)
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
        self.origin_distance_tr = 0.20  # Origin radius
        self.gesture_duration = 0.8     # Maximum gesture duration
        self.gap_max = 0.04             # Maximum allowed distance between gaze points
        self.error_tol = 20             # Error tolerance for gaps
        self.min_gaze_points = 30       # Minimum gaze points for gesture
        self.gaze_conf_tr = 0.6         # Gaze confidence threshold

        # Visualization variables
        self.info_text_color = (0.0, 0.0, 0.0, 1.0)  # Black Text
        self.info_text_bg = RGBA(0.8, 1.0, 0.8, 1.0)

        self.viz_text = ""
        self.viz_time = None
        self.gaze_buffer = []
        self.last_gesture = []
        self.trigger_event = None
        self.last_trigger_id = None
        self.curr_object = None
        self.direction = None
        self.origin_pos = None
        self.start_time = None
        self.gap_counter = 0

        self.logger.info("GazeGestureDetector initialized.")

    @classmethod
    def parse_pretty_class_name(cls) -> str:
        return "Head Gesture Detector"

    def init_ui(self):
        self.add_menu()
        self.menu.label = "Gaze Gesture Detector Settings"
        self.menu.append(
            ui.Info_Text(
                "This plugin detects head gestures based on gaze movements relative to a fixation point."
            )
        )
        self.menu.append(
            ui.Slider(
                "origin_distance_tr",
                self,
                min=0.01,
                step=0.01,
                max=1,
                label="Origin Radius"
            )
        )
        self.menu.append(
            ui.Slider(
                "gesture_duration",
                self,
                min=0.1,
                step=0.1,
                max=5,
                label="Gesture Max Duration"
            )
        )
        self.menu.append(
            ui.Slider(
                "gap_max",
                self,
                min=0.01,
                step=0.01,
                max=0.2,
                label="Max Gap Threshold"
            )
        )
        self.menu.append(
            ui.Slider(
                "error_tol",
                self,
                min=1,
                step=1,
                max=100,
                label="Error Tolerance"
            )
        )
        self.menu.append(
            ui.Slider(
                "gaze_conf_tr",
                self,
                min=0.01,
                step=0.01,
                max=1,
                label="Min Gaze Confidence"
            )
        )

        # Initialize font context for text rendering
        self.glfont = fontstash.Context()
        self.glfont.add_font("opensans", ui.get_opensans_font_path())
        self.glfont.set_size(20)
        self.glfont.set_color_float(self.info_text_color)  # Black Text

    def gl_display(self):
        # Position where the text will be drawn
        x_legend, y_legend = 20, 640

        # Draw the rounded rectangle
        draw_rounded_rect(
            (x_legend - 10, y_legend - 17),
            (x_legend + (8 * len(self.LEGEND_TEXT)), 23),
            corner_radius=5.0,
            color=self.info_text_bg
        )
        self.glfont.draw_text(x_legend, y_legend, self.LEGEND_TEXT)

        if self.viz_text:
            # Position where the text will be drawn
            x, y = 20, 110

            # Draw the rounded rectangle
            draw_rounded_rect(
                (x - 10, y - 17),
                (x + (8 * len(self.viz_text)), 23),
                corner_radius=5.0,
                color=self.info_text_bg
            )
            self.glfont.draw_text(x, y, self.viz_text)

    def deinit_ui(self):
        self.remove_menu()
        self.glfont = None

    def _gaze_in_origin(self, gaze):
        """Check if gaze point is within the origin radius."""
        origin_distance = np.linalg.norm(
            np.array(gaze['norm_pos']) - np.array(self.origin_pos)
        )
        return origin_distance < self.origin_distance_tr

    def _check_distance_threshold(self, gaze):
        """Check if the gaze point is within the allowed distance threshold."""
        if not self.gaze_buffer:
            distance = np.linalg.norm(
                np.array(gaze['norm_pos']) - np.array(self.origin_pos)
            )
            return distance < (self.origin_distance_tr + self.gap_max)
        else:
            last_gaze = self.gaze_buffer[-1]
            distance = np.linalg.norm(
                np.array(gaze['norm_pos']) - np.array(last_gaze['norm_pos'])
            )
            return distance < self.gap_max

    def _detect_direction(self, mean_gaze):
        """Determine the direction of the gesture based on the mean gaze point."""
        delta = np.array(mean_gaze) - np.array(self.origin_pos)
        angle = np.degrees(np.arctan2(delta[1], delta[0])) % 360

        if 45 <= angle < 135:
            return "down"
        elif 135 <= angle < 225:
            return "right"
        elif 225 <= angle < 315:
            return "up"
        else:
            return "left"

    def _publish_event(self, events):
        """Publish a custom event when a gesture is detected."""
        custom_datum = {
            "topic": self.CUSTOM_TOPIC,
            "timestamp": self.g_pool.get_timestamp(),
            "object": self.curr_object,
            "direction": self.direction,
        }
        events.setdefault(self.CUSTOM_TOPIC, []).append(custom_datum)

    def _set_viz_text(self):
        """Set the visualization text to display the detected gesture."""
        if all([self.last_trigger_id, self.direction, self.curr_object]):
            self.viz_text = (
                f"{self.last_trigger_id} - {self.direction.upper()} on {self.curr_object.upper()}"
            )

    def recent_events(self, events):
        gaze_data = events.get('gaze', [])
        # Filter out gaze data with low confidence
        gaze_data = [g for g in gaze_data if g['confidence'] > self.gaze_conf_tr]

        if not gaze_data:
            return

        if self.TRIGGER_TOPIC in events and self.trigger_event is None:
            self._start_gesture_recognition(events[self.TRIGGER_TOPIC][-1])
            return

        if self.trigger_event is not None:
            self._process_gaze_during_gesture(gaze_data, events)

    def _start_gesture_recognition(self, trigger_event):
        """Initialize variables to start gesture recognition."""
        self.logger.debug("Starting Gesture Recognition.")
        self.trigger_event = trigger_event
        self.last_trigger_id = self.trigger_event.get('id', None)
        self.curr_object = self.trigger_event.get('object', None)
        self.origin_pos = self.trigger_event.get('norm_pos', [0.5, 0.5])
        self.start_time = self.g_pool.get_timestamp()
        self.gap_counter = 0
        self.gaze_buffer.clear()
        self.direction = None

    def _process_gaze_during_gesture(self, gaze_data, events):
        """Process gaze data to detect gestures during an active gesture recognition phase."""
        current_time = self.g_pool.get_timestamp()
        for gaze in gaze_data:
            if self._gaze_in_origin(gaze) and not self.gaze_buffer:
                # Still at origin, gesture hasn't started
                self.start_time = current_time
                return
            elif not self._gaze_in_origin(gaze):
                # Gaze moved away from origin
                if self._check_distance_threshold(gaze):
                    self.gaze_buffer.append(gaze)
                    self.gap_counter = 0
                else:
                    self.gap_counter += 1
                    if self.gap_counter > self.error_tol:
                        self.logger.debug("Gesture discarded due to error tolerance exceeded.")
                        self._reset_gesture()
                        return
            elif self._gaze_in_origin(gaze) and self.gaze_buffer:
                # Gaze returned to origin, attempt to complete gesture
                self._complete_gesture(current_time, events)
                return

    def _complete_gesture(self, current_time, events):
        """Complete the gesture detection and publish the event if valid."""
        if len(self.gaze_buffer) < self.min_gaze_points:
            self.logger.debug("Gesture discarded due to insufficient gaze data.")
            self._reset_gesture()
            return

        duration = current_time - self.start_time
        if duration <= self.gesture_duration:
            mean_gaze = np.mean(
                [g['norm_pos'] for g in self.gaze_buffer], axis=0
            )
            self.direction = self._detect_direction(mean_gaze)
            self._set_viz_text()
            self._publish_event(events)
            self.logger.debug(
                f"Gesture detected: {self.direction.upper()} on {self.curr_object.upper()}"
            )
        else:
            self.logger.debug("Gesture discarded due to duration threshold exceeded.")
        self._reset_gesture()

    def _reset_gesture(self):
        """Reset all variables related to gesture detection."""
        self.trigger_event = None
        self.gaze_buffer.clear()
        self.gap_counter = 0
